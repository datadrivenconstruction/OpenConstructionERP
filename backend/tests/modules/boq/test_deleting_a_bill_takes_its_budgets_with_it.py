# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Deleting a bill takes the budgets it generated with it.

"Create budget" on a locked bill writes two layers: finance budgets stamped
with the bill's id, one per WBS or section group, and one cost model budget
line per position. The bill can then be unlocked and deleted, and the delete
left both layers behind: budget totals that no bill stands behind any more,
pointing at a bill and at positions that no longer exist.

A generated row nobody has worked on is removed with the bill. A row that
carries money recorded against it since (committed, actual, earned value, or a
revised finance budget) is kept, because deleting it would lose that record,
and it is detached instead: the link to the gone bill is cleared and the finance
row notes which bill it came from.

Run:
    cd backend
    python -m pytest tests/modules/boq/test_deleting_a_bill_takes_its_budgets_with_it.py -v
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ
from app.modules.boq.schemas import PositionCreate
from app.modules.boq.service import BOQService
from app.modules.costmodel.models import BudgetLine
from app.modules.finance.models import ProjectBudget
from app.modules.projects.models import Project
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # FK triggers off so a project can be seeded without standing up a user row.
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    project = Project(
        name=f"Budget orphans {uuid.uuid4().hex[:6]}",
        currency="EUR",
        region="DACH",
        owner_id=uuid.uuid4(),
    )
    session.add(project)
    await session.flush()
    return project.id


async def _bill(session: AsyncSession, project_id: uuid.UUID, name: str) -> tuple[uuid.UUID, list[uuid.UUID]]:
    boq = BOQ(project_id=project_id, name=name, status="draft", metadata_={})
    session.add(boq)
    await session.flush()
    boq_id = boq.id
    session.expunge(boq)
    service = BOQService(session)
    ids = []
    for n in (1, 2):
        pos = await service.add_position(
            PositionCreate(
                boq_id=boq_id, ordinal=f"0{n}", description=f"Line {n}", unit="m3", quantity=10, unit_rate=100
            )
        )
        ids.append(pos.id)
    return boq_id, ids


def _finance(project_id: uuid.UUID, boq_id: uuid.UUID, wbs: str, **money: Decimal) -> ProjectBudget:
    return ProjectBudget(
        project_id=project_id,
        wbs_id=wbs,
        category="other",
        currency_code="EUR",
        original_budget=Decimal("1000"),
        revised_budget=money.pop("revised_budget", Decimal("1000")),
        metadata_={"source": "boq", "boq_id": str(boq_id)},
        **money,
    )


def _line(project_id: uuid.UUID, position_id: uuid.UUID, **money: object) -> BudgetLine:
    return BudgetLine(
        project_id=project_id,
        boq_position_id=position_id,
        category="material",
        description="generated",
        planned_amount="1000",
        committed_amount=str(money.get("committed_amount", "0")),
        actual_amount=str(money.get("actual_amount", "0")),
        forecast_amount="1000",
        earned_amount=money.get("earned_amount"),
        currency="EUR",
    )


async def _finance_rows(session: AsyncSession, project_id: uuid.UUID) -> dict[str, dict]:
    rows = (await session.execute(select(ProjectBudget).where(ProjectBudget.project_id == project_id))).scalars()
    return {row.wbs_id: dict(row.metadata_ or {}) for row in rows}


async def _lines(session: AsyncSession, project_id: uuid.UUID) -> dict[str, uuid.UUID | None]:
    rows = (await session.execute(select(BudgetLine).where(BudgetLine.project_id == project_id))).scalars()
    return {row.description: row.boq_position_id for row in rows}


@pytest.mark.asyncio
async def test_untouched_generated_budgets_leave_with_the_bill(session: AsyncSession) -> None:
    project_id = await _project(session)
    boq_id, (p1, p2) = await _bill(session, project_id, "Tender bill")
    session.add_all([_finance(project_id, boq_id, "A"), _finance(project_id, boq_id, "B")])
    session.add_all([_line(project_id, p1), _line(project_id, p2)])
    await session.flush()

    await BOQService(session).delete_boq(boq_id)
    await session.flush()
    session.expire_all()

    assert await _finance_rows(session, project_id) == {}
    assert await _lines(session, project_id) == {}


@pytest.mark.asyncio
async def test_budgets_with_money_recorded_are_kept_and_detached(session: AsyncSession) -> None:
    project_id = await _project(session)
    boq_id, (p1, p2) = await _bill(session, project_id, "Tender bill")
    session.add_all(
        [
            _finance(project_id, boq_id, "spent", actual=Decimal("250")),
            _finance(project_id, boq_id, "revised", revised_budget=Decimal("1200")),
            _finance(project_id, boq_id, "untouched"),
        ]
    )
    committed = _line(project_id, p1, committed_amount="400")
    committed.description = "committed"
    earned = _line(project_id, p2, earned_amount=Decimal("300"))
    earned.description = "earned"
    session.add_all([committed, earned])
    await session.flush()

    await BOQService(session).delete_boq(boq_id)
    await session.flush()
    session.expire_all()

    finance = await _finance_rows(session, project_id)
    assert set(finance) == {"spent", "revised"}
    for meta in finance.values():
        assert "boq_id" not in meta
        assert meta["deleted_boq_id"] == str(boq_id)
    assert await _lines(session, project_id) == {"committed": None, "earned": None}


@pytest.mark.asyncio
async def test_another_bill_s_budgets_are_left_alone(session: AsyncSession) -> None:
    project_id = await _project(session)
    gone, (g1, _g2) = await _bill(session, project_id, "Old bill")
    kept, (k1, _k2) = await _bill(session, project_id, "Current bill")
    session.add_all([_finance(project_id, gone, "old"), _finance(project_id, kept, "current")])
    kept_line = _line(project_id, k1)
    kept_line.description = "current"
    session.add_all([_line(project_id, g1), kept_line])
    await session.flush()

    await BOQService(session).delete_boq(gone)
    await session.flush()
    session.expire_all()

    assert set(await _finance_rows(session, project_id)) == {"current"}
    assert await _lines(session, project_id) == {"current": k1}
