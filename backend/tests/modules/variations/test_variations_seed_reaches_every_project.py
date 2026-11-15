"""The generic variations register lands on every demo project, not a random few."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.variations.models import Notice
from app.modules.variations.seed import seed_variations_demo
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio
OWNER = uuid.UUID("00000000-0000-4000-8000-00000000f12e")


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def test_every_demo_project_gets_notices(session: AsyncSession) -> None:
    ids = []
    for n in range(14):
        project = Project(id=uuid.uuid4(), name=f"Demo {n}", currency="EUR", status="active", owner_id=OWNER)
        session.add(project)
        ids.append(project.id)
    await session.flush()

    await seed_variations_demo(session, ids)

    counts = dict(
        (
            await session.execute(
                select(Notice.project_id, func.count()).where(Notice.project_id.in_(ids)).group_by(Notice.project_id)
            )
        ).all()
    )
    assert set(counts) == set(ids)
