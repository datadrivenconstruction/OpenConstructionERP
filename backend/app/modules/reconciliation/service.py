# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Event-reconciliation service - persistence + gather layer over the pure engine.

This module owns two responsibilities, both thin:

* **Gather**: read a project's heterogeneous source rows (correspondence, change
  orders, variations, management-of-change entries) and project each onto the
  pure engine's uniform :class:`CandidateRecord`. All scoring then happens in
  :mod:`app.modules.reconciliation.correlate` - the service never computes a
  confidence itself, it only adapts rows in.
* **Persist**: read and write :class:`RecordLink` rows, the durable record of a
  reviewer's confirm / reject decisions on the engine's suggestions.

Writes follow the platform convention: the service flushes, and the
request-scoped session dependency commits, so a failed request rolls back
cleanly. Every read is scoped to a single ``project_id`` so a row leaked under
the wrong project id is never returned (the engine itself also never links
across projects).
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reconciliation.correlate import (
    CandidateRecord,
    ScoredLink,
    find_links,
    normalize_subject,
)
from app.modules.reconciliation.models import (
    STATUS_CONFIRMED,
    STATUS_REJECTED,
    RecordLink,
)

# --------------------------------------------------------------------------- #
# Source-type tokens. One stable string per gathered source so a record's
# identity ``(record_type, record_id)`` is stable across reads and matches what
# a persisted link row stores. A new source type adds a token here and a gather
# block below; nothing else changes (the link table is generic).
# --------------------------------------------------------------------------- #

TYPE_CORRESPONDENCE = "correspondence"
TYPE_CHANGE_ORDER = "change_order"
TYPE_VARIATION_REQUEST = "variation_request"
TYPE_VARIATION_ORDER = "variation_order"
TYPE_NOTICE = "notice"
TYPE_MOC = "moc"


# --------------------------------------------------------------------------- #
# Endpoint canonicalisation (mirrors the engine's ordering so a stored row and
# a freshly scored link share one key).
# --------------------------------------------------------------------------- #

Endpoint = tuple[str, str]
LinkKey = tuple[str, str, str, str]


def canonical_pair(a: Endpoint, b: Endpoint) -> tuple[Endpoint, Endpoint]:
    """Order two ``(type, id)`` endpoints the way the engine does (smaller left).

    The link is undirected; storing the smaller endpoint as the *left* (the same
    rule :func:`correlate.score_pair` uses) means the one link has a single
    canonical key regardless of the order the caller named its ends.
    """
    return (a, b) if a <= b else (b, a)


def link_key(left: Endpoint, right: Endpoint) -> LinkKey:
    """Flatten a canonical endpoint pair into a hashable 4-tuple key."""
    left, right = canonical_pair(left, right)
    return (left[0], left[1], right[0], right[1])


def scored_link_key(link: ScoredLink) -> LinkKey:
    """The canonical key of an engine :class:`ScoredLink` (already canonical)."""
    return (link.left_type, link.left_id, link.right_type, link.right_id)


def record_link_row_key(row: RecordLink) -> LinkKey:
    """The canonical key of a persisted :class:`RecordLink` row.

    Re-canonicalised defensively so a row written before canonicalisation (or by
    another path) still keys the same as the engine's output.
    """
    return link_key((row.left_type, row.left_id), (row.right_type, row.right_id))


# --------------------------------------------------------------------------- #
# Gather: project source rows onto the engine's CandidateRecord.
# --------------------------------------------------------------------------- #


