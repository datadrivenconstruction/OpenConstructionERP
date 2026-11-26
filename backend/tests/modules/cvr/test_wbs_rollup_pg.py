"""A CVR report read back up the project's WBS tree from the database.

Two WBS levels, one line per leaf and one unallocated line: the parent must be
the sum of its children, the report the parent plus unallocated, and an element
of another project must never place a line.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cvr.models import CvrLine, CvrReport
from app.modules.cvr.service import CvrService
from app.modules.projects.models import Project, ProjectWBS
from app.modules.users.models import User
from tests._pg import transactional_session

D = Decimal


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(email=f"cvr-wbs-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="CVR", role="admin")
    session.add(user)
    await session.flush()
    proj = Project(name=f"CVR WBS {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="EUR")
    session.add(proj)
    await session.flush()
    return proj.id


async def test_report_rolls_up_the_wbs_tree(session: AsyncSession) -> None:
    pid = await _project(session)
    other = await _project(session)
    root = ProjectWBS(project_id=pid, code="1", name="Building", level=0)
    session.add(root)
    await session.flush()
    sub = ProjectWBS(project_id=pid, parent_id=root.id, code="1.1", name="Substructure", level=1, sort_order=1)
    sup = ProjectWBS(project_id=pid, parent_id=root.id, code="1.2", name="Superstructure", level=1, sort_order=2)
    foreign = ProjectWBS(project_id=other, code="9", name="Other project")
    session.add_all([sub, sup, foreign])
    await session.flush()

    report = CvrReport(project_id=pid, period="2026-11", currency="EUR")
    session.add(report)
    await session.flush()

    def line(wbs, cost, value, budget, fcost, fvalue):
        return CvrLine(
            report_id=report.id,
            wbs_id=wbs,
            cost_to_date=D(cost),
            value_to_date=D(value),
            budget_cost=D(budget),
            committed_cost=D("0"),
            forecast_cost=D(fcost),
            forecast_value=D(fvalue),
            metadata_={"source": "cost_spine", "positions": 2},
        )

    session.add_all(
        [
            line(sub.id, "30000", "35000", "100000", "100000", "120000"),
            line(sup.id, "60000", "70000", "200000", "210000", "230000"),
            line(None, "1000", "0", "0", "1000", "0"),
            line(foreign.id, "5", "0", "0", "5", "0"),
        ]
    )
    await session.flush()

    out = await CvrService(session).get_wbs_rollup(report.id)

    assert [n.code for n in out.nodes] == ["1", "1.1", "1.2"]
    top = out.nodes[0]
    assert top.child_count == 2 and top.line_count == 2 and top.positions == 4
    assert top.total.cost_to_date == D("90000.00")
    assert top.total.forecast_margin == D("40000.00")
    assert out.unallocated.line_count == 2
    assert out.unallocated.total.cost_to_date == D("1005.00")
    assert out.totals.cost_to_date == D("91005.00")
    assert out.line_count == 4 and out.wbs_count == 3
    assert out.findings == []
