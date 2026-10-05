# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode a Gantt names only the contacts of the project's people.

An activity's ``assignee_id`` is a contact id, and the Gantt turns it into a
name by looking the contact up install-wide, on purpose: a colleague on the
project picks from their own address book, and the viewer's list would not
know that contact. The write side already keeps an assignee to the caller's
own contacts, but a row written before that gate or by a path around it
would print another learner's contact. In academy mode a contact is named
only when it belongs to someone in the schedule's project; any other id is
left unnamed, which the Gantt already shows as an unknown assignee.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.modules.contacts.models import Contact
from app.modules.schedule.models import Activity, Schedule
from app.modules.schedule.service import ScheduleService
from tests.pg.academy_isolation.rows import add_member, make_project, make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _setup(session):
    alice = await make_user(session, name="Alice")
    bob = await make_user(session, name="Bob")
    carol = await make_user(session, name="Carol")
    project = await make_project(session, alice)
    await add_member(session, project, carol)
    contacts = {
        "alice": Contact(contact_type="person", first_name="Anna", last_name="Own", tenant_id=str(alice.id)),
        "carol": Contact(contact_type="person", first_name="Cleo", last_name="Colleague", created_by=str(carol.id)),
        "bob": Contact(contact_type="person", first_name="Bruno", last_name="Outsider", tenant_id=str(bob.id)),
    }
    session.add_all(contacts.values())
    start = date(2026, 10, 1)
    schedule = Schedule(
        project_id=project.id,
        name="Programme",
        schedule_type="baseline",
        description="",
        start_date=start.isoformat(),
        end_date=(start + timedelta(days=40)).isoformat(),
        status="active",
        metadata_={},
    )
    session.add(schedule)
    await session.flush()
    for index, (key, contact) in enumerate(contacts.items()):
        session.add(
            Activity(
                id=uuid.uuid4(),
                schedule_id=schedule.id,
                name=f"Work for {key}",
                description="",
                wbs_code=f"{index + 1:02d}",
                start_date=start.isoformat(),
                end_date=(start + timedelta(days=8)).isoformat(),
                duration_days=8,
                progress_pct="0",
                status="planned",
                dependencies=[],
                resources=[],
                boq_position_ids=[],
                assignee_id=contact.id,
                sort_order=index,
            )
        )
    await session.flush()
    return schedule


async def _names(session, schedule) -> dict[str, str | None]:
    gantt = await ScheduleService(session).get_gantt_data(schedule.id)
    return {a.name: a.assignee_name for a in gantt.activities}


async def test_academy_on_another_learners_contact_is_not_named(pg_session, academy) -> None:
    academy(True)
    schedule = await _setup(pg_session)

    assert await _names(pg_session, schedule) == {
        "Work for alice": "Anna Own",
        "Work for carol": "Cleo Colleague",
        "Work for bob": None,
    }


async def test_academy_off_unchanged(pg_session, academy) -> None:
    academy(False)
    schedule = await _setup(pg_session)

    assert await _names(pg_session, schedule) == {
        "Work for alice": "Anna Own",
        "Work for carol": "Cleo Colleague",
        "Work for bob": "Bruno Outsider",
    }
