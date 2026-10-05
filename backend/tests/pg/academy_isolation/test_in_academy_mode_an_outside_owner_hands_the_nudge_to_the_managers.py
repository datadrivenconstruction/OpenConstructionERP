# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode an outside owner hands an overdue nudge to the managers.

An overdue item's owner is nudged once per window, and the in-app row is the
record that it was. When the owner is outside the project, the academy
notification backstop drops that row, so nothing recorded the nudge: every
sweep picked the item up again, reached the backstop again and published the
item's ``deadlines.<module>.overdue`` timeline event again, while nobody in
the project heard about it. In academy mode an owner outside the project is
now treated like an owner who is not there at all: the project managers get
the nudge, their row is the record, and the next sweep stays quiet. Nothing
changes with the flag off.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.modules.deadlines.sweeper import OVERDUE_TYPE, sweep_overdue
from app.modules.notifications.models import Notification
from app.modules.punchlist.schemas import PunchItemCreate
from app.modules.punchlist.service import PunchListService
from tests.pg.academy_isolation.rows import make_project, make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _setup(session):
    # Written with the flag off, as a row from before the assignee gate.
    alice = await make_user(session, name="Alice")
    bob = await make_user(session, name="Bob")
    project = await make_project(session, alice)
    item = await PunchListService(session).create_item(
        PunchItemCreate(
            project_id=project.id,
            title="Patch drywall",
            assigned_to=str(bob.id),
            due_date=date.today() - timedelta(days=3),
        ),
        user_id=str(alice.id),
    )
    return alice, bob, item


async def _overdue_for(session, user) -> int:
    stmt = select(func.count(Notification.id)).where(
        Notification.user_id == user.id, Notification.notification_type == OVERDUE_TYPE
    )
    return (await session.execute(stmt)).scalar_one()


def _timeline(events, item) -> list[dict]:
    return [d for name, d in events if name == "deadlines.punchlist.overdue" and d.get("entity_id") == str(item.id)]


async def _sweep_twice(session) -> None:
    now = datetime.now(UTC)
    await sweep_overdue(session, now=now)
    await sweep_overdue(session, now=now + timedelta(minutes=5))


async def test_academy_on_the_managers_get_it_once_and_the_next_sweep_is_quiet(pg_session, academy, events) -> None:
    academy(False)
    alice, bob, item = await _setup(pg_session)
    academy(True)

    await _sweep_twice(pg_session)

    assert await _overdue_for(pg_session, bob) == 0
    assert await _overdue_for(pg_session, alice) == 1
    assert len(_timeline(events, item)) == 1


async def test_academy_off_unchanged(pg_session, academy, events) -> None:
    academy(False)
    alice, bob, item = await _setup(pg_session)

    await _sweep_twice(pg_session)

    assert await _overdue_for(pg_session, bob) == 1
    assert await _overdue_for(pg_session, alice) == 0
    assert len(_timeline(events, item)) == 1
