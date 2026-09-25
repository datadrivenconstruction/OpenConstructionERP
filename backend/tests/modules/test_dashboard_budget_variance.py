# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The over-budget card counts money that is promised, not only money that is gone.

``variance.py`` was written because three callers each carried their own copy of
the rule and a correction reached one of them. This card was a fourth, and it
was missed because it spelled the subtraction differently: the others wrote
`revised - actual`, this one wrote `actual - planned`, so the gate that hunts
for the first shape could not see the second. Wording, not arithmetic, is what
kept it hidden.

The consequence is the one that matters on a dashboard. A project with 48.7
budgeted, 12.4 invoiced and 33.4 under signed order is 94% spoken for, and the
card whose whole job is to name over-budget projects left it off the list
entirely, because 12.4 is comfortably under 48.7.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dashboard.service import compute_budget_variance
from app.modules.finance.models import ProjectBudget
from app.modules.projects.models import Project
from tests._pg import transactional_session

D = Decimal


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A rolled-back session on the shared PostgreSQL unit database."""
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _project(session: AsyncSession, name: str) -> Project:
    project = Project(name=name, currency="EUR", owner_id=uuid.uuid4())
    session.add(project)
    await session.flush()
    return project


async def _budget(session: AsyncSession, project: Project, **money: str) -> None:
    row = ProjectBudget(
        project_id=project.id,
        currency_code="EUR",
        original_budget=D(money.get("original", "0")),
        revised_budget=D(money.get("revised", "0")),
        committed=D(money.get("committed", "0")),
        actual=D(money.get("actual", "0")),
        forecast_final=D(money.get("forecast", "0")),
    )
    session.add(row)
    await session.flush()


@pytest.mark.asyncio
async def test_commitment_alone_puts_a_project_on_the_card(session: AsyncSession) -> None:
    """Nothing has been invoiced past the budget, and the project is still over it."""
    project = await _project(session, "Ordered past the budget")
    # 43 still open on order plus 9 spent: the line finishes at 52.
    await _budget(session, project, revised="40.00", committed="43.00", actual="9.00")

    payload = await compute_budget_variance(session, [project])

    assert payload["over_budget_count"] == 1
    row = payload["top_over"][0]
    assert D(row["planned"]) == D("40.00")
    assert D(row["actual"]) == D("9.00")
    assert D(row["committed"]) == D("43.00")
    assert D(row["outturn"]) == D("52.00")
    assert D(row["variance"]) == D("12.00")
    assert row["pct"] == 30
    # The old reading: spend under budget, so nothing to report.
    assert D(row["actual"]) < D(row["planned"])


@pytest.mark.asyncio
async def test_the_outturn_is_taken_per_line_not_per_project(session: AsyncSession) -> None:
    """One line under order and another one invoiced are two different lines.

    Summing the project's commitment and its spend and taking the larger of the
    two totals would drop whichever total is smaller in full. Here that would
    report 30 instead of 50 and leave the project off the card.
    """
    project = await _project(session, "Two lines, two states")
    await _budget(session, project, revised="25.00", committed="30.00", actual="0.00")
    await _budget(session, project, revised="20.00", committed="0.00", actual="20.00")

    payload = await compute_budget_variance(session, [project])

    row = payload["top_over"][0]
    assert D(row["planned"]) == D("45.00")
    assert D(row["outturn"]) == D("50.00")
    assert D(row["variance"]) == D("5.00")


@pytest.mark.asyncio
async def test_a_typed_forecast_wins_over_the_commitment(session: AsyncSession) -> None:
    """The forecast column exists so a cost engineer can overrule the arithmetic."""
    project = await _project(session, "Forecast says otherwise")
    await _budget(session, project, revised="48.70", committed="60.00", actual="12.40", forecast="30.00")

    payload = await compute_budget_variance(session, [project])

    assert payload["over_budget_count"] == 0, "a recorded forecast of 30 against 48.7 is not an overrun"


@pytest.mark.asyncio
async def test_a_project_within_budget_stays_off_the_card(session: AsyncSession) -> None:
    project = await _project(session, "Quiet job")
    await _budget(session, project, revised="100.00", committed="40.00", actual="35.00")

    payload = await compute_budget_variance(session, [project])

    assert payload["over_budget_count"] == 0
    assert payload["top_over"] == []
