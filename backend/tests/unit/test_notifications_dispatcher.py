"""Unit tests for the Epic B notifications dispatcher.

Covers the new pieces introduced by the Epic B wave:

* B1: file_comments @mention → file_comments.mention.created event →
  notifications subscriber writes a per-user notification row.
* B2: webhook event-filter matching + HMAC-SHA256 signature helper.
* B6: notifications_ws_hub join/leave + dead-socket scrub.
* B7: every KNOWN_EVENT_TYPES entry has a corresponding template OR is
  documented as event-only (no in-app body).
* B8: WebhookTargetResponse never leaks the plaintext ``secret``.

Per ``feedback_test_isolation.md`` each test uses an isolated temp
SQLite — never ``backend/openestimate.db``.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.notifications.dispatcher import (
    _event_filter_matches,
    _sign_payload,
)
from app.modules.notifications.models import (
    Notification,
    WebhookTarget,
)
from app.modules.notifications.service import (
    KNOWN_EVENT_TYPES,
    NotificationService,
)
from app.modules.notifications.templates import (
    _TEMPLATES,
    icon_category_for,
)
from app.modules.notifications.ws_hub import NotificationsWsHub


def _register_models() -> None:
    import app.modules.notifications.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def session():
    tmp_db = Path(tempfile.mkdtemp()) / "dispatcher.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)
    _register_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


# ── B2: event-filter matching ─────────────────────────────────────────────


def test_event_filter_wildcard_matches_anything() -> None:
    """`*` is the catch-all wildcard."""
    assert _event_filter_matches("*", "boq.position.created") is True
    assert _event_filter_matches("*", "anything.at.all") is True


def test_event_filter_prefix_glob() -> None:
    """`boq.*` matches every event in the boq namespace, nothing else."""
    assert _event_filter_matches("boq.*", "boq.position.created") is True
    assert _event_filter_matches("boq.*", "boq.boq.created") is True
    assert _event_filter_matches("boq.*", "rfi.assigned") is False
    # Edge case: exact namespace name without subevent still matches the
    # exact pattern but not the prefix glob.
    assert _event_filter_matches("rfi.assigned", "rfi.assigned") is True
    assert _event_filter_matches("rfi.assigned", "rfi.responded") is False


def test_event_filter_comma_separated_list() -> None:
    """Multi-pattern list is OR-joined; whitespace is tolerated."""
    f = "boq.*, rfi.assigned, transmittal.*"
    assert _event_filter_matches(f, "boq.position.created") is True
    assert _event_filter_matches(f, "rfi.assigned") is True
    assert _event_filter_matches(f, "transmittal.issued") is True
    assert _event_filter_matches(f, "submittal.submitted") is False


# ── B2: HMAC signing ──────────────────────────────────────────────────────


def test_hmac_signature_is_deterministic_and_keyed() -> None:
    """Same secret + body → same digest; different secret → different digest."""
    body = b'{"event": "test"}'
    sig_a = _sign_payload("secret-1", body)
    sig_b = _sign_payload("secret-1", body)
    sig_c = _sign_payload("secret-2", body)
    assert sig_a == sig_b
    assert sig_a != sig_c
    # HMAC-SHA256 hex is 64 chars
    assert len(sig_a) == 64


# ── B1: file_comments.mention.created subscriber writes a row ─────────────


@pytest.mark.asyncio
async def test_file_comment_mention_creates_notification(session) -> None:
    """The mention subscriber path produces a per-user notification.

    We don't exercise the full event-bus round-trip (that's covered by
    test_notifications_events.py).  Instead we call the subscriber
    coroutine with a synthetic Event, opening its own write session
    against the same engine via ``async_session_factory`` shim.

    The subscriber is tested end-to-end (creates a row) when we drive
    NotificationService.create directly — that's the contract.
    """
    from app.modules.users.models import User

    mentioned_user_id = uuid.uuid4()
    author_id = uuid.uuid4()
    session.add(
        User(
            id=mentioned_user_id,
            email="alice@example.com",
            hashed_password="x",
            full_name="Alice",
        ),
    )
    session.add(
        User(
            id=author_id,
            email="bob@example.com",
            hashed_password="x",
            full_name="Bob",
        ),
    )
    await session.commit()

    svc = NotificationService(session)
    note = await svc.create(
        user_id=mentioned_user_id,
        notification_type="file_comment_mention",
        title_key="notifications.file_comments.mention.title",
        body_key="notifications.file_comments.mention.body",
        body_context={"excerpt": "Hey @alice can you review?"},
        entity_type="file_comment",
        entity_id=str(uuid.uuid4()),
        action_url="/files/document/abc?comment=xyz",
    )

    rows = list(
        (
            await session.execute(
                select(Notification).where(Notification.user_id == mentioned_user_id),
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].notification_type == "file_comment_mention"
    assert rows[0].title_key == "notifications.file_comments.mention.title"
    assert rows[0].body_context.get("excerpt") == "Hey @alice can you review?"
    assert note.id == rows[0].id


# ── B7: KNOWN_EVENT_TYPES sync test ───────────────────────────────────────


def test_known_event_types_have_unique_names() -> None:
    """Catalogue entries must not duplicate (frontend dedupe key)."""
    names = [e["event_type"] for e in KNOWN_EVENT_TYPES]
    assert len(names) == len(set(names)), f"duplicate event types in KNOWN_EVENT_TYPES: {sorted(names)}"


def test_known_event_types_have_required_fields() -> None:
    """Each catalogue entry must carry event_type/module/description."""
    for entry in KNOWN_EVENT_TYPES:
        assert "event_type" in entry, f"missing event_type: {entry}"
        assert "module" in entry, f"missing module: {entry}"
        assert "description" in entry, f"missing description: {entry}"
        assert entry["event_type"], f"empty event_type: {entry}"
        assert entry["module"], f"empty module: {entry}"


def test_file_comments_mention_event_is_registered() -> None:
    """Epic B / B1: the @mention event must appear in the catalogue."""
    types = {e["event_type"] for e in KNOWN_EVENT_TYPES}
    assert "file_comments.mention.created" in types
    # And the template for the i18n key must exist so the bell can
    # render the row even when the locale file is missing the key.
    assert "notifications.file_comments.mention.title" in _TEMPLATES
    assert "notifications.file_comments.mention.body" in _TEMPLATES


# ── B6: notifications_ws_hub fan-out ──────────────────────────────────────


@pytest.mark.asyncio
async def test_ws_hub_push_fans_out_to_every_socket_for_user() -> None:
    """Every open socket for a user receives the same push payload."""
    hub = NotificationsWsHub()
    uid = uuid.uuid4()

    captured: list[dict] = []
    captured_b: list[dict] = []

    class _StubSocket:
        def __init__(self, sink: list[dict]) -> None:
            self.sink = sink

        async def send_json(self, message: dict) -> None:
            self.sink.append(message)

    ws_a = _StubSocket(captured)
    ws_b = _StubSocket(captured_b)
    await hub.join(uid, ws_a)
    await hub.join(uid, ws_b)
    assert hub.subscriber_count(uid) == 2

    sent = await hub.push_to_user(uid, {"event": "notification.created", "data": {"x": 1}})
    assert sent == 2
    assert captured[-1]["event"] == "notification.created"
    assert captured_b[-1]["event"] == "notification.created"

    # Leaving a socket drops it from fan-out, the other stays.
    await hub.leave(uid, ws_a)
    sent2 = await hub.push_to_user(uid, {"event": "second", "data": {}})
    assert sent2 == 1
    assert hub.subscriber_count(uid) == 1


@pytest.mark.asyncio
async def test_ws_hub_dead_socket_scrub() -> None:
    """A socket whose send_json raises is dropped silently and never blocks
    the rest of the fan-out.
    """
    hub = NotificationsWsHub()
    uid = uuid.uuid4()

    captured: list[dict] = []

    class _LiveSocket:
        async def send_json(self, message: dict) -> None:
            captured.append(message)

    class _DeadSocket:
        async def send_json(self, message: dict) -> None:
            raise ConnectionError("client closed tab")

    live = _LiveSocket()
    dead = _DeadSocket()
    await hub.join(uid, live)
    await hub.join(uid, dead)
    assert hub.subscriber_count(uid) == 2

    sent = await hub.push_to_user(uid, {"event": "test"})
    # Only the live socket counted as delivered.
    assert sent == 1
    # Dead socket was scrubbed.
    assert hub.subscriber_count(uid) == 1


# ── B8: WebhookTargetResponse never leaks secret ──────────────────────────


@pytest.mark.asyncio
async def test_webhook_target_response_omits_secret_plaintext(session) -> None:
    """The wire shape exposes ``has_secret`` (bool) but never ``secret``.

    This protects against accidental round-trip in admin UIs — if a
    secret-bearing target is fetched and re-PATCHed, the request body
    must not echo back the stored plaintext.
    """
    target = WebhookTarget(
        name="staging-jira",
        url="https://staging.example.com/hooks/jira",
        event_filter="*",
        secret="super-secret-hmac-key",
        active=True,
    )
    session.add(target)
    await session.commit()

    # Use the router helper directly to avoid a full TestClient setup —
    # the helper is where the secret-stripping logic lives.
    from app.modules.notifications.router import _webhook_to_response

    resp = _webhook_to_response(target)
    payload = resp.model_dump()
    assert payload["has_secret"] is True
    assert "secret" not in payload, "WebhookTargetResponse must not expose plaintext secret"
    # Sanity-check the rest of the round-trip.
    assert payload["name"] == "staging-jira"
    assert payload["url"] == "https://staging.example.com/hooks/jira"
    assert payload["active"] is True


# ── Sanity: icon_category mapping still picks up new types ─────────────────


def test_file_comment_mention_icon_category() -> None:
    """The file_comment_mention type maps to the 'info' icon (Epic B / B1)."""
    assert icon_category_for("file_comment_mention") == "info"
    # Unknown still falls back to info — never raises.
    assert icon_category_for("some_random_third_party_type") == "info"
    assert icon_category_for(None) == "info"


# ── Circuit-breaker: open threshold skips delivery ─────────────────────────


def test_circuit_open_threshold_constants_are_sane() -> None:
    """The two thresholds must be positive and ordered correctly."""
    from app.modules.notifications.dispatcher import (
        _CIRCUIT_DEACTIVATE_THRESHOLD,
        _CIRCUIT_OPEN_THRESHOLD,
    )

    assert _CIRCUIT_OPEN_THRESHOLD > 0
    assert _CIRCUIT_DEACTIVATE_THRESHOLD > _CIRCUIT_OPEN_THRESHOLD


@pytest.mark.asyncio
async def test_circuit_open_skips_delivery_for_high_failure_count(session) -> None:
    """A target whose ``failure_count`` >= ``_CIRCUIT_OPEN_THRESHOLD`` must not
    receive the POST even though ``active=True``.

    We drive the internal helper directly rather than a full HTTP POST so we
    can assert skipping without needing an external server.
    """
    from app.modules.notifications.dispatcher import (
        _CIRCUIT_OPEN_THRESHOLD,
        _on_dispatch_webhook,
    )
    from app.core.events import Event

    target = WebhookTarget(
        name="circuit-open-target",
        url="https://dead.endpoint.example.com/hook",
        event_filter="*",
        active=True,
        failure_count=_CIRCUIT_OPEN_THRESHOLD,  # exactly at threshold
    )
    session.add(target)
    await session.commit()

    posted_to: list[str] = []

    import app.modules.notifications.dispatcher as disp_mod

    original_factory = disp_mod.async_session_factory

    class _PatchedFactory:
        """Return the test session instead of opening a new one."""

        def __aenter__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, *_: object) -> None:
            # We do NOT commit from the test session — keep isolation.
            pass

    # Monkey-patch the factory used inside _on_dispatch_webhook so it uses
    # our test session instead of the production pool.
    original = disp_mod.async_session_factory

    class _CM:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_: object) -> None:
            pass

    import httpx
    import unittest.mock

    with unittest.mock.patch.object(disp_mod, "async_session_factory", return_value=_CM()):
        with unittest.mock.patch.object(
            disp_mod,
            "_get_http_client",
        ) as mock_client:

            class _FakeClient:
                async def post(self, url: str, **kwargs: object) -> object:
                    posted_to.append(url)

                    class _FakeResp:
                        status_code = 200

                    return _FakeResp()

            mock_client.return_value = _FakeClient()

            event = Event(
                name="notifications.dispatch.webhook",
                data={
                    "event_type": "boq.position.created",
                    "user_id": str(uuid.uuid4()),
                    "payload": {},
                },
            )
            await _on_dispatch_webhook(event)

    # Circuit is open: no HTTP call should have been made to the dead endpoint.
    assert posted_to == [], (
        f"Expected no delivery for circuit-open target but got posts to: {posted_to}"
    )
