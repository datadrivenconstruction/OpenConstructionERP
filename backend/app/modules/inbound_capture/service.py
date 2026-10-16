# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Inbound capture service - persist a normalized inbound message as correspondence.

The pure :mod:`~app.modules.inbound_capture.normalize` engine has already
flattened the channel payload to a canonical
:class:`~app.modules.inbound_capture.normalize.InboundMessage`. This thin layer
persists that message as an ``oe_correspondence`` row with ``direction =
incoming`` and announces it on the same ``correspondence.created`` event the
Correspondence module publishes, so the vector indexer and the comms digest see
captured messages exactly as they see hand-entered ones.

Two platform conventions are load-bearing here:

* Writes FLUSH, never commit. The request-scoped session dependency
  (:data:`app.dependencies.SessionDep`) commits after the handler returns and
  rolls back on error, so a failed capture leaves no half-written row.
* Capture is IDEMPOTENT on the provider's own message id. The same delivery
  captured twice (a retried webhook, a re-imported ``.eml``) shares a channel
  and external id, hence the engine's :func:`idempotency_key`; we look that key
  up first and return the existing row rather than inserting a duplicate.

Channel / external id storage
-----------------------------
The ``oe_correspondence`` table has no ``channel`` or ``external_message_id``
column, so this service stores both (plus the idempotency key and the rest of
the normalized envelope) under the row's ``metadata_`` JSON. That keeps the
module migration-free and mirrors how the cost-recovery service reads
``metadata_['traceability_band']``. If first-class columns are added later (see
the module REPORT), the idempotency lookup below is the one place that changes.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.correspondence.models import Correspondence
from app.modules.correspondence.repository import CorrespondenceRepository
from app.modules.correspondence.service import _safe_publish
from app.modules.inbound_capture.normalize import (
    CHANNEL_EMAIL,
    AttachmentRef,
    InboundMessage,
    idempotency_key,
)

#: Key under which the inbound envelope is stashed inside ``metadata_``. Kept in
#: one place so the idempotency lookup and the read projection agree.
META_KEY = "inbound_capture"

#: The Correspondence model constrains ``correspondence_type`` to a small enum
#: (``letter`` / ``email`` / ``notice`` / ``memo``). Captured email maps to
#: ``email``; every other channel (chat webhook, SMS) has no dedicated member, so
#: it is stored as ``notice`` with the true channel preserved in the metadata
#: envelope (``metadata_['inbound_capture']['channel']``).
_TYPE_EMAIL = "email"
_TYPE_OTHER = "notice"


def _correspondence_type_for(channel: str) -> str:
    """Map an inbound channel onto a valid correspondence type."""
    return _TYPE_EMAIL if channel == CHANNEL_EMAIL else _TYPE_OTHER


def _attachment_dict(att: AttachmentRef) -> dict[str, object]:
    """Render one :class:`AttachmentRef` as a JSON-safe dict for ``metadata_``."""
    return {
        "filename": att.filename,
        "content_type": att.content_type,
        "size_bytes": att.size_bytes,
        "storage_hint": att.storage_hint,
    }


def build_envelope(msg: InboundMessage) -> dict[str, object]:
    """Project a normalized message onto the ``metadata_`` envelope we persist.

    Carries everything the canonical shape holds that the typed correspondence
    columns cannot: the channel, the provider's external id, the idempotency key
    (the de-duplication anchor), the sender / recipients, the reply pointer, the
    attachment pointers and the breadcrumbs of anything the normalizer could not
    place. Stored under :data:`META_KEY` so it never collides with other
    metadata a caller might set.
    """
    return {
        "channel": msg.channel,
        "external_message_id": msg.external_id,
        "idempotency_key": idempotency_key(msg),
        "sender": msg.sender,
        "recipients": list(msg.recipients),
        "sent_at": msg.sent_at.isoformat(),
        "in_reply_to": msg.in_reply_to,
        "attachments": [_attachment_dict(a) for a in msg.attachments],
        "raw_refs": list(msg.raw_refs),
    }


def _envelope_of(row: Correspondence) -> dict[str, object]:
    """Return a row's inbound envelope (empty dict when absent / malformed)."""
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    envelope = meta.get(META_KEY)
    return envelope if isinstance(envelope, dict) else {}


