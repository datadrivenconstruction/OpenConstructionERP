# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode a punch owner or an inspector must be in the project.

A punch item's ``assigned_to`` and an inspection's ``inspector_id`` are free id
strings from the request body. They are shown back through the party-name
resolver, which turns any user or contact id on the install into a name, and a
punch item's ``assigned_to`` becomes the owner of its deadline: once it is
overdue, the deadlines sweeper notifies that owner in-app and by email. So on an
academy box one learner could read another learner's name, or send them a real
email, by naming them on a punch item. In academy mode the id must be a project
member or a contact in the caller's own address book (a typed-in name is still
accepted), and the sweeper's notifications carry the project, so the
notification backstop drops one addressed outside it.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.academy_isolation import USER_NOT_IN_PROJECT
from app.modules.contacts.models import Contact
from app.modules.deadlines.sweeper import OVERDUE_TYPE, sweep_overdue
from app.modules.inspections.schemas import InspectionCreate, InspectionUpdate
from app.modules.inspections.service import InspectionService
from app.modules.notifications.models import Notification
from app.modules.punchlist.schemas import PunchItemCreate, PunchItemUpdate
from app.modules.punchlist.service import PunchListService
from tests.pg.academy_isolation.rows import add_member, make_project, make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _setup(session):
    alice = await make_user(session, name="Alice")
    bob = await make_user(session, name="Bob")
    carol = await make_user(session, name="Carol")
    project = await make_project(session, alice)
    await add_member(session, project, carol)
    mine = Contact(contact_type="subcontractor", company_name="Alice drywall", tenant_id=str(alice.id))
    theirs = Contact(contact_type="subcontractor", company_name="Bob drywall", tenant_id=str(bob.id))
    session.add_all([mine, theirs])
    await session.flush()
    return project, alice, bob, carol, mine, theirs


def _refused(caught) -> None:
    assert caught.value.status_code == 422
    assert caught.value.detail["error"] == USER_NOT_IN_PROJECT


async def _overdue_for(session, user) -> int:
    return (
        await session.execute(
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id, Notification.notification_type == OVERDUE_TYPE
            )
        )
    ).scalar_one()


def _punch(project, assigned_to, **extra) -> PunchItemCreate:
    return PunchItemCreate(project_id=project.id, title="Patch drywall", assigned_to=assigned_to, **extra)


async def test_academy_on_a_punch_item_names_only_project_people(pg_session, academy, events) -> None:
    academy(True)
    project, alice, bob, _carol, _mine, theirs = await _setup(pg_session)
    service = PunchListService(pg_session)

    for outsider in (str(bob.id), str(theirs.id)):
        with pytest.raises(HTTPException) as caught:
            await service.create_item(_punch(project, outsider), user_id=str(alice.id))
        _refused(caught)

    item = await service.create_item(_punch(project, None), user_id=str(alice.id))
    with pytest.raises(HTTPException) as on_update:
        await service.update_item(item.id, PunchItemUpdate(assigned_to=str(bob.id)), actor_id=str(alice.id))
    _refused(on_update)
    await pg_session.refresh(item)
    assert item.assigned_to is None


async def test_academy_on_an_inspector_must_be_in_the_project(pg_session, academy, events) -> None:
    academy(True)
    project, alice, bob, _carol, _mine, _theirs = await _setup(pg_session)
    service = InspectionService(pg_session)

    with pytest.raises(HTTPException) as caught:
        await service.create_inspection(
            InspectionCreate(project_id=project.id, inspection_type="general", title="Walk", inspector_id=str(bob.id)),
            user_id=str(alice.id),
        )
    _refused(caught)
    inspection = await service.create_inspection(
        InspectionCreate(project_id=project.id, inspection_type="general", title="Walk"), user_id=str(alice.id)
    )
    with pytest.raises(HTTPException) as on_update:
        await service.update_inspection(
            inspection.id, InspectionUpdate(inspector_id=str(bob.id)), actor_id=str(alice.id)
        )
    _refused(on_update)


async def test_academy_on_members_own_contacts_and_typed_names_still_work(pg_session, academy, events) -> None:
    academy(True)
    project, alice, _bob, carol, mine, _theirs = await _setup(pg_session)
    punch = PunchListService(pg_session)

    for named in (str(carol.id), str(mine.id), "Site foreman Jan"):
        item = await punch.create_item(_punch(project, named), user_id=str(alice.id))
        assert item.assigned_to == named
    await punch.update_item(item.id, PunchItemUpdate(assigned_to=str(alice.id)), actor_id=str(alice.id))
    inspection = await InspectionService(pg_session).create_inspection(
        InspectionCreate(project_id=project.id, inspection_type="general", title="Walk", inspector_id=str(carol.id)),
        user_id=str(alice.id),
    )
    assert inspection.inspector_id == str(carol.id)


async def test_academy_on_the_sweeper_does_not_notify_an_owner_outside_the_project(pg_session, academy, events) -> None:
    # Written before the gate (flag off), then swept on the academy box.
    academy(False)
    project, alice, bob, _carol, _mine, _theirs = await _setup(pg_session)
    await PunchListService(pg_session).create_item(
        _punch(project, str(bob.id), due_date=date.today() - timedelta(days=3)), user_id=str(alice.id)
    )
    academy(True)

    await sweep_overdue(pg_session, now=datetime.now(UTC))

    assert await _overdue_for(pg_session, bob) == 0
    assert not [d for name, d in events if name.startswith("notifications.") and d.get("user_id") == str(bob.id)]


async def test_academy_off_unchanged(pg_session, academy, events) -> None:
    academy(False)
    project, alice, bob, _carol, _mine, theirs = await _setup(pg_session)
    punch = PunchListService(pg_session)

    item = await punch.create_item(
        _punch(project, str(bob.id), due_date=date.today() - timedelta(days=3)), user_id=str(alice.id)
    )
    other = await punch.create_item(_punch(project, str(theirs.id)), user_id=str(alice.id))
    await punch.update_item(other.id, PunchItemUpdate(assigned_to=str(bob.id)), actor_id=str(alice.id))
    inspection = await InspectionService(pg_session).create_inspection(
        InspectionCreate(project_id=project.id, inspection_type="general", title="Walk", inspector_id=str(bob.id)),
        user_id=str(alice.id),
    )
    assert inspection.inspector_id == str(bob.id)
    assert item.assigned_to == str(bob.id)

    await sweep_overdue(pg_session, now=datetime.now(UTC))
    assert await _overdue_for(pg_session, bob) == 1
