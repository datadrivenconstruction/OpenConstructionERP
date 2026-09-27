# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A locked bill is the project budget once, however many ways it gets there.

Locking a bill seeds the finance budget (``costmodel.budget.generated`` ->
``FinanceService.seed_budget_from_boq``, rows in category ``estimate``). The
"Create Budget" button on the same locked bill wrote a second set of its own
(category ``other``), and the toast after the lock offered exactly that button,
so following the product's own prompt put the budget at twice the estimate on
the Budgets tab and on the dashboard.

The button now goes through the same writer, and the writer also leaves alone a
bill that already has a budget from the old button (18.0 and earlier), so the
bill is budgeted once in either order.

Run:
    cd backend
    python -m pytest tests/modules/test_a_locked_bill_is_budgeted_once.py -v
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.finance.models import ProjectBudget
from app.modules.finance.service import FinanceService
from app.modules.projects.models import Project
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

D = Decimal

#: Net total of the bill below: 9 250 + 5 100 on WBS "A", 5 920 without a WBS.
BILL_TOTAL = D("20270.00")


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    # FK triggers off so a project can be seeded without standing up a user row.
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _bill(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """A locked bill with a section and three priced lines under it."""
    project = Project(name=f"Budget once {uuid.uuid4().hex[:6]}", currency="EUR", owner_id=uuid.uuid4())
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="Tender estimate", status="final", is_locked=True, metadata_={})
    session.add(boq)
    await session.flush()
    section = Position(
        boq_id=boq.id, ordinal="01", description="Foundations", unit="", quantity="0", unit_rate="0", total="20270"
    )
    session.add(section)
    await session.flush()
    for ordinal, wbs, qty, rate, total in (
        ("01.01", "A", "50", "185", "9250"),
        ("01.02", "A", "120", "42.5", "5100"),
        ("01.03", None, "3200", "1.85", "5920"),
    ):
        session.add(
            Position(
                boq_id=boq.id,
                parent_id=section.id,
                ordinal=ordinal,
                description=f"Line {ordinal}",
                unit="m3",
                quantity=qty,
                unit_rate=rate,
                total=total,
                wbs_id=wbs,
            )
        )
    await session.flush()
    return project.id, boq.id


async def _rows(session: AsyncSession, project_id: uuid.UUID) -> list[ProjectBudget]:
    session.expire_all()
    return list(
        (await session.execute(select(ProjectBudget).where(ProjectBudget.project_id == project_id))).scalars().all()
    )


def _original(rows: list[ProjectBudget]) -> Decimal:
    return sum((D(str(r.original_budget)) for r in rows), D("0"))


async def test_the_lock_then_the_button_budget_the_bill_once(session: AsyncSession) -> None:
    project_id, boq_id = await _bill(session)
    service = FinanceService(session)

    # The lock's event handler, then the button: both reach the same writer.
    await service.seed_budget_from_boq(project_id, boq_id)
    await service.seed_budget_from_boq(project_id, boq_id)

    rows = await _rows(session, project_id)
    assert _original(rows) == BILL_TOTAL
    assert sorted((r.wbs_id or "", r.category) for r in rows) == [("", "estimate"), ("A", "estimate")]
    revised = sum((D(str(r.revised_budget)) for r in rows), D("0"))
    assert revised == BILL_TOTAL


async def test_a_bill_budgeted_by_the_old_button_is_not_budgeted_again(session: AsyncSession) -> None:
    """18.0 wrote the button's rows as ``other`` with ``boq_id`` in their metadata.

    A later lock of that bill (or the button pressed again after the upgrade)
    must find them and add nothing: they are the bill's budget, and may carry
    revisions somebody booked against them.
    """
    project_id, boq_id = await _bill(session)
    for wbs, amount in (("A", "14350"), (None, "5920")):
        session.add(
            ProjectBudget(
                project_id=project_id,
                wbs_id=wbs,
                category="other",
                currency_code="EUR",
                original_budget=D(amount),
                revised_budget=D(amount) + D("100"),
                metadata_={"source": "boq", "boq_id": str(boq_id)},
            )
        )
    await session.flush()

    returned = await FinanceService(session).seed_budget_from_boq(project_id, boq_id)

    rows = await _rows(session, project_id)
    assert {r.id for r in returned} == {r.id for r in rows}
    assert [r.category for r in rows] == ["other", "other"]
    assert _original(rows) == BILL_TOTAL
    # The revision booked on the old rows survives untouched.
    assert sum((D(str(r.revised_budget)) for r in rows), D("0")) == BILL_TOTAL + D("200")


async def test_a_second_bill_still_adds_its_own_share(session: AsyncSession) -> None:
    """The old-button guard is per bill: another bill's legacy rows block nothing."""
    project_id, boq_id = await _bill(session)
    session.add(
        ProjectBudget(
            project_id=project_id,
            wbs_id="Z",
            category="other",
            currency_code="EUR",
            original_budget=D("500"),
            revised_budget=D("500"),
            metadata_={"source": "boq", "boq_id": str(uuid.uuid4())},
        )
    )
    await session.flush()

    await FinanceService(session).seed_budget_from_boq(project_id, boq_id)

    rows = await _rows(session, project_id)
    assert _original(rows) == BILL_TOTAL + D("500")