async def find_by_idempotency_key(
    session: AsyncSession,
    project_id: uuid.UUID,
    key: str,
) -> Correspondence | None:
    """Find the already-captured inbound row for ``key`` in this project.

    SQL JSON containment is not portable across the dialects the platform runs
    on, so - following the same approach the BI-dashboard and clash repositories
    use - the incoming rows are fetched scoped to the project and the match is
    made in Python over the stored ``idempotency_key``. The candidate set is
    bounded to one project's incoming correspondence, so the read stays small.
    A blank key never matches (an external-id-less delivery is not
    de-duplicable; see :func:`capture_message`).
    """
    if not key:
        return None
    stmt = select(Correspondence).where(
        Correspondence.project_id == project_id,
        Correspondence.direction == "incoming",
    )
    rows = (await session.execute(stmt)).scalars().all()
    for row in rows:
        if _envelope_of(row).get("idempotency_key") == key:
            return row
    return None


def _subject_for(msg: InboundMessage) -> str:
    """A non-empty, header-safe subject for the correspondence row.

    The Correspondence column requires a non-empty subject. SMS and some chat
    deliveries carry none, so fall back to a stable channel-tagged placeholder.
    CR / LF and other control characters are stripped so a crafted subject can
    never inject an email header or break HTML rendering downstream (the same
    discipline the Correspondence schema enforces).
    """
    raw = msg.subject or ""
    cleaned = "".join(ch for ch in raw if ch == "\t" or ord(ch) >= 0x20)
    cleaned = " ".join(cleaned.split())
    if cleaned:
        return cleaned[:500]
    return f"[{msg.channel or 'inbound'} message]"


async def capture_message(
    session: AsyncSession,
    project_id: uuid.UUID,
    msg: InboundMessage,
    *,
    created_by: str | None = None,
) -> tuple[Correspondence, bool]:
    """Persist a normalized inbound message as incoming correspondence.

    Returns ``(row, deduplicated)``. When a message with the same channel and
    external id has already been captured for this project, the existing row is
    returned with ``deduplicated=True`` and nothing new is written - the
    idempotency contract. Otherwise a new ``oe_correspondence`` row is created
    with ``direction = incoming``, the inbound envelope stored under
    ``metadata_`` (see :func:`build_envelope`), a reference number allocated by
    the Correspondence repository's collision-safe generator, and
    ``correspondence.created`` published on the shared event path so the same
    downstream consumers fire as for hand-entered correspondence.

    Idempotency only applies when the provider supplied an external id. A
    delivery with a blank external id is not de-duplicable against other blank
    ones, so it is always inserted (and is the rare case a caller should expect
    a possible duplicate for); this matches the engine's documented caveat.
    """
    key = idempotency_key(msg)
    if msg.external_id:
        existing = await find_by_idempotency_key(session, project_id, key)
        if existing is not None:
            return existing, True

    envelope = build_envelope(msg)
    repo = CorrespondenceRepository(session)
    reference_number = await repo.next_reference_number(project_id)
    row = Correspondence(
        project_id=project_id,
        reference_number=reference_number,
        direction="incoming",
        subject=_subject_for(msg),
        correspondence_type=_correspondence_type_for(msg.channel),
        notes=msg.body or None,
        created_by=created_by,
        metadata_={META_KEY: envelope},
    )
    # ``repo.create`` flushes and re-raises IntegrityError on a reference-number
    # collision (concurrent capture). Mirror the Correspondence service's retry
    # so a parallel POST does not 500 on the unique (project, reference) index.
    row = await _create_with_retry(session, repo, row, project_id)
    # Same originator stamp as the Correspondence service's create path: a
    # message captured by a member of a project party belongs to that party.
    from app.modules.teams.party_access import stamp_originator

    await stamp_originator(
        session,
        entity_type="correspondence",
        project_id=project_id,
        entity_id=row.id,
        user_id=created_by,
    )

    # Reuse the EXACT event the Correspondence service publishes on create so
    # the vector indexer / comms digest treat a captured message like any other
    # incoming correspondence. ``_safe_publish`` defers past the request commit
    # and swallows bus errors so a hiccup never breaks capture.
    await _safe_publish(
        "correspondence.created",
        {
            "project_id": str(project_id),
            "correspondence_id": str(row.id),
            "reference_number": row.reference_number,
        },
    )
    return row, False


