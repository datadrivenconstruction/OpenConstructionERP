# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Deleting a position takes the cost model budget line it generated with it.

"Create budget" writes one cost model budget line per position. Deleting the
whole bill already removes or detaches them; deleting a single position (or a
section with its children) left its line behind, pointing at a position that no
longer exists. The same rule applies here: a line nobody has recorded money on
goes with the position, a line with committed, actual or earned money stays and
drops its position link.

Run:
    cd backend
    python -m pytest tests/modules/boq/test_deleting_a_position_takes_its_budget_line_with_it.py -v
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.schemas import PositionCreate, SectionCreate
from app.modules.boq.service import BOQService
from tests._pg import transactional_session
from tests.modules.boq.test_deleting_a_bill_takes_its_budgets_with_it import _bill, _line, _lines, _project


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # FK triggers off so a project can be seeded without standing up a user row.
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest.mark.asyncio
async def test_an_untouched_line_leaves_with_its_position(session: AsyncSession) -> None:
    project_id = await _project(session)
    _boq_id, (p1, p2) = await _bill(session, project_id, "Tender bill")
    gone = _line(project_id, p1)
    gone.description = "gone"
    kept = _line(project_id, p2)
    kept.description = "kept"
    session.add_all([gone, kept])
    await session.flush()

    await BOQService(session).delete_position(p1)
    await session.flush()
    session.expire_all()

    assert await _lines(session, project_id) == {"kept": p2}


@pytest.mark.asyncio
async def test_a_line_with_money_is_kept_and_detached(session: AsyncSession) -> None:
    project_id = await _project(session)
    _boq_id, (p1, p2) = await _bill(session, project_id, "Tender bill")
    committed = _line(project_id, p1, committed_amount="400")
    committed.description = "committed"
    earned = _line(project_id, p2, earned_amount=Decimal("300"))
    earned.description = "earned"
    session.add_all([committed, earned])
    await session.flush()

    service = BOQService(session)
    await service.delete_position(p1)
    await service.delete_position(p2)
    await session.flush()
    session.expire_all()

    assert await _lines(session, project_id) == {"committed": None, "earned": None}


@pytest.mark.asyncio
async def test_a_section_delete_releases_the_lines_of_its_children(session: AsyncSession) -> None:
    project_id = await _project(session)
    boq_id, (p1, _p2) = await _bill(session, project_id, "Tender bill")
    service = BOQService(session)
    section = await service.create_section(boq_id, SectionCreate(ordinal="10", description="Section"))
    child = await service.add_position(
        PositionCreate(
            boq_id=boq_id,
            parent_id=section.id,
            ordinal="10.01",
            description="Child",
            unit="m3",
            quantity=1,
            unit_rate=10,
        )
    )
    child_line = _line(project_id, child.id)
    child_line.description = "child"
    other = _line(project_id, p1)
    other.description = "other"
    session.add_all([child_line, other])
    await session.flush()

    await service.delete_position(section.id, cascade=True)
    await session.flush()
    session.expire_all()

    assert await _lines(session, project_id) == {"other": p1}
