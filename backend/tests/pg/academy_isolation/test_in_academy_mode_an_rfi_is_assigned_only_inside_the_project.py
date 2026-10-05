# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode an RFI is assigned only inside the project.

An RFI's ``assigned_to`` and ``ball_in_court`` come from the request body.
Assigning sends the assignee two in-app notifications (two handlers listen to
``rfi.assigned``), and the RFI log export and the RFI PDF print every person
on the RFI by full name or email, whatever project they belong to. On an
academy box a learner could therefore push RFIs at another learner and read
their name back on a printout. In academy mode create and update refuse an
assignee or ball-in-court id outside the project (a typed-in name is still
accepted), names are printed only for project members, and both notifications
carry the project so the backstop drops a stray one.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

import app.database as database
from app.core import event_handlers
from app.core.academy_isolation import USER_NOT_IN_PROJECT
from app.core.events import Event
from app.modules.notifications import events as notification_events
from app.modules.notifications.models import Notification
from app.modules.rfi.models import RFI
from app.modules.rfi.schemas import RFICreate, RFIUpdate
from app.modules.rfi.service import RFIService
from tests.pg.academy_isolation.rows import add_member, make_project, make_user
from tests.pg.tender_award_fixtures import _NonCommittingSession

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

ASSIGNED = "rfi.assigned"


async def _setup(session):
    alice = await make_user(session, name="Alice Owner")
    bob = await make_user(session, name="Bob Outsider")
    carol = await make_user(session, name="Carol Member")
    project = await make_project(session, alice)
    await add_member(session, project, carol)
    return project, alice, bob, carol


def _rfi(project, **fields) -> RFICreate:
    return RFICreate(project_id=project.id, subject="Slab edge detail", question="Which detail applies?", **fields)


def _refused(caught) -> None:
    assert caught.value.status_code == 422
    assert caught.value.detail["error"] == USER_NOT_IN_PROJECT


def _assigned(events) -> list[str]:
    return [data["assigned_to"] for name, data in events if name == ASSIGNED]


async def _count(session, project) -> int:
    return (await session.execute(select(func.count(RFI.id)).where(RFI.project_id == project.id))).scalar_one()


async def test_academy_on_an_rfi_cannot_name_someone_outside_the_project(pg_session, academy, events) -> None:
    academy(True)
    project, alice, bob, carol = await _setup(pg_session)
    service = RFIService(pg_session)

    for fields in ({"assigned_to": str(bob.id)}, {"ball_in_court": str(bob.id)}):
        with pytest.raises(HTTPException) as caught:
            await service.create_rfi(_rfi(project, **fields), user_id=str(alice.id))
        _refused(caught)
    assert await _count(pg_session, project) == 0

    rfi = await service.create_rfi(_rfi(project, assigned_to=str(carol.id)), user_id=str(alice.id))
    for fields in ({"assigned_to": str(bob.id)}, {"ball_in_court": str(bob.id)}):
        with pytest.raises(HTTPException) as caught:
            await service.update_rfi(rfi.id, RFIUpdate(**fields), actor_id=str(alice.id), actor_role="manager")
        _refused(caught)
    assert _assigned(events) == [str(carol.id)]


async def test_academy_on_members_and_typed_names_still_work(pg_session, academy, events) -> None:
    academy(True)
    project, alice, _bob, carol = await _setup(pg_session)
    service = RFIService(pg_session)

    rfi = await service.create_rfi(_rfi(project, ball_in_court="Structural engineer"), user_id=str(alice.id))
    await service.update_rfi(rfi.id, RFIUpdate(assigned_to=str(carol.id)), actor_id=str(alice.id), actor_role="manager")
    assert _assigned(events) == [str(carol.id)]


async def test_academy_on_names_are_printed_only_for_project_members(pg_session, academy, events) -> None:
    academy(False)
    project, alice, bob, _carol = await _setup(pg_session)
    service = RFIService(pg_session)
    rfi = await service.create_rfi(_rfi(project, assigned_to=str(bob.id)), user_id=str(alice.id))
    academy(True)

    people = await service.user_display_names([rfi.raised_by, rfi.assigned_to], project_id=project.id)

    assert people == {str(alice.id): "Alice Owner"}


async def test_academy_on_both_assignment_notifications_name_the_project(pg_session, academy, monkeypatch) -> None:
    academy(True)
    project, _alice, bob, carol = await _setup(pg_session)
    monkeypatch.setattr(notification_events, "async_session_factory", lambda: _NonCommittingSession(pg_session))
    monkeypatch.setattr(database, "async_session_factory", lambda: _NonCommittingSession(pg_session))

    for person in (carol, bob):
        event = Event(
            name=ASSIGNED,
            data={
                "project_id": str(project.id),
                "rfi_id": "6f1c1f9e-0000-4000-8000-000000000002",
                "rfi_number": "RFI-001",
                "subject": "Slab edge detail",
                "assigned_to": str(person.id),
            },
        )
        await notification_events._on_rfi_assigned(event)
        await event_handlers._notify_rfi_assigned(event)

    rows = (await pg_session.execute(select(Notification).where(Notification.entity_type == "rfi"))).scalars().all()
    assert sorted(r.notification_type for r in rows) == ["info", "rfi_assigned"]
    assert {r.user_id for r in rows} == {carol.id}
    assert {r.metadata_["project_id"] for r in rows} == {str(project.id)}


async def test_academy_off_unchanged(pg_session, academy, events) -> None:
    academy(False)
    project, alice, bob, _carol = await _setup(pg_session)
    service = RFIService(pg_session)

    rfi = await service.create_rfi(_rfi(project, assigned_to=str(bob.id)), user_id=str(alice.id))
    other = await service.create_rfi(_rfi(project), user_id=str(alice.id))
    await service.update_rfi(
        other.id, RFIUpdate(ball_in_court=str(bob.id)), actor_id=str(alice.id), actor_role="manager"
    )
    people = await service.user_display_names([rfi.raised_by, rfi.assigned_to], project_id=project.id)

    assert _assigned(events) == [str(bob.id)]
    assert people == {str(alice.id): "Alice Owner", str(bob.id): "Bob Outsider"}