def _parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp string to a datetime, or None if unusable.

    The source tables store timestamps as ISO strings of varying width (date,
    date-time, date-time-with-offset). ``datetime.fromisoformat`` handles all of
    these on py3.11; an unparseable or blank value yields ``None`` so the record
    simply has no date-proximity signal rather than raising.
    """
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        # A bare date such as "2026-05-30" already parses; anything else
        # (free text, partial timestamp) is treated as undated.
        return None


def _refs_for(*codes: str | None) -> tuple[str, ...]:
    """Collect non-blank explicit reference codes (e.g. a CO ``code``) as a tuple.

    The engine re-parses and normalises these, so passing a record's own tracked
    code (``"CO-014"``) lets the shared-reference signal fire between, say, a
    change order and a piece of correspondence that mentions ``CO-14`` in its
    subject.
    """
    return tuple(c.strip() for c in codes if c and c.strip())


async def _gather_correspondence(session: AsyncSession, project_id: uuid.UUID) -> list[CandidateRecord]:
    """Project a project's correspondence rows onto candidate records."""
    from app.modules.correspondence.models import Correspondence

    rows = (
        (await session.execute(select(Correspondence).where(Correspondence.project_id == project_id))).scalars().all()
    )
    records: list[CandidateRecord] = []
    for row in rows:
        # Correspondence has no single "party" column; the originating contact id
        # is the closest stable signal for the same-party-and-time check.
        records.append(
            CandidateRecord(
                record_type=TYPE_CORRESPONDENCE,
                record_id=str(row.id),
                project_id=str(project_id),
                subject=row.subject or "",
                body=row.notes or "",
                party=(row.from_contact_id or None),
                occurred_at=_parse_dt(row.date_sent or row.date_received),
                refs=_refs_for(row.reference_number, row.linked_rfi_id),
            )
        )
    return records


async def _gather_change_orders(session: AsyncSession, project_id: uuid.UUID) -> list[CandidateRecord]:
    """Project a project's change orders onto candidate records."""
    from app.modules.changeorders.models import ChangeOrder

    rows = (await session.execute(select(ChangeOrder).where(ChangeOrder.project_id == project_id))).scalars().all()
    records: list[CandidateRecord] = []
    for row in rows:
        records.append(
            CandidateRecord(
                record_type=TYPE_CHANGE_ORDER,
                record_id=str(row.id),
                project_id=str(project_id),
                subject=row.title or "",
                body=row.description or "",
                # The party owing the next action is the best available
                # responsible-party proxy on a change order.
                party=(row.ball_in_court or row.submitted_by or None),
                occurred_at=_parse_dt(row.submitted_at or row.approved_at),
                refs=_refs_for(row.code),
            )
        )
    return records


async def _gather_variations(session: AsyncSession, project_id: uuid.UUID) -> list[CandidateRecord]:
    """Project a project's variation notices / requests / orders onto candidates."""
    from app.modules.variations.models import (
        Notice,
        VariationOrder,
        VariationRequest,
    )

    records: list[CandidateRecord] = []

    notices = (await session.execute(select(Notice).where(Notice.project_id == project_id))).scalars().all()
    for row in notices:
        records.append(
            CandidateRecord(
                record_type=TYPE_NOTICE,
                record_id=str(row.id),
                project_id=str(project_id),
                subject=row.title or "",
                body=row.description or "",
                party=(row.ball_in_court or row.raised_by or None),
                occurred_at=_parse_dt(row.raised_at),
                refs=_refs_for(row.code),
            )
        )

    requests = (
        (await session.execute(select(VariationRequest).where(VariationRequest.project_id == project_id)))
        .scalars()
        .all()
    )
    for row in requests:
        records.append(
            CandidateRecord(
                record_type=TYPE_VARIATION_REQUEST,
                record_id=str(row.id),
                project_id=str(project_id),
                subject=row.title or "",
                body=row.description or "",
                party=(row.ball_in_court or row.requested_by or None),
                occurred_at=_parse_dt(row.submitted_at or row.requested_at),
                refs=_refs_for(row.code),
            )
        )

    orders = (
        (await session.execute(select(VariationOrder).where(VariationOrder.project_id == project_id))).scalars().all()
    )
    for row in orders:
        records.append(
            CandidateRecord(
                record_type=TYPE_VARIATION_ORDER,
                record_id=str(row.id),
                project_id=str(project_id),
                subject=row.title or "",
                body="",
                party=(row.ball_in_court or row.signed_by or None),
                occurred_at=_parse_dt(row.agreed_at),
                refs=_refs_for(row.code),
            )
        )

    return records


