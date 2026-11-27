"""A section moved by the editor keeps its place when the bill is read again."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ
from app.modules.boq.schemas import PositionCreate
from app.modules.boq.service import BOQService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


@pytest.mark.asyncio
async def test_section_moved_with_its_lines_reads_back_in_the_new_place(session: AsyncSession) -> None:
    owner = User(email=f"mv-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="E", role="admin")
    session.add(owner)
    await session.flush()
    project = Project(name="Move", currency="EUR", region="FR", owner_id=owner.id)
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="Bill", status="draft", metadata_={})
    session.add(boq)
    await session.flush()
    svc = BOQService(session)

    async def add(ordinal: str, unit: str, parent=None):
        return await svc.add_position(
            PositionCreate(
                boq_id=boq.id,
                ordinal=ordinal,
                description=f"d{ordinal}",
                unit=unit,
                quantity=1,
                unit_rate=1,
                parent_id=parent.id if parent else None,
            )
        )

    a = await add("1", "section")
    a1 = await add("1.1", "m2", a)
    b = await add("2", "section")
    b1 = await add("2.1", "m2", b)
    c = await add("3", "section")

    ids = [x.id for x in (a, a1, b, b1, c)]
    a_id, a1_id, b_id, b1_id, c_id = ids
    # Section A moves below B: the editor sends the whole bill in document order.
    await svc.reorder_positions(boq.id, [b_id, b1_id, a_id, a1_id, c_id])
    positions, _ = await svc.position_repo.list_for_boq(boq.id)
    assert [p.id for p in positions] == [b_id, b1_id, a_id, a1_id, c_id]
    assert [p.sort_order for p in positions] == [0, 1, 2, 3, 4]
