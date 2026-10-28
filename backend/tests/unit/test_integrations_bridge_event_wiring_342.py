"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Regression test for issue #342 - real notifications never reached Telegram.

Connecting Telegram succeeded and the "Test" button delivered a message, but
no real platform notification (task/RFI assignment, mention, status change, ...)
ever arrived. The Test button works because the router calls the telegram send
helper directly; the event-driven path is what was broken.

Root cause: BOTH the integrations connector bridge and the notifications
dispatcher subscribe a module-level function named ``_on_notification_created``
to the same ``notifications.notification.created`` event. Their idempotency
guards compared handlers by ``__qualname__`` - the identical bare string
``"_on_notification_created"`` for both functions - so whichever module loaded
second saw the other's handler and skipped its own subscription. The
notifications module loads first (it is pulled in early as a dependency), so the
integrations bridge was never wired and the connector stayed write-only.

This test wires BOTH registrars through the real event bus in the production
order (dispatcher first, bridge second), publishes a real event, and asserts
the Telegram send path fires. The HTTP send is mocked - no network, no DB.

Before the fix this test fails: the bridge is skipped, ``sends`` stays empty.
After the fix (identity-based idempotency guard) both same-named handlers
coexist and the event reaches Telegram.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

import app.modules.integrations.notification_bridge as bridge
import app.modules.notifications.dispatcher as dispatcher
from app.core.events import event_bus
from app.modules.integrations.notification_bridge import (
    register_integration_notification_bridge,
)
from app.modules.notifications.dispatcher import register_dispatchers

# ── In-memory fakes (DB-free) ──────────────────────────────────────────────


class _FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[object]:
        return list(self._rows)


class _FakeSession:
    """Async-session stub returning a fixed set of IntegrationConfig rows."""

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


@pytest.fixture
def clean_event_bus():
    """Snapshot, clear, and restore the global event bus around the test.

    The bus is a process-global singleton; this test wires handlers into it,
    so it must start from a pristine slate (to reproduce the exact production
    registration order) and leave the pre-test handlers untouched afterwards.
    """
    saved = {name: list(handlers) for name, handlers in event_bus._handlers.items()}
    saved_wild = list(event_bus._wildcard_handlers)
    event_bus._handlers.clear()
    event_bus._wildcard_handlers.clear()
    try:
        yield event_bus
    finally:
        event_bus._handlers.clear()
        for name, handlers in saved.items():
            event_bus._handlers[name] = handlers
        event_bus._wildcard_handlers[:] = saved_wild


@pytest.mark.asyncio
async def test_created_event_reaches_telegram_end_to_end(
    clean_event_bus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()

    # An ACTIVE telegram connector for this user, matching all events.
    cfg = SimpleNamespace(
        id=uuid.uuid4(),
        integration_type="telegram",
        config={"bot_token": "123:abc", "chat_id": "-100"},
        events=["*"],
        is_active=True,
        last_triggered_at=None,
    )
    monkeypatch.setattr(bridge, "async_session_factory", lambda: _FakeSession([cfg]))

    # Capture the telegram HTTP send (mock - no network).
    sends: list[dict] = []

    async def _fake_send(*, bot_token: str, chat_id: str, title: str, message: str, action_url=None) -> bool:
        sends.append({"bot_token": bot_token, "chat_id": chat_id, "title": title, "message": message})
        return True

    monkeypatch.setattr(
        "app.modules.integrations.telegram.send_telegram_notification",
        _fake_send,
    )

    # Silence the dispatcher's real WS-push sibling (the other, identically
    # named handler) so this test isolates the telegram path. The bus runs it
    # first (subscribed first), before the bridge.
    from app.modules.notifications.ws_hub import notifications_ws_hub

    async def _noop_push(*_a: object, **_k: object) -> int:
        return 0

    monkeypatch.setattr(notifications_ws_hub, "push_to_user", _noop_push)

    # Wire in PRODUCTION order: notifications dispatcher first (it loads first),
    # then the integrations bridge. This is the exact sequence that used to drop
    # the bridge subscription via the qualname-collision guard.
    register_dispatchers()
    register_integration_notification_bridge()

    # Both distinct same-named handlers must now coexist on the event - the
    # crux of the fix (identity check, not qualname string).
    subscribed = event_bus._handlers.get("notifications.notification.created", [])
    assert bridge._on_notification_created in subscribed
    assert dispatcher._on_notification_created in subscribed
    assert len(subscribed) == 2

    # Publish a REAL platform notification event for this user (the shape
    # NotificationService.create emits for an RFI assignment, mention, etc.).
    await event_bus.publish(
        "notifications.notification.created",
        {
            "notification_id": str(uuid.uuid4()),
            "user_id": str(user_id),
            "notification_type": "rfi.assigned",
            "title_key": "notifications.rfi.assigned.title",
        },
    )

    # The event reached Telegram through the event-driven path.
    assert len(sends) == 1
    assert sends[0]["bot_token"] == "123:abc"
    assert sends[0]["chat_id"] == "-100"
    assert sends[0]["title"]  # rendered, non-empty


@pytest.mark.asyncio
async def test_bridge_registration_not_shadowed_by_dispatcher(
    clean_event_bus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Focused wiring assertion: registering the dispatcher first must NOT stop
    the bridge from subscribing (the pre-#342 qualname guard did exactly that).
    """
    register_dispatchers()
    # Dispatcher's WS-push handler is now on the event; its bare __qualname__ is
    # the identical string to the bridge's handler.
    before = event_bus._handlers.get("notifications.notification.created", [])
    assert dispatcher._on_notification_created in before
    assert bridge._on_notification_created not in before

    register_integration_notification_bridge()

    after = event_bus._handlers.get("notifications.notification.created", [])
    assert bridge._on_notification_created in after  # would fail before the fix

    # Idempotent: a second call must not double-subscribe either handler.
    register_dispatchers()
    register_integration_notification_bridge()
    final = event_bus._handlers.get("notifications.notification.created", [])
    assert final.count(bridge._on_notification_created) == 1
    assert final.count(dispatcher._on_notification_created) == 1