async def _gather_moc(session: AsyncSession, project_id: uuid.UUID) -> list[CandidateRecord]:
    """Project a project's management-of-change entries onto candidate records."""
    from app.modules.moc.models import MoCEntry

    rows = (await session.execute(select(MoCEntry).where(MoCEntry.project_id == project_id))).scalars().all()
    records: list[CandidateRecord] = []
    for row in rows:
        records.append(
            CandidateRecord(
                record_type=TYPE_MOC,
                record_id=str(row.id),
                project_id=str(project_id),
                subject=row.title or "",
                body=row.description or "",
                party=(row.ball_in_court or row.proposed_by or None),
                occurred_at=_parse_dt(row.proposed_at or row.decided_at),
                # MoC carries its own code plus soft links to a CO / VR / VO; the
                # code rendered as "MoC-<n>" already matches the engine vocabulary.
                refs=_refs_for(row.code),
            )
        )
    return records


async def gather_candidates(session: AsyncSession, project_id: uuid.UUID) -> list[CandidateRecord]:
    """Gather every reconcilable source record for a project as candidates.

    The MVP source set is correspondence + change orders + variations (notice /
    request / order) + management-of-change entries. The result is deterministic:
    each gather block reads in a stable order and the engine sorts its output, so
    identical data always yields an identical thread. A module that is not
    installed (its models cannot be imported) is skipped rather than failing the
    whole gather - reconciliation degrades to the sources that are present.
    """
    records: list[CandidateRecord] = []
    gatherers = (
        _gather_correspondence,
        _gather_change_orders,
        _gather_variations,
        _gather_moc,
    )
    for gather in gatherers:
        try:
            records.extend(await gather(session, project_id))
        except ModuleNotFoundError:
            # Optional source module not installed in this deployment - skip it.
            continue
    return records


# --------------------------------------------------------------------------- #
# Thread assembly.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ThreadRecord:
    """A record in an assembled thread, plus whether it is the seed."""

    record: CandidateRecord
    is_seed: bool


@dataclass(frozen=True)
class ThreadLink:
    """A scored link in an assembled thread, plus its persisted decision state."""

    link: ScoredLink
    status: str
    link_id: str | None


@dataclass(frozen=True)
class EventThread:
    """The reconciled cross-channel thread assembled around one seed event."""

    project_id: str
    event_key: str
    seed_type: str | None
    seed_id: str | None
    records: list[ThreadRecord]
    links: list[ThreadLink]
    confirmed_count: int
    rejected_count: int


def _record_sort_key(rec: CandidateRecord) -> tuple[int, str, str, str]:
    """Deterministic timeline order: dated first by time, then by identity.

    Records with an ``occurred_at`` sort ahead of undated ones (group 0 vs 1) and
    within the dated group by the timestamp's ISO string; ties (and the undated
    group) fall back to ``(record_type, record_id)`` so ordering is total and
    stable for identical input. Mixed naive/aware timestamps are not compared
    directly (which would raise); the ISO string is used purely as a sort key.
    """
    occurred = rec.occurred_at
    if occurred is not None:
        return (0, occurred.isoformat(), rec.record_type, rec.record_id)
    return (1, "", rec.record_type, rec.record_id)


def _resolve_seeds(
    event_key: str,
    records: list[CandidateRecord],
) -> tuple[set[Endpoint], str | None, str | None]:
    """Resolve ``event_key`` to the seed endpoints a thread is grown from.

    Two interpretations, tried in order:

    * **Seed record key** ``"<record_type>:<record_id>"`` (the primary form, and
      what the thread view echoes back). Resolves to that single record when it
      exists among the gathered candidates. ``seed_type`` / ``seed_id`` are then
      the record's own type and id.
    * **Normalized-subject key** (any ``event_key`` without a ``":"``, or a
      ``type:id`` that matches no record). Resolves to *every* candidate whose
      :func:`correlate.normalize_subject` of its subject equals the normalised
      key, so an event named by its subject line gathers all same-subject
      records. ``seed_type`` / ``seed_id`` are ``None`` (no single seed row).

    Returns ``(seed_endpoints, seed_type, seed_id)``; an empty seed set means the
    key matched nothing (the thread is then empty).
    """
    by_endpoint = {(r.record_type, r.record_id): r for r in records}

    if ":" in event_key:
        rtype, _, rid = event_key.partition(":")
        endpoint = (rtype, rid)
        if endpoint in by_endpoint:
            return {endpoint}, rtype, rid

    # Fall back to a normalized-subject match across all candidates.
    target = normalize_subject(event_key)
    seeds = {(r.record_type, r.record_id) for r in records if target and normalize_subject(r.subject) == target}
    return seeds, None, None