async def _create_with_retry(
    session: AsyncSession,
    repo: CorrespondenceRepository,
    row: Correspondence,
    project_id: uuid.UUID,
    *,
    max_attempts: int = 5,
) -> Correspondence:
    """Insert ``row``, re-rolling its reference number on a unique collision.

    The reference number is ``MAX(suffix)+1`` (TOCTOU under concurrent creates);
    the unique ``(project_id, reference_number)`` index turns a racing duplicate
    into an ``IntegrityError`` which we retry with a fresh number, exactly as the
    Correspondence service does. After ``max_attempts`` the last error
    propagates and the request rolls back.
    """
    from sqlalchemy.exc import IntegrityError

    last_exc: Exception | None = None
    for _ in range(max_attempts):
        try:
            return await repo.create(row)
        except IntegrityError as exc:
            last_exc = exc
            row.reference_number = await repo.next_reference_number(project_id)
    raise last_exc  # type: ignore[misc]  # loop runs at least once


# --- Read projection ---------------------------------------------------------


def _is_captured(row: Correspondence) -> bool:
    """Whether a correspondence row was captured through this gateway.

    The discriminator is the inbound envelope under ``metadata_[META_KEY]`` that
    :func:`capture_message` always writes - present only on rows this module
    created, so a hand-entered incoming letter is never mistaken for a captured
    message.
    """
    return bool(_envelope_of(row))


async def list_captured(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[Correspondence], int]:
    """List a project's captured inbound messages (newest first) + the total.

    Returns only rows this gateway created (those carrying the inbound envelope),
    not every incoming correspondence, so the admin view shows exactly what came
    through the capture endpoints. SQL JSON containment is not portable across the
    dialects the platform runs on, so - as the idempotency lookup does - the
    project's incoming rows are fetched and the envelope filter is applied in
    Python; the total reflects the captured count, and the page is sliced after
    the filter so ``limit`` counts captured rows. ``limit`` is clamped to a sane
    ceiling so a caller cannot ask for an unbounded scan.
    """
    capped = max(1, min(int(limit), 200))
    start = max(0, int(offset))
    stmt = (
        select(Correspondence)
        .where(
            Correspondence.project_id == project_id,
            Correspondence.direction == "incoming",
        )
        .order_by(Correspondence.created_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    captured = [r for r in rows if _is_captured(r)]
    total = len(captured)
    return captured[start : start + capped], total


def to_message_out_fields(row: Correspondence) -> dict[str, object]:
    """Project a captured correspondence row back to the inbound read shape.

    Reads the inbound envelope from ``metadata_`` so the API can return the
    normalized sender / recipients / attachments / breadcrumbs alongside the
    correspondence ids, without a second model. Tolerant of a row whose envelope
    is missing (a correspondence created outside this gateway), in which case the
    envelope-derived fields come back blank rather than raising.
    """
    envelope = _envelope_of(row)
    return {
        "correspondence_id": str(row.id),
        "project_id": str(row.project_id),
        "reference_number": row.reference_number or "",
        "channel": str(envelope.get("channel", "") or ""),
        "external_message_id": str(envelope.get("external_message_id", "") or ""),
        "idempotency_key": str(envelope.get("idempotency_key", "") or ""),
        "direction": row.direction or "",
        "sender": str(envelope.get("sender", "") or ""),
        "recipients": _as_str_list(envelope.get("recipients")),
        "sent_at": str(envelope.get("sent_at", "") or ""),
        "subject": row.subject or "",
        "body": row.notes or "",
        "in_reply_to": envelope.get("in_reply_to") or None,
        "attachments": _as_dict_list(envelope.get("attachments")),
        "raw_refs": _as_str_list(envelope.get("raw_refs")),
    }


def _as_str_list(value: object) -> list[str]:
    """Coerce a stored JSON value to a list of strings (empty when not a list)."""
    if not isinstance(value, list):
        return []
    return [str(v) for v in value]


def _as_dict_list(value: object) -> list[dict]:
    """Coerce a stored JSON value to a list of dicts (empty when not a list)."""
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, dict)]
