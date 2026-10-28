"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Event-emission tests for the Notifications service (slice E)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.events import Event, event_bus
from app.modules.notifications.service import NotificationService

USER_ID = uuid.uuid4()


# ── Stub repository ───────────────────────────────────────────────────────


class _StubRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self.read_set: set[uuid.UUID] = set()

    async def create(self, notification: Any) -> Any:
        if getattr(notification, "id", None) is None:
            notification.id = uuid.uuid4()
        now = datetime.now(UTC)
        notification.created_at = now
        notification.updated_at = now
        self.rows[notification.id] = notification
        return notification

    async def mark_read(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        n = self.rows.get(notification_id)
        if n and getattr(n, "user_id", None) == user_id:
            self.read_set.add(notification_id)
            return True
        return False

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        count = 0
        for nid, n in self.rows.items():
            if n.user_id == user_id and nid not in self.read_set:
                self.read_set.add(nid)
                count += 1
        return count

    async def delete_by_id(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        n = self.rows.get(notification_id)
        if n and getattr(n, "user_id", None) == user_id:
            del self.rows[notification_id]
            return True
        return False


def _make_service() -> NotificationService:
    svc = NotificationService.__new__(NotificationService)
    svc.session = SimpleNamespace()
    svc.repo = _StubRepo()
    return svc


@pytest.fixture
def captured_events(monkeypatch: pytest.MonkeyPatch):
    """Capture every event the service publishes, deterministically.

    The service normally publishes via ``event_bus.publish_detached`` (a
    fire-and-forget ``asyncio.create_task``) so a request never blocks on a
    subscriber while it holds a database connection. That makes the
    *timing* of delivery non-deterministic in a test: the event lands on a
    later loop turn, and pumping the loop to wait for it also drags in
    fire-and-forget tasks leaked by earlier tests (which can raise cross-loop
    errors). So for these unit tests we patch the service's ``_safe_publish``
    to await ``event_bus.publish`` inline on the current loop — the event is
    delivered to our capture before ``await svc.create(...)`` returns, with no
    loop pumping and no dependence on test ordering.
    """
    captured: list[Event] = []

    async def _capture(event: Event) -> None:
        captured.append(event)

    async def _sync_publish(
        name: str,
        data: dict[str, Any],
        source_module: str = "oe_notifications",
    ) -> None:
        await event_bus.publish(name, data, source_module=source_module)

    from app.modules.notifications import service as _notif_service

    monkeypatch.setattr(_notif_service, "_safe_publish", _sync_publish)

    event_bus.subscribe("*", _capture)
    try:
        yield captured
    finally:
        event_bus.unsubscribe("*", _capture)


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_emits_notification_created(captured_events: list[Event]) -> None:
    svc = _make_service()

    n = await svc.create(
        user_id=USER_ID,
        notification_type="punchlist_assigned",
        title_key="notifications.punchlist.assigned",
        entity_type="punch_item",
        entity_id="abc-123",
    )

    matches = [e for e in captured_events if e.name == "notifications.notification.created"]
    assert len(matches) == 1
    payload = matches[0].data
    assert payload["notification_id"] == str(n.id)
    assert payload["user_id"] == str(USER_ID)
    assert payload["notification_type"] == "punchlist_assigned"
    assert payload["entity_type"] == "punch_item"
    assert payload["entity_id"] == "abc-123"
    assert matches[0].source_module == "oe_notifications"


@pytest.mark.asyncio
async def test_mark_read_emits_event(captured_events: list[Event]) -> None:
    svc = _make_service()
    n = await svc.create(user_id=USER_ID, notification_type="x", title_key="x")
    captured_events.clear()

    ok = await svc.mark_read(n.id, USER_ID)
    assert ok is True

    matches = [e for e in captured_events if e.name == "notifications.notification.read"]
    assert len(matches) == 1
    assert matches[0].data["notification_id"] == str(n.id)
    assert matches[0].data["user_id"] == str(USER_ID)


@pytest.mark.asyncio
async def test_mark_all_read_emits_bulk_read_event(captured_events: list[Event]) -> None:
    svc = _make_service()
    await svc.create(user_id=USER_ID, notification_type="x", title_key="x")
    await svc.create(user_id=USER_ID, notification_type="y", title_key="y")
    captured_events.clear()

    count = await svc.mark_all_read(USER_ID)
    assert count == 2

    matches = [e for e in captured_events if e.name == "notifications.notification.bulk_read"]
    assert len(matches) == 1
    assert matches[0].data["user_id"] == str(USER_ID)
    assert matches[0].data["count"] == 2


@pytest.mark.asyncio
async def test_delete_emits_deleted_event(captured_events: list[Event]) -> None:
    svc = _make_service()
    n = await svc.create(user_id=USER_ID, notification_type="x", title_key="x")
    captured_events.clear()

    ok = await svc.delete(n.id, USER_ID)
    assert ok is True

    matches = [e for e in captured_events if e.name == "notifications.notification.deleted"]
    assert len(matches) == 1
    assert matches[0].data["notification_id"] == str(n.id)


@pytest.mark.asyncio
async def test_mark_read_no_match_does_not_emit(captured_events: list[Event]) -> None:
    """If the row isn't owned by this user (mark_read returns False), no event."""
    svc = _make_service()
    other_user = uuid.uuid4()
    n = await svc.create(user_id=USER_ID, notification_type="x", title_key="x")
    captured_events.clear()

    ok = await svc.mark_read(n.id, other_user)
    assert ok is False

    matches = [e for e in captured_events if e.name == "notifications.notification.read"]
    assert matches == []