def assemble_thread(
    project_id: uuid.UUID,
    event_key: str,
    candidates: list[CandidateRecord],
    scored: list[ScoredLink],
    persisted: dict[LinkKey, RecordLink],
) -> EventThread:
    """Assemble the reconciled thread around ``event_key`` (pure, no I/O).

    Grows the connected component of records reachable from the seed(s) through
    links at or above the engine threshold, treating a *rejected* persisted link
    as cut (it does not connect its endpoints). The returned timeline is the
    deterministically ordered records of that component; the returned links are
    the scored links wholly inside it, strongest first, each annotated with its
    persisted decision state (``suggested`` when no row exists). Splitting the
    pure assembly out keeps it unit-testable without the database.
    """
    by_endpoint = {(r.record_type, r.record_id): r for r in candidates}
    seeds, seed_type, seed_id = _resolve_seeds(event_key, candidates)

    # Adjacency over non-rejected links only - a rejected link must not stitch
    # two records into the same thread.
    adjacency: dict[Endpoint, list[Endpoint]] = {}
    live_links: list[ScoredLink] = []
    for link in scored:
        key = scored_link_key(link)
        row = persisted.get(key)
        if row is not None and row.status == STATUS_REJECTED:
            continue
        left = (link.left_type, link.left_id)
        right = (link.right_type, link.right_id)
        adjacency.setdefault(left, []).append(right)
        adjacency.setdefault(right, []).append(left)
        live_links.append(link)

    # Breadth-first reach from every seed endpoint through the live adjacency.
    component: set[Endpoint] = set()
    queue: deque[Endpoint] = deque(ep for ep in seeds if ep in by_endpoint)
    component.update(queue)
    while queue:
        current = queue.popleft()
        for neighbour in adjacency.get(current, ()):
            if neighbour not in component and neighbour in by_endpoint:
                component.add(neighbour)
                queue.append(neighbour)

    # Always include any seed that exists as a record even if it has no links, so
    # a lone seed still returns itself.
    for ep in seeds:
        if ep in by_endpoint:
            component.add(ep)

    records = [ThreadRecord(record=by_endpoint[ep], is_seed=ep in seeds) for ep in component]
    records.sort(key=lambda tr: _record_sort_key(tr.record))

    # Live links wholly inside the component, each annotated with its decision.
    # Rejected links never reach here (they were cut from ``live_links``), so a
    # link shown in the thread is either a bare suggestion or a confirmation.
    thread_links: list[ThreadLink] = []
    confirmed = 0
    for link in live_links:
        left = (link.left_type, link.left_id)
        right = (link.right_type, link.right_id)
        if left not in component or right not in component:
            continue
        row = persisted.get(scored_link_key(link))
        status = row.status if row is not None else "suggested"
        if status == STATUS_CONFIRMED:
            confirmed += 1
        thread_links.append(
            ThreadLink(
                link=link,
                status=status,
                link_id=str(row.id) if row is not None else None,
            )
        )

    # Rejected decisions are cut from the thread itself, but reporting how many
    # suggestions touching these records a reviewer has dismissed is useful
    # context. Count persisted rejections whose both endpoints are in-component.
    rejected = sum(
        1
        for row in persisted.values()
        if row.status == STATUS_REJECTED
        and (row.left_type, row.left_id) in component
        and (row.right_type, row.right_id) in component
    )

    # The engine already returns links strongest-first; preserve that order.
    return EventThread(
        project_id=str(project_id),
        event_key=event_key,
        seed_type=seed_type,
        seed_id=seed_id,
        records=records,
        links=thread_links,
        confirmed_count=confirmed,
        rejected_count=rejected,
    )


