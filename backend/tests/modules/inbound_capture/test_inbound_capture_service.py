# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for inbound capture persistence (PostgreSQL, py3.12).

Exercises the service end to end on real PostgreSQL: each channel (email, chat
webhook, SMS) normalizes and persists as an INCOMING correspondence row with the
inbound envelope stored under ``metadata_``; the same delivery captured twice is
idempotent on the provider's external id (one row, ``deduplicated=True``); a
delivery with no external id is never de-duplicated; idempotency is fenced to one
project; and the ``correspondence.created`` event fires on a fresh capture but
not on a deduplicated one.

A second class drives the router handlers DIRECTLY (no TestClient - that hits the
asyncpg cross-loop issue on Windows) with the REAL ``verify_project_access`` to
prove the IDOR-404 access guard, and the webhook handler's signature seam (good
and bad signature) over a real request.
"""

from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.correspondence.models import Correspondence
from app.modules.inbound_capture.normalize import (
    normalize_email,
    normalize_sms,
    normalize_webhook,
)
from app.modules.inbound_capture.service import META_KEY, capture_message
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession, *, role: str = "admin") -> uuid.UUID:
    user = User(
        email=f"ic-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="IC",
        role=role,
    )
    session.add(user)
    await session.flush()
    return user.id


async def _project(session: AsyncSession, owner_id: uuid.UUID | None = None) -> uuid.UUID:
    owner = owner_id or await _user(session)
    proj = Project(name=f"IC {uuid.uuid4().hex[:6]}", owner_id=owner, currency="EUR")
    session.add(proj)
    await session.flush()
    return proj.id


def _envelope(row: Correspondence) -> dict:
    return row.metadata_[META_KEY]


# --- Channel maps + persists as incoming correspondence ----------------------


@pytest.mark.asyncio
async def test_email_persists_as_incoming_correspondence(session: AsyncSession) -> None:
    pid = await _project(session)
    msg = normalize_email(
        {
            "from": "gc@example.com",
            "to": ["pm@example.com", "qs@example.com"],
            "subject": "Re: RFI 12 response",
            "text": "See attached markup.",
            "message_id": "<abc@mail>",
            "in_reply_to": "<rfi12@mail>",
            "attachments": [{"filename": "markup.pdf", "content_type": "application/pdf", "size": 2048}],
        }
    )
    row, deduplicated = await capture_message(session, pid, msg)

    assert deduplicated is False
    assert row.direction == "incoming"
    assert row.correspondence_type == "email"
    assert row.project_id == pid
    assert row.reference_number.startswith("COR-")
    # Body lands on notes; subject is the normalized display subject.
    assert row.notes == "See attached markup."
    assert "RFI 12 response" in row.subject
    env = _envelope(row)
    assert env["channel"] == "email"
    assert env["external_message_id"] == "<abc@mail>"
    assert env["sender"] == "gc@example.com"
    assert env["recipients"] == ["pm@example.com", "qs@example.com"]
    assert env["in_reply_to"] == "<rfi12@mail>"
    assert env["attachments"][0]["filename"] == "markup.pdf"
    assert env["idempotency_key"]


@pytest.mark.asyncio
async def test_webhook_persists_as_incoming_notice(session: AsyncSession) -> None:
    pid = await _project(session)
    msg = normalize_webhook(
        {
            "id": "evt_1",
            "user": "site.foreman",
            "text": "Concrete pour delayed to Friday.",
            "channel": "site-updates",
            "thread_id": "T-77",
        },
        channel_hint="chat",
    )
    row, deduplicated = await capture_message(session, pid, msg)

    assert deduplicated is False
    assert row.direction == "incoming"
    # No correspondence-type enum member for chat -> stored as notice, true
    # channel preserved in the envelope.
    assert row.correspondence_type == "notice"
    env = _envelope(row)
    assert env["channel"] == "chat"
    assert env["external_message_id"] == "evt_1"
    assert env["sender"] == "site.foreman"
    assert env["in_reply_to"] == "T-77"


@pytest.mark.asyncio
async def test_sms_persists_with_placeholder_subject(session: AsyncSession) -> None:
    pid = await _project(session)
    msg = normalize_sms(
        {
            "from": "+15551230000",
            "to": "+15559990000",
            "text": "On site, gate locked.",
            "sms_id": "SM123",
        }
    )
    row, deduplicated = await capture_message(session, pid, msg)

    assert deduplicated is False
    assert row.direction == "incoming"
    assert row.correspondence_type == "notice"
    # SMS has no subject; a non-empty placeholder satisfies the NOT NULL column.
    assert row.subject == "[sms message]"
    assert row.notes == "On site, gate locked."
    env = _envelope(row)
    assert env["channel"] == "sms"
    assert env["external_message_id"] == "SM123"
    assert env["sender"] == "+15551230000"


# --- Idempotency on external_message_id --------------------------------------


@pytest.mark.asyncio
async def test_capture_is_idempotent_on_external_id(session: AsyncSession) -> None:
    pid = await _project(session)
    payload = {"id": "evt_dup", "user": "alice", "text": "ping"}

    first, dup_first = await capture_message(session, pid, normalize_webhook(payload))
    second, dup_second = await capture_message(session, pid, normalize_webhook(payload))

    assert dup_first is False
    assert dup_second is True
    # Same row returned, and only ONE incoming row exists for the project.
    assert second.id == first.id
    rows = (await session.execute(select(Correspondence).where(Correspondence.project_id == pid))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_blank_external_id_is_not_deduplicated(session: AsyncSession) -> None:
    pid = await _project(session)
    # No id field at all -> blank external id -> not de-duplicable, two rows.
    payload = {"user": "bob", "text": "no id here"}

    first, dup_first = await capture_message(session, pid, normalize_webhook(payload))
    second, dup_second = await capture_message(session, pid, normalize_webhook(payload))

    assert dup_first is False
    assert dup_second is False
    assert second.id != first.id
    rows = (await session.execute(select(Correspondence).where(Correspondence.project_id == pid))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_idempotency_is_scoped_per_project(session: AsyncSession) -> None:
    pid_a = await _project(session)
    pid_b = await _project(session)
    payload = {"id": "evt_shared", "user": "carol", "text": "x"}

    row_a, _ = await capture_message(session, pid_a, normalize_webhook(payload))
    # Same external id under a DIFFERENT project is a distinct capture, not a dup.
    row_b, dup_b = await capture_message(session, pid_b, normalize_webhook(payload))

    assert dup_b is False
    assert row_b.id != row_a.id
    assert row_a.project_id == pid_a
    assert row_b.project_id == pid_b


# --- Event publication --------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_capture_publishes_correspondence_created(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = await _project(session)
    published: list[tuple[str, dict]] = []

    async def _spy(name: str, data: dict, source_module: str = "oe_correspondence") -> None:
        published.append((name, data))

    # Patch the shared publish helper the service reuses from correspondence.
    monkeypatch.setattr("app.modules.inbound_capture.service._safe_publish", _spy)

    payload = {"id": "evt_pub", "user": "dan", "text": "hello"}
    row, _ = await capture_message(session, pid, normalize_webhook(payload))
    # Fresh capture -> exactly one correspondence.created for the new row.
    assert published == [
        (
            "correspondence.created",
            {
                "project_id": str(pid),
                "correspondence_id": str(row.id),
                "reference_number": row.reference_number,
            },
        )
    ]

    # A deduplicated re-capture must NOT publish again.
    published.clear()
    await capture_message(session, pid, normalize_webhook(payload))
    assert published == []


# --- Router auth / IDOR / signature seam (direct handler invocation) ---------


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


class _StubRequest:
    """Minimal stand-in for starlette Request: raw body + header mapping.

    The webhook handler only touches ``request.body()`` and ``request.headers``,
    so this avoids building a full ASGI scope (and a TestClient thread).
    """

    def __init__(self, body: bytes, headers: dict[str, str]) -> None:
        self._body = body
        # Header lookups in the seam are lower-cased already.
        self.headers = {k.lower(): v for k, v in headers.items()}

    async def body(self) -> bytes:
        return self._body


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_email_handler_idor_returns_404_for_non_member(db_session: AsyncSession) -> None:
    from fastapi import HTTPException

    from app.modules.inbound_capture.router import capture_inbound_email
    from app.modules.inbound_capture.schemas import InboundEmailRequest

    owner = await _user(db_session, role="manager")
    outsider = await _user(db_session, role="manager")  # NOT owner/admin/member
    pid = await _project(db_session, owner_id=owner)

    req = InboundEmailRequest(project_id=str(pid), payload={"id": "<x@m>", "subject": "hi", "text": "body"})
    with pytest.raises(HTTPException) as exc:
        await capture_inbound_email(req, db_session, user_id=str(outsider))
    # IDOR-safe: missing == denied == 404.
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_email_handler_succeeds_for_owner(db_session: AsyncSession) -> None:
    from app.modules.inbound_capture.router import capture_inbound_email
    from app.modules.inbound_capture.schemas import InboundEmailRequest

    owner = await _user(db_session, role="manager")
    pid = await _project(db_session, owner_id=owner)

    req = InboundEmailRequest(
        project_id=str(pid),
        payload={"id": "<owner@m>", "from": "a@b.com", "subject": "Hello", "text": "Body"},
    )
    out = await capture_inbound_email(req, db_session, user_id=str(owner))
    assert out.direction == "incoming"
    assert out.channel == "email"
    assert out.external_message_id == "<owner@m>"
    assert out.deduplicated is False


@pytest.mark.asyncio
async def test_webhook_handler_rejects_bad_signature(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    from app.modules.inbound_capture.router import capture_inbound_webhook

    owner = await _user(db_session, role="manager")
    pid = await _project(db_session, owner_id=owner)
    monkeypatch.setenv("INBOUND_CAPTURE_SECRET__TWILIO", "s3cr3t")

    body = json.dumps({"project_id": str(pid), "payload": {"id": "SM1", "text": "hi"}}).encode()
    req = _StubRequest(body, {"x-inbound-signature": "deadbeef"})  # wrong digest
    with pytest.raises(HTTPException) as exc:
        await capture_inbound_webhook("twilio", req, db_session, user_id=str(owner))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_webhook_handler_captures_with_valid_signature(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib
    import hmac

    from app.modules.inbound_capture.router import capture_inbound_webhook

    owner = await _user(db_session, role="manager")
    pid = await _project(db_session, owner_id=owner)
    secret = "s3cr3t"
    monkeypatch.setenv("INBOUND_CAPTURE_SECRET__TWILIO", secret)

    body = json.dumps(
        {"project_id": str(pid), "channel": "sms", "payload": {"id": "SM9", "from": "+1", "text": "yo"}}
    ).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    req = _StubRequest(body, {"x-inbound-signature": sig})

    out = await capture_inbound_webhook("twilio", req, db_session, user_id=str(owner))
    assert out.direction == "incoming"
    assert out.channel == "sms"
    assert out.external_message_id == "SM9"
    assert out.body == "yo"

    # The datetime echoed back is the engine's epoch fallback when none supplied;
    # assert it round-tripped as an ISO string rather than crashing.
    assert "T" in out.sent_at
    # Sanity: the persisted row exists and is incoming.
    row = await db_session.get(Correspondence, uuid.UUID(out.correspondence_id))
    assert row is not None
    assert row.direction == "incoming"
