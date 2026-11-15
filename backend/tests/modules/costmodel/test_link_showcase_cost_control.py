"""A showcase project gets cost lines, so the report shows planned and committed money on them."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import Contract
from app.modules.costmodel.cost_control_demo import link_showcase_cost_control
from app.modules.costmodel.cost_control_service import CostControlService
from app.modules.costmodel.models import BudgetLine
from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
from app.modules.projects.models import Project
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio
OWNER = uuid.UUID("00000000-0000-4000-8000-00000000f11e")


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _showcase(session: AsyncSession) -> uuid.UUID:
    project = Project(id=uuid.uuid4(), name="Showcase", currency="EUR", status="active", owner_id=OWNER)
    session.add(project)
    await session.flush()
    for n, amount in enumerate(("1000000", "2000000"), start=1):
        session.add(BudgetLine(project_id=project.id, category=f"Section {n}", planned_amount=amount, currency="EUR"))
    session.add(
        Contract(
            project_id=project.id,
            code="SUB-1",
            title="Structure",
            contract_type="lump_sum",
            counterparty_type="subcontractor",
            total_value=Decimal("750000"),
            currency="EUR",
            status="active",
        )
    )
    po = PurchaseOrder(
        project_id=project.id, po_number="PO-1", po_type="standard", status="issued", currency_code="EUR"
    )
    session.add(po)
    await session.flush()
    session.add(
        PurchaseOrderItem(po_id=po.id, description="Steel", quantity="1", unit="lot", unit_rate="50000", amount="50000")
    )
    await session.flush()
    return project.id


async def test_report_shows_planned_and_committed_on_cost_lines(session: AsyncSession) -> None:
    project_id = await _showcase(session)
    before = await CostControlService(session).report(project_id, today=date(2026, 11, 15))
    assert Decimal(before.totals["planned"]) == 0

    assert await link_showcase_cost_control(session, project_id) == 2
    report = await CostControlService(session).report(project_id, today=date(2026, 11, 15))

    assert Decimal(report.totals["planned"]) == Decimal("3000000")
    assert Decimal(report.totals["committed"]) == Decimal("800000")
    assert not [r for r in report.rows if r.kind == "unassigned"]
    assert await link_showcase_cost_control(session, project_id) == 0
