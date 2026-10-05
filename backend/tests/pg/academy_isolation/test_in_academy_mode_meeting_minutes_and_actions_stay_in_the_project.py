# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode meeting minutes and action items stay in the project.

A meeting's attendees and its action-item owners are user ids taken from the
request body. Distributing the minutes sends every attendee an in-app "Minutes
issued" with the meeting's number and title, and completing the meeting turns
each open action item into a task assigned to its owner, written directly
(around the task gate) and announced by a "task assigned" notification. On an
academy box one learner could therefore push minutes, tasks and notifications
at another. In academy mode the minutes go only to attendees in the project,
an action item whose owner is outside the project becomes an unassigned task,
and both notifications carry the project so the backstop drops a stray one.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.events import Event
from app.modules.meetings.models import Meeting, MeetingMinutes
from app.modules.meetings.service import MeetingService
from app.modules.notifications import events as notification_events
from app.modules.notifications.models import Notification
from app.modules.tasks.models import Task
from tests.pg.academy_isolation.rows import add_member, make_project, make_user
from tests.pg.tender_award_fixtures import _NonCommittingSession

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

ACTIONS = "meeting.action_items_created"


async def _setup(session):
    alice = await make_user(session, name="Alice")
    bob = await make_user(session, name="Bob")
    carol = await make_user(session, name="Carol")
    project = await make_project(session, alice)
    await add_member(session, project, carol)
    meeting = Meeting(
        project_id=project.id,
        meeting_number=f"MTG-{uuid.uuid4().hex[:4]}",
        meeting_type="progress",
        title="Weekly site progress",
        meeting_date="2026-10-05",
        status="scheduled",
        attendees=[
            {"user_id": str(carol.id), "name": "Carol", "status": "present"},
            {"user_id": str(bob.id), "name": "Bob", "status": "present"},
            {"name": "Walk-in guest", "status": "present"},
        ],
        action_items=[
            {"description": "Order rebar", "owner_id": str(carol.id), "status": "open"},
            {"description": "Fix crane", "owner_id": str(bob.id), "status": "open"},
        ],
    )
    session.add(meeting)
    await session.flush()
    minutes = MeetingMinutes(project_id=project.id, meeting_id=meeting.id, status="issued", content={})
    session.add(minutes)
    await session.flush()
    return project, alice, bob, carol, meeting, minutes


async def _notified(session, user, kind: str) -> int:
    rows = await session.execute(
        select(Notification.id).where(Notification.user_id == user.id, Notification.notification_type == kind)
    )
    return len(rows.scalars().all())


async def _task_owners(session, meeting) -> dict[str, str | None]:
    rows = (await session.execute(select(Task).where(Task.meeting_id == str(meeting.id)))).scalars().all()
    return {t.title: (str(t.responsible_id) if t.responsible_id else None) for t in rows}


def _announced_owners(events) -> list[str | None]:
    return [item.get("owner_id") for name, data in events if name == ACTIONS for item in data["action_items"]]


async def test_academy_on_minutes_reach_only_project_attendees(pg_session, academy, events) -> None:
    academy(True)
    _project, alice, bob, carol, meeting, minutes = await _setup(pg_session)

    _row, notified = await MeetingService(pg_session).distribute_minutes(meeting, minutes, user_id=str(alice.id))

    assert notified == [str(carol.id)]
    assert await _notified(pg_session, carol, "info") == 1
    assert await _notified(pg_session, bob, "info") == 0


async def test_academy_on_an_outside_action_owner_gets_no_task(pg_session, academy, events) -> None:
    academy(True)
    _project, alice, _bob, carol, meeting, _minutes = await _setup(pg_session)

    await MeetingService(pg_session).complete_meeting(meeting.id, user_id=str(alice.id))

    owners = await _task_owners(pg_session, meeting)
    assert owners == {"Order rebar": str(carol.id), "Fix crane": None}
    assert _announced_owners(events) == [str(carol.id), None]


async def test_academy_on_the_action_notification_names_its_project(pg_session, academy, monkeypatch) -> None:
    academy(True)
    project, _alice, bob, carol, meeting, _minutes = await _setup(pg_session)
    monkeypatch.setattr(notification_events, "async_session_factory", lambda: _NonCommittingSession(pg_session))

    await notification_events._on_meeting_action_items_created(
        Event(
            name=ACTIONS,
            data={
                "meeting_id": str(meeting.id),
                "project_id": str(project.id),
                "meeting_number": meeting.meeting_number,
                "action_items": [
                    {"description": "Order rebar", "owner_id": str(carol.id)},
                    {"description": "Fix crane", "owner_id": str(bob.id)},
                ],
            },
        )
    )

    assert await _notified(pg_session, carol, "task_assigned") == 1
    assert await _notified(pg_session, bob, "task_assigned") == 0


async def test_academy_off_unchanged(pg_session, academy, events) -> None:
    academy(False)
    _project, alice, bob, carol, meeting, minutes = await _setup(pg_session)
    service = MeetingService(pg_session)

    _row, notified = await service.distribute_minutes(meeting, minutes, user_id=str(alice.id))
    assert notified == [str(carol.id), str(bob.id)]
    await service.complete_meeting(meeting.id, user_id=str(alice.id))
    assert await _task_owners(pg_session, meeting) == {"Order rebar": str(carol.id), "Fix crane": str(bob.id)}
    assert _announced_owners(events) == [str(carol.id), str(bob.id)]
