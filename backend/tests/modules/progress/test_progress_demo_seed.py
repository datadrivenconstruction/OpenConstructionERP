"""A demo project with a priced bill and no time sheets still shows tracked positions."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.progress.models import ProgressEntry
from app.modules.progress.seed import seed_position_progress_demo
from app.modules.projects.models import Project
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio
OWNER = uuid.UUID("00000000-0000-4000-8000-00000000f15e")


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def test_bill_without_hours_gets_readings(session: AsyncSession) -> None:
    project = Project(id=uuid.uuid4(), name="Demo", currency="EUR", status="active", owner_id=OWNER)
    session.add(project)
    boq = BOQ(id=uuid.uuid4(), project_id=project.id, name="Bill")
    session.add(boq)
    await session.flush()
    for n in range(12):
        session.add(
            Position(
                id=uuid.uuid4(),
                boq_id=boq.id,
                ordinal=f"01.{n:02d}",
                description=f"Item {n}",
                unit="m2",
                quantity="10",
                unit_rate="5",
                total="50",
            )
        )
    await session.flush()

    result = await seed_position_progress_demo(session, [project.id])

    assert result == {"projects": 1, "entries": 8}
    rows = (await session.execute(select(ProgressEntry).where(ProgressEntry.project_id == project.id))).scalars().all()
    assert len(rows) == 8 and all(r.boq_position_id for r in rows)
    assert (await seed_position_progress_demo(session, [project.id]))["entries"] == 0