async def list_record_links(session: AsyncSession, project_id: uuid.UUID) -> list[RecordLink]:
    """Return every persisted record-link decision for a project, oldest first."""
    stmt = select(RecordLink).where(RecordLink.project_id == project_id).order_by(RecordLink.created_at)
    return list((await session.execute(stmt)).scalars().all())


async def build_event_thread(
    session: AsyncSession,
    project_id: uuid.UUID,
    event_key: str,
) -> EventThread:
    """Gather, score and assemble the reconciled thread for one event.

    Reads the project's source rows, scores every same-project candidate pair
    with the pure engine, overlays the persisted confirm / reject decisions, and
    returns the thread grown from the seed ``event_key``. Performs no writes.
    """
    candidates = await gather_candidates(session, project_id)
    scored = find_links(candidates)
    rows = await list_record_links(session, project_id)
    persisted = {record_link_row_key(row): row for row in rows}
    return assemble_thread(project_id, event_key, candidates, scored, persisted)


# --------------------------------------------------------------------------- #
# Persisting a confirm / reject decision.
# --------------------------------------------------------------------------- #


def _coerce_confidence(value: float | None) -> Decimal | None:
    """Coerce a wire confidence float to a Decimal, or None when absent/invalid.

    Kept as a ratio (NUMERIC(6,4) on the column); an out-of-range or unparseable
    value is dropped rather than persisted so a bad score never corrupts a row.
    """
    if value is None:
        return None
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if dec < 0 or dec > 1:
        return None
    return dec


async def get_record_link(
    session: AsyncSession,
    project_id: uuid.UUID,
    left: Endpoint,
    right: Endpoint,
    relation: str,
) -> RecordLink | None:
    """Fetch the one persisted link for a canonical endpoint pair + relation.

    Scoped to the project so a link under another project is never returned
    (IDOR-safe). The endpoints are canonicalised first so either argument order
    finds the same row.
    """
    left, right = canonical_pair(left, right)
    stmt = select(RecordLink).where(
        RecordLink.project_id == project_id,
        RecordLink.left_type == left[0],
        RecordLink.left_id == left[1],
        RecordLink.right_type == right[0],
        RecordLink.right_id == right[1],
        RecordLink.relation == relation,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def decide_record_link(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    left: Endpoint,
    right: Endpoint,
    relation: str,
    status: str,
    confidence: float | None = None,
    created_by: str | None = None,
) -> RecordLink:
    """Persist a confirm / reject decision on a correlation (idempotent upsert).

    The link is identified by its canonical endpoint pair and ``relation``; if a
    row already exists its ``status`` (and ``confidence`` when a new one is
    supplied) is updated, otherwise a new row is created. Returns the stored row.
    Raises :class:`ValueError` for a status outside ``confirmed`` / ``rejected``
    (the router renders that as a 422). Flushes; the request dependency commits.
    """
    if status not in (STATUS_CONFIRMED, STATUS_REJECTED):
        raise ValueError(f"status must be one of confirmed / rejected, got {status!r}")

    left, right = canonical_pair(left, right)
    coerced = _coerce_confidence(confidence)

    existing = await get_record_link(session, project_id, left, right, relation)
    if existing is not None:
        existing.status = status
        if coerced is not None:
            existing.confidence = coerced
        await session.flush()
        return existing

    row = RecordLink(
        project_id=project_id,
        left_type=left[0],
        left_id=left[1],
        right_type=right[0],
        right_id=right[1],
        relation=relation or "same_event",
        confidence=coerced if coerced is not None else Decimal("0"),
        status=status,
        created_by=created_by,
    )
    session.add(row)
    await session.flush()
    return row
