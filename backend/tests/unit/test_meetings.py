"""Unit tests for :class:`MeetingService`.

Scope:
    CRUD, status transitions, attendee/agenda/action-item management,
    complete_meeting workflow, and open action item scanning.
    Repositories are stubbed so the suite doesn't need a live database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.meetings.schemas import (
    ActionItemEntry,
    AgendaItemEntry,
    AttendeeEntry,
    MeetingCreate,
    MeetingUpdate,
)
from app.modules.meetings.service import MeetingService

# ── Helpers / stubs ───────────────────────────────────────────────────────


def _make_service() -> MeetingService:
    service = MeetingService.__new__(MeetingService)
    service.session = _StubSession()
    service.repo = _StubMeetingRepo()
    return service


class _StubSession:
    """Minimal session stub with add/flush/refresh."""

    def __init__(self) -> None:
        self._added: list[Any] = []

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self._added.append(obj)

    async def flush(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:
        pass

    async def execute(self, stmt: Any) -> SimpleNamespace:
        return SimpleNamespace(rowcount=0)


class _StubMeetingRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def create(self, meeting: Any) -> Any:
        if getattr(meeting, "id", None) is None:
            meeting.id = uuid.uuid4()
        now = datetime.now(UTC)
        meeting.created_at = now
        meeting.updated_at = now
        self.rows[meeting.id] = meeting
        return meeting

    async def get_by_id(self, meeting_id: uuid.UUID) -> Any:
        return self.rows.get(meeting_id)

    async def next_meeting_number(self, project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"MTG-{self._counter:03d}"

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        meeting_type: str | None = None,
        status: str | None = None,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str = "desc",
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        if meeting_type is not None:
            rows = [r for r in rows if r.meeting_type == meeting_type]
        if status is not None:
            rows = [r for r in rows if r.status == status]
        return rows[offset : offset + limit], len(rows)

    async def update_fields(self, meeting_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(meeting_id)
        if obj is not None:
            for k, v in fields.items():
                setattr(obj, k, v)

    async def delete(self, meeting_id: uuid.UUID) -> None:
        self.rows.pop(meeting_id, None)

    async def all_for_project(self, project_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.project_id == project_id]

    async def stats_for_project(self, project_id: uuid.UUID) -> dict[str, Any]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        by_status: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for r in rows:
            by_status[r.status] = by_status.get(r.status, 0) + 1
            by_type[r.meeting_type] = by_type.get(r.meeting_type, 0) + 1
        return {
            "total": len(rows),
            "by_status": by_status,
            "by_type": by_type,
            "next_meeting_date": None,
        }


# ── Create ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_meeting_assigns_number_and_stores_attendees() -> None:
    service = _make_service()
    pid = uuid.uuid4()
    data = MeetingCreate(
        project_id=pid,
        meeting_type="progress",
        title="Weekly Progress Meeting",
        meeting_date="2026-04-15",
        attendees=[
            AttendeeEntry(name="Alice", company="ACME", status="present"),
            AttendeeEntry(name="Bob", company="ACME", status="absent"),
        ],
    )
    meeting = await service.create_meeting(data, user_id="user-1")

    assert meeting.id is not None
    assert meeting.meeting_number == "MTG-001"
    assert meeting.meeting_type == "progress"
    assert len(meeting.attendees) == 2
    assert meeting.attendees[0]["name"] == "Alice"


@pytest.mark.asyncio
async def test_create_meeting_with_agenda_and_action_items() -> None:
    service = _make_service()
    data = MeetingCreate(
        project_id=uuid.uuid4(),
        meeting_type="design",
        title="Design Review",
        meeting_date="2026-04-16",
        agenda_items=[
            AgendaItemEntry(topic="Foundation design review", number="1"),
        ],
        action_items=[
            ActionItemEntry(description="Update drawings", owner_id="eng-1", due_date="2026-04-20"),
        ],
    )
    meeting = await service.create_meeting(data)
    assert len(meeting.agenda_items) == 1
    assert len(meeting.action_items) == 1
    assert meeting.action_items[0]["description"] == "Update drawings"


# ── List ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_meetings_returns_project_scoped_results() -> None:
    service = _make_service()
    pid = uuid.uuid4()
    await service.create_meeting(
        MeetingCreate(project_id=pid, meeting_type="safety", title="Safety", meeting_date="2026-04-15")
    )
    await service.create_meeting(
        MeetingCreate(project_id=uuid.uuid4(), meeting_type="safety", title="Other", meeting_date="2026-04-15")
    )

    rows, total = await service.list_meetings(pid)
    assert total == 1


# ── Update ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_meeting_title() -> None:
    service = _make_service()
    meeting = await service.create_meeting(
        MeetingCreate(
            project_id=uuid.uuid4(),
            meeting_type="kickoff",
            title="Kickoff",
            meeting_date="2026-04-15",
        )
    )
    updated = await service.update_meeting(
        meeting.id, MeetingUpdate(title="Revised Kickoff")
    )
    assert updated.title == "Revised Kickoff"


@pytest.mark.asyncio
async def test_update_completed_meeting_raises_400() -> None:
    from fastapi import HTTPException

    service = _make_service()
    meeting = await service.create_meeting(
        MeetingCreate(
            project_id=uuid.uuid4(),
            meeting_type="progress",
            title="Done",
            meeting_date="2026-04-15",
        )
    )
    meeting.status = "completed"

    with pytest.raises(HTTPException) as exc_info:
        await service.update_meeting(meeting.id, MeetingUpdate(title="Change"))
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_update_invalid_status_transition_raises_400() -> None:
    from fastapi import HTTPException

    service = _make_service()
    meeting = await service.create_meeting(
        MeetingCreate(
            project_id=uuid.uuid4(),
            meeting_type="progress",
            title="Draft",
            meeting_date="2026-04-15",
        )
    )
    # draft -> completed is NOT allowed (must go through scheduled first)
    with pytest.raises(HTTPException) as exc_info:
        await service.update_meeting(meeting.id, MeetingUpdate(status="completed"))
    assert exc_info.value.status_code == 400


# ── Complete ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_scheduled_meeting_succeeds() -> None:
    service = _make_service()
    meeting = await service.create_meeting(
        MeetingCreate(
            project_id=uuid.uuid4(),
            meeting_type="progress",
            title="Scheduled Meeting",
            meeting_date="2026-04-15",
        )
    )
    meeting.status = "scheduled"
    meeting.action_items = []

    result = await service.complete_meeting(meeting.id)
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_complete_draft_meeting_raises_400() -> None:
    """Draft meetings must be scheduled first."""
    from fastapi import HTTPException

    service = _make_service()
    meeting = await service.create_meeting(
        MeetingCreate(
            project_id=uuid.uuid4(),
            meeting_type="progress",
            title="Draft",
            meeting_date="2026-04-15",
        )
    )
    # default status is draft
    with pytest.raises(HTTPException) as exc_info:
        await service.complete_meeting(meeting.id)
    assert exc_info.value.status_code == 400
    assert "draft" in exc_info.value.detail.lower()


# ── Delete ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_meeting_removes_from_repo() -> None:
    from fastapi import HTTPException

    service = _make_service()
    meeting = await service.create_meeting(
        MeetingCreate(
            project_id=uuid.uuid4(),
            meeting_type="closeout",
            title="Closeout",
            meeting_date="2026-04-15",
        )
    )
    await service.delete_meeting(meeting.id)

    with pytest.raises(HTTPException) as exc_info:
        await service.get_meeting(meeting.id)
    assert exc_info.value.status_code == 404
