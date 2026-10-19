"""Scheduling an inspection or a meeting tells the people it was scheduled for.

``_notify_inspection_due`` and ``_notify_meeting_scheduled`` in
``app.core.event_handlers`` were subscribed to ``inspection.scheduled`` and
``meeting.scheduled`` from the start, while neither service published anything
when it scheduled. The inspector learned about an inspection, and an attendee
about a meeting, only by opening the register.

Each test drives the real service over stub repositories, captures what it
publishes, and replays that payload through a bus wired by the production
``register_event_handlers``. The assertion is the effect, a notification for
the right user, not that a handler fired.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

import app.core.event_handlers as core_handlers
from app.core.events import EventBus, event_bus
from app.modules.inspections.schemas import InspectionCreate, InspectionUpdate
from app.modules.inspections.service import InspectionService
from app.modules.meetings.schemas import AttendeeEntry, MeetingCreate, MeetingUpdate
from app.modules.meetings.service import MeetingService

PROJECT = uuid.uuid4()
SCHEDULER = str(uuid.uuid4())
INSPECTOR = str(uuid.uuid4())
OTHER_INSPECTOR = str(uuid.uuid4())
ATTENDEE = str(uuid.uuid4())


# ── Stubs ──────────────────────────────────────────────────────────────────


class _StubSession:
    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()

    async def flush(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        return None

    async def execute(self, stmt: Any) -> SimpleNamespace:
        return SimpleNamespace(rowcount=0, scalar_one_or_none=lambda: None)


class _StubRepo:
    def __init__(self, prefix: str) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._prefix = prefix
        self._counter = 0

    async def create(self, row: Any) -> Any:
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()
        row.created_at = row.updated_at = datetime.now(UTC)
        self._counter += 1
        if self._prefix == "INS":
            row.inspection_number = f"INS-{self._counter:03d}"
        self.rows[row.id] = row
        return row

    async def get_by_id(self, row_id: uuid.UUID) -> Any:
        return self.rows.get(row_id)

    async def next_meeting_number(self, project_id: uuid.UUID) -> str:
        return f"MTG-{self._counter + 1:03d}"

    async def update_fields(self, row_id: uuid.UUID, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self.rows[row_id], key, value)


def _inspections() -> InspectionService:
    service = InspectionService.__new__(InspectionService)
    service.session = _StubSession()
    service.repo = _StubRepo("INS")
    return service


def _meetings() -> MeetingService:
    service = MeetingService.__new__(MeetingService)
    service.session = _StubSession()
    service.repo = _StubRepo("MTG")
    return service


class _Notifications:
    """Stands in for ``NotificationService`` and records who was told."""

    sent: list[tuple[str, dict[str, Any]]] = []

    def __init__(self, session: Any) -> None:
        self.session = session

    async def create(self, *, user_id: str, **kwargs: Any) -> None:
        self.sent.append((str(user_id), kwargs))

    async def notify_users(self, user_ids: list[str], **kwargs: Any) -> None:
        for user_id in user_ids:
            self.sent.append((str(user_id), kwargs))


class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """What the services hand the bus, in order.

    A stub session has no transaction, so ``publish_after_commit`` publishes
    straight away through ``publish_detached``; both paths land here.
    """
    seen: list[tuple[str, dict[str, Any]]] = []

    def _capture(name: str, data: dict[str, Any] | None = None, source_module: str | None = None) -> None:
        seen.append((name, dict(data or {})))

    monkeypatch.setattr(event_bus, "publish_detached", _capture)
    return seen


@pytest.fixture
def production_bus(monkeypatch: pytest.MonkeyPatch) -> EventBus:
    """A fresh bus wired by the registrar the app runs at startup."""
    import app.database
    import app.modules.notifications.service as notification_service

    _Notifications.sent = []
    monkeypatch.setattr(notification_service, "NotificationService", _Notifications)
    monkeypatch.setattr(app.database, "async_session_factory", _Session)
    bus = EventBus()
    monkeypatch.setattr(core_handlers, "event_bus", bus)
    core_handlers.register_event_handlers()
    # The webhook forwarder hears every event and is not under test.
    bus.unsubscribe("*", core_handlers._dispatch_to_webhooks)
    return bus


async def _replay(bus: EventBus, published: list[tuple[str, dict[str, Any]]], name: str) -> list[str]:
    for event_name, data in published:
        if event_name == name:
            await bus.publish(event_name, data, source_module="test")
    return [user for user, _ in _Notifications.sent]


def _named(published: list[tuple[str, dict[str, Any]]], name: str) -> list[dict[str, Any]]:
    return [data for event_name, data in published if event_name == name]


# ── Inspections ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scheduling_an_inspection_notifies_the_inspector(published, production_bus) -> None:
    inspection = await _inspections().create_inspection(
        InspectionCreate(
            project_id=PROJECT,
            inspection_type="concrete_pour",
            title="Slab L3 pour",
            inspector_id=INSPECTOR,
            inspection_date="2026-11-02",
        ),
        user_id=SCHEDULER,
    )

    [payload] = _named(published, "inspection.scheduled")
    assert payload["inspection_id"] == str(inspection.id)
    assert payload["inspection_date"] == "2026-11-02"
    assert await _replay(production_bus, published, "inspection.scheduled") == [INSPECTOR]
    [(_, sent)] = _Notifications.sent
    assert sent["entity_id"] == str(inspection.id)
    assert sent["action_url"] == f"/projects/{PROJECT}/inspections"


@pytest.mark.asyncio
async def test_an_inspection_nobody_was_assigned_to_tells_nobody(published, production_bus) -> None:
    service = _inspections()
    await service.create_inspection(
        InspectionCreate(project_id=PROJECT, inspection_type="mep", title="Riser check"),
        user_id=SCHEDULER,
    )
    # Scheduling yourself is not news to you.
    await service.create_inspection(
        InspectionCreate(project_id=PROJECT, inspection_type="mep", title="Own check", inspector_id=SCHEDULER),
        user_id=SCHEDULER,
    )

    assert await _replay(production_bus, published, "inspection.scheduled") == []


@pytest.mark.asyncio
async def test_a_rescheduled_or_reassigned_inspection_notifies_again(published, production_bus) -> None:
    service = _inspections()
    inspection = await service.create_inspection(
        InspectionCreate(project_id=PROJECT, inspection_type="general", title="Handover walk", inspector_id=INSPECTOR),
        user_id=SCHEDULER,
    )
    published.clear()

    # An edit that does not move the inspection or change who does it is quiet.
    await service.update_inspection(inspection.id, InspectionUpdate(title="Handover walk, block B"))
    assert _named(published, "inspection.scheduled") == []

    await service.update_inspection(inspection.id, InspectionUpdate(inspector_id=OTHER_INSPECTOR))
    await service.update_inspection(inspection.id, InspectionUpdate(inspection_date="2026-11-09"))
    # A failed inspection scheduled again for re-inspection.
    service.repo.rows[inspection.id].status = "failed"
    await service.update_inspection(inspection.id, InspectionUpdate(status="scheduled"))

    assert await _replay(production_bus, published, "inspection.scheduled") == [OTHER_INSPECTOR] * 3


# ── Meetings ───────────────────────────────────────────────────────────────


def _attendees() -> list[AttendeeEntry]:
    return [
        AttendeeEntry(user_id=ATTENDEE, name="Site engineer"),
        AttendeeEntry(name="Walk-in guest"),
        AttendeeEntry(user_id=SCHEDULER, name="Chair"),
        AttendeeEntry(user_id="not-a-uuid", name="Typo"),
    ]


@pytest.mark.asyncio
async def test_scheduling_a_meeting_notifies_its_attendees(published, production_bus) -> None:
    meeting = await _meetings().create_meeting(
        MeetingCreate(
            project_id=PROJECT,
            meeting_type="progress",
            title="Weekly progress",
            meeting_date="2026-11-03",
            attendees=_attendees(),
            status="scheduled",
        ),
        user_id=SCHEDULER,
    )

    [payload] = _named(published, "meeting.scheduled")
    assert payload["meeting_id"] == str(meeting.id)
    # Only attendees with a user account can be told, and not the organiser.
    assert await _replay(production_bus, published, "meeting.scheduled") == [ATTENDEE]
    [(_, sent)] = _Notifications.sent
    assert sent["action_url"] == f"/projects/{PROJECT}/meetings"


@pytest.mark.asyncio
async def test_a_draft_meeting_is_announced_when_scheduled_or_moved(published, production_bus) -> None:
    service = _meetings()
    meeting = await service.create_meeting(
        MeetingCreate(
            project_id=PROJECT,
            meeting_type="progress",
            title="Design review",
            meeting_date="2026-11-04",
            attendees=_attendees(),
        ),
        user_id=SCHEDULER,
    )
    assert _named(published, "meeting.scheduled") == []

    await service.update_meeting(meeting.id, MeetingUpdate(status="scheduled"), user_id=SCHEDULER)
    await service.update_meeting(meeting.id, MeetingUpdate(location="Site cabin 2"), user_id=SCHEDULER)
    await service.update_meeting(meeting.id, MeetingUpdate(meeting_date="2026-11-05"), user_id=SCHEDULER)

    assert [p["meeting_date"] for p in _named(published, "meeting.scheduled")] == ["2026-11-04", "2026-11-05"]
    assert await _replay(production_bus, published, "meeting.scheduled") == [ATTENDEE, ATTENDEE]
