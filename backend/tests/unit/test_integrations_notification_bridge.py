"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the integrations chat-connector notification bridge (#279).

These exercise the bridge that forwards ``notifications.notification.created``
events to a user's connected chat connectors (Telegram / Slack / Teams /
Discord / WhatsApp).

The actual network send helpers are patched - NO real HTTP is made. The
event subscriber's DB access is stubbed with an in-memory fake session, so
these tests do not touch a real database and run on the local py3.11
interpreter.

Coverage:
    1. a connector receives a send call when a matching notification fires;
    2. a non-matching ``events`` filter is skipped;
    3. an inactive / disabled connector is skipped;
    4. one connector's send raising does not stop the others;
    5. ``last_triggered_at`` is stamped on a successful send;
    6. the events-filter-to-pattern helper handles list / str / None / empty.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

import app.modules.integrations.notification_bridge as bridge
from app.core.events import Event

# ── In-memory fakes ────────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[object]:
        return list(self._rows)


class _FakeSession:
    """Minimal async-session stub returning a fixed set of IntegrationConfig rows."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows
        self.committed = False

    async def execute(self, _stmt: object) -> _FakeResult:
        return _FakeResult(self._rows)

    async def commit(self) -> None:
        self.committed = True

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


def _make_config(
    *,
    integration_type: str,
    config: dict | None = None,
    events: object = None,
    is_active: bool = True,
) -> SimpleNamespace:
    """Build an IntegrationConfig-like row (only the fields the bridge reads)."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        integration_type=integration_type,
        config=config if config is not None else {},
        events=events if events is not None else ["*"],
        is_active=is_active,
        last_triggered_at=None,
    )


def _patch_session(monkeypatch: pytest.MonkeyPatch, rows: list[object]) -> _FakeSession:
    """Patch the bridge's ``async_session_factory`` to yield a fake session."""
    fake = _FakeSession(rows)

    def _factory() -> _FakeSession:
        return fake

    monkeypatch.setattr(bridge, "async_session_factory", _factory)
    return fake


def _event(user_id: uuid.UUID | str, notification_type: str = "comment_added") -> Event:
    return Event(
        name="notifications.notification.created",
        data={
            "notification_id": str(uuid.uuid4()),
            "user_id": str(user_id),
            "notification_type": notification_type,
            "title_key": f"notifications.{notification_type}.title",
        },
    )


# ── events filter helper ───────────────────────────────────────────────────


def test_events_filter_to_pattern_variants() -> None:
    assert bridge._events_filter_to_pattern(["*"]) == "*"
    assert bridge._events_filter_to_pattern(["boq.*", "rfi.assigned"]) == "boq.*,rfi.assigned"
    assert bridge._events_filter_to_pattern(None) == "*"
    assert bridge._events_filter_to_pattern([]) == "*"
    assert bridge._events_filter_to_pattern("boq.*") == "boq.*"
    # Whitespace-only entries are dropped; an all-empty list falls back to "*".
    assert bridge._events_filter_to_pattern(["  ", ""]) == "*"


# ── 1. matching connector receives the send ────────────────────────────────


