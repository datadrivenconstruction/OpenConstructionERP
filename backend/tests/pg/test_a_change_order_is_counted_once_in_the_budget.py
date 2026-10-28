# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An approved change order moves the budget by its own amount, once.

The approval writes one budget delta row per change order, and the finance
dashboard, the EVM snapshot and the impact preview all read the budget through
``BudgetRepository.aggregate_for_dashboard``, which sums every row of the
project. A delta row therefore has to carry only the change: ``original`` 0 and
``revised`` the change order's effect. That is what the row carried from
v2.9.17 until 17.7.0.

17.7.0 changed the create path to carry the project budget forward as the
row's ``original`` and to write ``revised`` as that plus the effect. It was
meant for a project with no baseline rows, whose Finance tab showed a total
budget of zero once a change order had been approved. The aggregator sums the
carried figure once per change order, so a 100 000 budget with two change
orders of 10 000 and 5 000 came out as 310 000 original and 325 000 revised,
or 210 000 and 225 000 without a baseline row. The right answer is 100 000 and
115 000 in both cases, and the table below is that answer through the real
service, the real repository and the real dashboard.

The project without baseline rows is the case 17.7.0 set out to fix, and it
stays fixed: the aggregator takes the original budget from the project's own
budget figure when change order rows are all the project has.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.changeorders.schemas import ChangeOrderCreate
from app.modules.changeorders.service import ChangeOrderService
from app.modules.finance.models import ProjectBudget
from app.modules.finance.repository import BudgetRepository
from app.modules.finance.service import FinanceService
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _user(session) -> uuid.UUID:
    user = User(email=f"co-budget-{uuid.uuid4().hex[:10]}@test.com", hashed_password="x")
    session.add(user)
    await session.flush()
    return user.id


async def _project(session, owner: uuid.UUID, *, budget: str | None, with_base_line: bool) -> uuid.UUID:
    project = Project(name="Budget delta project", owner_id=owner, currency="USD", budget_estimate=budget)
    session.add(project)
    await session.flush()
    if with_base_line:
        session.add(
            ProjectBudget(
                project_id=project.id,
                wbs_id="base",
                category="Base",
                currency_code="USD",
                original_budget=Decimal("100000"),
                revised_budget=Decimal("100000"),
                metadata_={},
            )
        )
    await session.commit()
    return project.id


async def _approve(session, project_id: uuid.UUID, owner: uuid.UUID, amount: str, *, currency: str = "") -> None:
    """Create, submit and approve one change order through the service, as the UI does."""
    svc = ChangeOrderService(session)
    submitter = await _user(session)
    await session.commit()
    order = await svc.create_order(
        ChangeOrderCreate(
            project_id=project_id,
            title=f"Scope change {amount}",
            description="",
            cost_impact=amount,
            currency=currency,
        )
    )
    await session.commit()
    await svc.submit_order(order.id, str(submitter))
    await session.commit()
    await svc.approve_order(order.id, str(owner))
    await session.commit()


async def _change_order_rows(session, project_id: uuid.UUID) -> list[tuple[Decimal, Decimal]]:
    rows = (
        (
            await session.execute(
                select(ProjectBudget).where(ProjectBudget.project_id == project_id).order_by(ProjectBudget.category)
            )
        )
        .scalars()
        .all()
    )
    return [
        (Decimal(str(r.original_budget)), Decimal(str(r.revised_budget)))
        for r in rows
        if isinstance(r.metadata_, dict) and r.metadata_.get("change_order_id")
    ]


