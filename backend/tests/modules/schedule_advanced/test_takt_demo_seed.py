"""The demo takt plan: floors as locations, trade wagons handing off in order."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.schedule_advanced.models import Location, TaktActivity, TaktSchedule
from app.modules.schedule_advanced.takt_seed import seed_takt_demo
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio
OWNER = uuid.UUID("00000000-0000-4000-8000-00000000f16e")


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def test_project_gets_a_chained_takt_plan(session: AsyncSession) -> None:
    project = Project(id=uuid.uuid4(), name="Demo", currency="EUR", status="active", owner_id=OWNER)
    session.add(project)
    await session.flush()

    result = await seed_takt_demo(session, [project.id])

    assert (result["takt_schedules"], result["locations"], result["activities"]) == (1, 4, 4)
    takt = (await session.execute(select(TaktSchedule))).scalars().one()
    assert takt.location_sequence_count == 4 and takt.target_cycle_days == 5
    assert len((await session.execute(select(Location))).scalars().all()) == 4
    activities = (await session.execute(select(TaktActivity).order_by(TaktActivity.sequence_order))).scalars().all()
    assert activities[0].sequence_predecessor_activity_id is None
    assert all(a.sequence_predecessor_activity_id == activities[i].id for i, a in enumerate(activities[1:]))
    assert (await seed_takt_demo(session, [project.id]))["takt_schedules"] == 0
