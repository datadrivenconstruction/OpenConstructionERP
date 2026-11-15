"""The demo dispatch board: standing places, project columns and today's crew cards."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dispatch.models import DispatchLocation, DispatchPlacement
from app.modules.dispatch.seed import seed_dispatch_demo
from app.modules.projects.models import Project
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio
OWNER = uuid.UUID("00000000-0000-4000-8000-00000000f17e")


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def test_board_gets_columns_and_cards(session: AsyncSession) -> None:
    ids = []
    for n in range(6):
        project = Project(id=uuid.uuid4(), name=f"Demo {n}", currency="EUR", status="active", owner_id=OWNER)
        session.add(project)
        ids.append(project.id)
    await session.flush()

    result = await seed_dispatch_demo(session, ids)

    assert result == {"locations": 6, "crews": 3, "placements": 3}
    kinds = [k for (k,) in (await session.execute(select(DispatchLocation.kind))).all()]
    assert sorted(kinds) == ["project"] * 4 + ["shop", "yard"]
    assert len((await session.execute(select(DispatchPlacement))).scalars().all()) == 3
    assert (await seed_dispatch_demo(session, ids))["locations"] == 0
