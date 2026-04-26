"""Event-emission tests for the Punch List service (slice E).

Verifies that ``PunchListService`` publishes the right events on its
state-mutating paths.  Mirrors the stub-based pattern in
``test_procurement.py`` so we don't need a database — the repository
is faked and we subscribe to the global ``event_bus`` to capture
emissions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.events import Event, event_bus
from app.modules.punchlist.schemas import (
    PunchItemCreate,
    PunchItemUpdate,
    PunchStatusTransition,
)
from app.modules.punchlist.service import PunchListService

PROJECT_ID = uuid.uuid4()


# ── Stub repository ───────────────────────────────────────────────────────


class _StubRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, item: Any) -> Any:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        now = datetime.now(UTC)
        item.created_at = now
        item.updated_at = now
        if not hasattr(item, "photos"):
            item.photos = []
        self.rows[item.id] = item
        return item

    async def get_by_id(self, item_id: uuid.UUID) -> Any:
        return self.rows.get(item_id)

    async def update_fields(self, item_id: uuid.UUID, **fields: Any) -> None:
        item = self.rows.get(item_id)
        if item:
            for k, v in fields.items():
                setattr(item, k, v)
            item.updated_at = datetime.now(UTC)

    async def delete(self, item_id: uuid.UUID) -> None:
        self.rows.pop(item_id, None)

    async def count_open_critical(self, project_id: uuid.UUID, *, exclude_id=None) -> int:
        return 0


def _make_service() -> PunchListService:
    svc = PunchListService.__new__(PunchListService)
    fake_session = SimpleNamespace()
    # ``service.session.refresh`` is awaited — provide an async no-op
    async def _refresh(_obj: Any) -> None:
        return None

    fake_session.refresh = _refresh  # type: ignore[attr-defined]
    svc.session = fake_session
    svc.repo = _StubRepo()
    return svc


# ── Event capture fixture ────────────────────────────────────────────────


@pytest.fixture
def captured_events():
    """Subscribe a recorder to the global event bus for the test duration."""
    captured: list[Event] = []

    async def _capture(event: Event) -> None:
        captured.append(event)

    event_bus.subscribe("*", _capture)
    try:
        yield captured
    finally:
        event_bus.unsubscribe("*", _capture)


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_emits_item_created(captured_events: list[Event]) -> None:
    svc = _make_service()
    data = PunchItemCreate(project_id=PROJECT_ID, title="Door alignment", priority="high")
    item = await svc.create_item(data, user_id="user-1")

    matches = [e for e in captured_events if e.name == "punchlist.item.created"]
    assert len(matches) == 1
    payload = matches[0].data
    assert payload["item_id"] == str(item.id)
    assert payload["project_id"] == str(PROJECT_ID)
    assert payload["priority"] == "high"
    assert payload["status"] == "open"
    assert payload["created_by"] == "user-1"
    assert matches[0].source_module == "oe_punchlist"


@pytest.mark.asyncio
async def test_update_emits_item_updated(captured_events: list[Event]) -> None:
    svc = _make_service()
    item = await svc.create_item(
        PunchItemCreate(project_id=PROJECT_ID, title="x"), user_id="u"
    )
    captured_events.clear()

    await svc.update_item(item.id, PunchItemUpdate(priority="critical"))

    matches = [e for e in captured_events if e.name == "punchlist.item.updated"]
    assert len(matches) == 1
    payload = matches[0].data
    assert payload["item_id"] == str(item.id)
    assert payload["project_id"] == str(PROJECT_ID)
    assert "priority" in payload["updated_fields"]


@pytest.mark.asyncio
async def test_delete_emits_item_deleted(captured_events: list[Event]) -> None:
    svc = _make_service()
    item = await svc.create_item(
        PunchItemCreate(project_id=PROJECT_ID, title="x"), user_id="u"
    )
    captured_events.clear()

    await svc.delete_item(item.id)

    matches = [e for e in captured_events if e.name == "punchlist.item.deleted"]
    assert len(matches) == 1
    assert matches[0].data["item_id"] == str(item.id)
    assert matches[0].data["project_id"] == str(PROJECT_ID)


@pytest.mark.asyncio
async def test_status_transition_emits_status_changed(captured_events: list[Event]) -> None:
    svc = _make_service()
    item = await svc.create_item(
        PunchItemCreate(project_id=PROJECT_ID, title="x"), user_id="u"
    )
    captured_events.clear()

    await svc.transition_status(
        item.id,
        PunchStatusTransition(new_status="in_progress"),
        user_id="user-2",
    )

    matches = [e for e in captured_events if e.name == "punchlist.item.status_changed"]
    assert len(matches) == 1
    payload = matches[0].data
    assert payload["item_id"] == str(item.id)
    assert payload["from_status"] == "open"
    assert payload["to_status"] == "in_progress"
    assert payload["user_id"] == "user-2"