@pytest.mark.asyncio
async def test_matching_connector_receives_send(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = uuid.uuid4()
    cfg = _make_config(
        integration_type="telegram",
        config={"bot_token": "123:abc", "chat_id": "-100"},
        events=["*"],
    )
    fake = _patch_session(monkeypatch, [cfg])

    calls: list[dict] = []

    async def _fake_send(*, bot_token: str, chat_id: str, title: str, message: str, action_url=None) -> bool:
        calls.append({"bot_token": bot_token, "chat_id": chat_id, "title": title, "message": message})
        return True

    monkeypatch.setattr(
        "app.modules.integrations.telegram.send_telegram_notification",
        _fake_send,
    )

    await bridge._on_notification_created(_event(user_id))

    assert len(calls) == 1
    assert calls[0]["bot_token"] == "123:abc"
    assert calls[0]["chat_id"] == "-100"
    assert calls[0]["title"]  # rendered, non-empty
    # last_triggered_at stamped + committed on success.
    assert cfg.last_triggered_at is not None
    assert fake.committed is True


# ── 2. non-matching events filter is skipped ───────────────────────────────


@pytest.mark.asyncio
async def test_non_matching_filter_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = uuid.uuid4()
    cfg = _make_config(
        integration_type="telegram",
        config={"bot_token": "t", "chat_id": "c"},
        events=["boq.*"],  # does not match "comment_added"
    )
    fake = _patch_session(monkeypatch, [cfg])

    calls: list[int] = []

    async def _fake_send(**_: object) -> bool:
        calls.append(1)
        return True

    monkeypatch.setattr(
        "app.modules.integrations.telegram.send_telegram_notification",
        _fake_send,
    )

    await bridge._on_notification_created(_event(user_id, notification_type="comment_added"))

    assert calls == []
    assert cfg.last_triggered_at is None
    assert fake.committed is False


# ── 3. inactive connector is skipped (filtered in the query) ───────────────


@pytest.mark.asyncio
async def test_inactive_connector_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """The query filters on ``is_active``; mirror that by not returning the row.

    The bridge relies on the WHERE clause, so an inactive connector simply
    never comes back from the session. We assert the bridge issues no send and
    does not commit when the (already-filtered) result set is empty.
    """
    user_id = uuid.uuid4()
    fake = _patch_session(monkeypatch, [])  # disabled row excluded by the query

    calls: list[int] = []

    async def _fake_send(**_: object) -> bool:
        calls.append(1)
        return True

    monkeypatch.setattr(
        "app.modules.integrations.telegram.send_telegram_notification",
        _fake_send,
    )

    await bridge._on_notification_created(_event(user_id))

    assert calls == []
    assert fake.committed is False


@pytest.mark.asyncio
async def test_send_to_connector_inactive_flag_not_consulted_but_helper_safe() -> None:
    """``_send_to_connector`` on a connector with missing creds returns False."""
    cfg = _make_config(integration_type="telegram", config={})  # no bot_token/chat_id
    ok = await bridge._send_to_connector(cfg, "Title", "Body", None)
    assert ok is False


# ── 4. one connector raising does not stop the others ──────────────────────


@pytest.mark.asyncio
async def test_one_connector_failure_does_not_block_others(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = uuid.uuid4()
    tele = _make_config(
        integration_type="telegram",
        config={"bot_token": "t", "chat_id": "c"},
        events=["*"],
    )
    disc = _make_config(
        integration_type="discord",
        config={"webhook_url": "https://discord.com/api/webhooks/x/y"},
        events=["*"],
    )
    fake = _patch_session(monkeypatch, [tele, disc])

    discord_calls: list[int] = []

    async def _telegram_boom(**_: object) -> bool:
        raise RuntimeError("telegram exploded")

    async def _discord_ok(*, webhook_url: str, title: str, message: str, action_url=None) -> bool:
        discord_calls.append(1)
        return True

    # Discord posts to a URL, so the bridge re-validates it; stub the SSRF check
    # to a no-op so we exercise the send path without network/DNS.
    async def _allow_url(_url: str) -> None:
        return None

    monkeypatch.setattr(
        "app.modules.integrations.telegram.send_telegram_notification",
        _telegram_boom,
    )
    monkeypatch.setattr(
        "app.modules.integrations.discord.send_discord_notification",
        _discord_ok,
    )
    monkeypatch.setattr(bridge, "resolve_and_validate_external_url", _allow_url)

    # Must not raise even though the telegram connector blows up.
    await bridge._on_notification_created(_event(user_id))

    # The second connector still received its send.
    assert discord_calls == [1]
    # The failing connector did NOT get stamped; the succeeding one did.
    assert tele.last_triggered_at is None
    assert disc.last_triggered_at is not None
    # At least one delivery succeeded, so the session committed.
    assert fake.committed is True


# ── 5. unknown / helper-less channel is skipped gracefully ─────────────────


@pytest.mark.asyncio
async def test_unknown_channel_skipped_gracefully() -> None:
    cfg = _make_config(integration_type="carrier-pigeon", config={"foo": "bar"})
    ok = await bridge._send_to_connector(cfg, "Title", "Body", None)
    assert ok is False


# ── 6. body_context interpolates BOTH title and body (#284 follow-up) ──────


@pytest.mark.asyncio
async def test_body_context_interpolated_into_title_and_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """The created event now carries body_key + body_context + action_url, so
    the connector message must match the in-app notification: placeholders in
    both the title and body templates are filled, and the body is forwarded
    (not dropped to the title).
    """
    user_id = uuid.uuid4()
    cfg = _make_config(
        integration_type="telegram",
        config={"bot_token": "t", "chat_id": "c"},
        events=["*"],
    )
    _patch_session(monkeypatch, [cfg])

    calls: list[dict] = []

    async def _fake_send(*, bot_token: str, chat_id: str, title: str, message: str, action_url=None) -> bool:
        calls.append({"title": title, "message": message, "action_url": action_url})
        return True

    monkeypatch.setattr(
        "app.modules.integrations.telegram.send_telegram_notification",
        _fake_send,
    )

    # Use the cost-overrun template: its body has {actual}/{currency}/{...}
    # placeholders, the exact case the in-app bell renders but the bridge
    # used to leave raw.
    ev = Event(
        name="notifications.notification.created",
        data={
            "notification_id": str(uuid.uuid4()),
            "user_id": str(user_id),
            "notification_type": "costmodel.overrun_alert",
            "title_key": "notifications.costmodel.overrun_alert.title",
            "body_key": "notifications.costmodel.overrun_alert.body",
            "body_context": {
                "category": "Concrete",
                "actual": "120000",
                "currency": "EUR",
                "threshold_pct": "10",
                "planned": "100000",
            },
            "action_url": "https://erp.example.com/projects/1/cost",
        },
    )

    await bridge._on_notification_created(ev)

    assert len(calls) == 1
    sent = calls[0]
    # Title renders (it has no placeholders) and the body is the distinct,
    # fully-interpolated message - NOT a copy of the title and NOT raw braces.
    assert sent["title"] == "Cost Overrun Alert"
    assert sent["message"] != sent["title"]
    assert "120000" in sent["message"]
    assert "EUR" in sent["message"]
    assert "{actual}" not in sent["message"]
    assert "{currency}" not in sent["message"]
    # The action URL rides along to the connector.
    assert sent["action_url"] == "https://erp.example.com/projects/1/cost"


@pytest.mark.asyncio
async def test_missing_user_id_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """An event with no user_id must short-circuit before opening a session."""
    opened: list[int] = []

    def _factory() -> object:
        opened.append(1)
        raise AssertionError("session must not be opened when user_id is missing")

    monkeypatch.setattr(bridge, "async_session_factory", _factory)

    ev = Event(name="notifications.notification.created", data={"notification_type": "x"})
    await bridge._on_notification_created(ev)
    assert opened == []