@pytest.mark.parametrize("with_base_line", [True, False], ids=["with_base_line", "without_base_lines"])
async def test_two_change_orders_move_the_budget_by_their_own_amounts(pg_session, with_base_line: bool) -> None:
    owner = await _user(pg_session)
    project_id = await _project(pg_session, owner, budget="100000", with_base_line=with_base_line)

    await _approve(pg_session, project_id, owner, "10000")
    await _approve(pg_session, project_id, owner, "5000")

    # Each delta row carries its change and nothing else.
    assert sorted(await _change_order_rows(pg_session, project_id)) == [
        (Decimal("0"), Decimal("5000")),
        (Decimal("0"), Decimal("10000")),
    ]

    agg = await BudgetRepository(pg_session).aggregate_for_dashboard(project_id=project_id)
    assert agg["original_by_currency"] == {"USD": 100000.0}
    assert agg["revised_by_currency"] == {"USD": 115000.0}

    # The figures a user actually reads: the Finance tab KPI cards.
    dashboard = await FinanceService(pg_session).get_dashboard(project_id=project_id)
    assert Decimal(str(dashboard["total_budget_original"])) == Decimal("100000")
    assert Decimal(str(dashboard["total_budget_revised"])) == Decimal("115000")


async def test_one_change_order_on_a_project_without_base_lines_does_not_show_a_zero_budget(pg_session) -> None:
    """The case 17.7.0 was written for, held so that restoring the delta shape does not undo it."""
    owner = await _user(pg_session)
    project_id = await _project(pg_session, owner, budget="100000", with_base_line=False)

    await _approve(pg_session, project_id, owner, "10000")

    dashboard = await FinanceService(pg_session).get_dashboard(project_id=project_id)
    assert Decimal(str(dashboard["total_budget_original"])) == Decimal("100000")
    assert Decimal(str(dashboard["total_budget_revised"])) == Decimal("110000")


async def test_a_deductive_change_order_lowers_the_revised_budget_only(pg_session) -> None:
    owner = await _user(pg_session)
    project_id = await _project(pg_session, owner, budget="100000", with_base_line=False)

    await _approve(pg_session, project_id, owner, "-8000")

    agg = await BudgetRepository(pg_session).aggregate_for_dashboard(project_id=project_id)
    assert agg["original_by_currency"] == {"USD": 100000.0}
    assert agg["revised_by_currency"] == {"USD": 92000.0}


async def test_a_foreign_change_order_with_no_rate_is_not_taken_out_of_the_budget(pg_session) -> None:
    """A change order the approval could not convert never reached the project budget figure.

    The approval skips the budget writeback for a foreign currency with no FX
    rate and records the row in its own currency. Subtracting that row from the
    project budget to find the original would take out money that was never put
    in, so the original here has to stay at 100 000, not drop to 95 000.
    """
    owner = await _user(pg_session)
    project_id = await _project(pg_session, owner, budget="100000", with_base_line=False)

    await _approve(pg_session, project_id, owner, "10000")
    await _approve(pg_session, project_id, owner, "5000", currency="EUR")

    agg = await BudgetRepository(pg_session).aggregate_for_dashboard(project_id=project_id)
    assert agg["original_by_currency"] == {"USD": 100000.0, "EUR": 0.0}
    assert agg["revised_by_currency"] == {"USD": 110000.0, "EUR": 5000.0}


async def test_a_project_with_no_budget_rows_is_left_empty(pg_session) -> None:
    """Negative control: nothing is invented for a project that has no budget rows at all."""
    owner = await _user(pg_session)
    project_id = await _project(pg_session, owner, budget="100000", with_base_line=False)

    agg = await BudgetRepository(pg_session).aggregate_for_dashboard(project_id=project_id)
    assert agg["original_by_currency"] == {}
    assert agg["revised_by_currency"] == {}


async def test_the_portfolio_rollup_counts_each_project_budget_once(pg_session) -> None:
    """The accessible-projects scope takes the same path as a single project."""
    owner = await _user(pg_session)
    with_base = await _project(pg_session, owner, budget="100000", with_base_line=True)
    without_base = await _project(pg_session, owner, budget="100000", with_base_line=False)
    for project_id in (with_base, without_base):
        await _approve(pg_session, project_id, owner, "10000")
        await _approve(pg_session, project_id, owner, "5000")

    agg = await BudgetRepository(pg_session).aggregate_for_dashboard(project_ids={with_base, without_base})
    assert agg["original_by_currency"] == {"USD": 200000.0}
    assert agg["revised_by_currency"] == {"USD": 230000.0}
