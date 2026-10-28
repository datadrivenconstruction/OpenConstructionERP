# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-backed tests for the estimate-rollup composition service.

Builds a project with a known BOQ base, known preliminaries and known allowances
on a real PostgreSQL database, then asserts the composed estimate total is exactly
``boq_base + preliminaries + allowances`` - Decimal-exact and rendered as the
Decimal strings the endpoint returns. Covers the double-counting decision
(allowances contribute remaining, not held), the multi-currency FX fold, and the
two degenerate paths (no prelims / allowances, and an empty project) that must
return the BOQ base / zeros rather than an error.

All seeds land in an isolated PostgreSQL database rolled back on teardown; FK
triggers are off so the cross-module rows can be inserted without a users row.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

# Import the sibling ORM modules so their tables exist in Base.metadata.
import app.modules.allowances.models  # noqa: F401
import app.modules.boq.models  # noqa: F401
import app.modules.preliminaries.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
from app.modules.allowances.models import Allowance, AllowanceDrawdown
from app.modules.boq.models import BOQ, Position
from app.modules.estimate_rollup.schemas import EstimateRollupResponse
from app.modules.estimate_rollup.service import compute_estimate_rollup
from app.modules.preliminaries.models import PrelimItem
from app.modules.projects.models import Project
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Isolated PostgreSQL session, FK triggers off, rolled back on teardown."""
    async with transactional_session(disable_fks=True) as sess:
        yield sess


async def _make_project(session: AsyncSession, *, currency: str = "EUR", fx_rates: list | None = None) -> Project:
    project = Project(
        name="Estimate Tower",
        owner_id=uuid.uuid4(),
        currency=currency,
        fx_rates=fx_rates if fx_rates is not None else [],
    )
    session.add(project)
    await session.flush()
    return project


async def _add_boq_with_leaves(session: AsyncSession, project: Project, totals: list[str]) -> BOQ:
    """Create one BOQ with a section header plus one priced leaf per total."""
    boq = BOQ(project_id=project.id, name="Main BOQ")
    session.add(boq)
    await session.flush()
    section = Position(
        boq_id=boq.id,
        parent_id=None,
        ordinal="01",
        description="Section",
        unit="",
        quantity="0",
        unit_rate="0",
        total="0",
    )
    session.add(section)
    await session.flush()
    for i, total in enumerate(totals):
        session.add(
            Position(
                boq_id=boq.id,
                parent_id=section.id,
                ordinal=f"01.{i:03d}",
                description=f"Item {i}",
                unit="m3",
                quantity="1",
                unit_rate=total,
                total=total,
            )
        )
    await session.flush()
    return boq


async def _add_prelim(
    session: AsyncSession,
    project: Project,
    *,
    item_type: str,
    fixed_amount: str = "0",
    rate_per_period: str = "0",
    periods: str = "0",
) -> None:
    session.add(
        PrelimItem(
            project_id=project.id,
            label="Prelim",
            category="general",
            item_type=item_type,
            fixed_amount=fixed_amount,
            rate_per_period=rate_per_period,
            periods=periods,
        )
    )
    await session.flush()


async def _add_allowance(
    session: AsyncSession,
    project: Project,
    *,
    allowance_type: str,
    held: str,
    currency: str = "EUR",
    drawdowns: list[str] | None = None,
) -> None:
    allowance = Allowance(
        project_id=project.id,
        label=allowance_type,
        allowance_type=allowance_type,
        held_amount=held,
        currency=currency,
    )
    session.add(allowance)
    await session.flush()
    for amount in drawdowns or []:
        session.add(AllowanceDrawdown(allowance_id=allowance.id, amount=amount))
    await session.flush()


# ── Core: exact composition ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rollup_is_exactly_boq_base_plus_prelims_plus_contingency(session: AsyncSession) -> None:
    """estimate_total == boq_base + preliminaries + contingency, Decimal-exact as strings."""
    project = await _make_project(session)
    # BOQ base: 1000 + 500 = 1500 (no markups).
    await _add_boq_with_leaves(session, project, ["1000.00", "500.00"])
    # Preliminaries: 200 fixed + (100 * 3) time-related = 500.
    await _add_prelim(session, project, item_type="fixed", fixed_amount="200.00")
    await _add_prelim(session, project, item_type="time_related", rate_per_period="100.00", periods="3")
    # Contingency held 400, no drawdowns -> remaining 400.
    await _add_allowance(session, project, allowance_type="contingency", held="400.00")

    rollup = await compute_estimate_rollup(session, project.id)
    body = EstimateRollupResponse.from_rollup(rollup, project_id=project.id)

    assert body.base_currency == "EUR"
    assert body.boq_base == "1500.00"
    assert body.preliminaries.total == "500.00"
    assert body.preliminaries.fixed_total == "200.00"
    assert body.preliminaries.time_related_total == "300.00"
    assert body.allowances.contingency_total == "400.00"
    assert body.allowances.total == "400.00"
    # 1500 + 500 + 400 = 2400.
    assert body.estimate_total == "2400.00"

    # The rendered lines reconstruct the total exactly.
    line_sum = sum((Decimal(line.amount) for line in body.lines), Decimal("0"))
    assert line_sum == Decimal(body.estimate_total)
    keys = [line.key for line in body.lines]
    assert keys == ["boq_base", "preliminaries", "contingency"]


@pytest.mark.asyncio
async def test_allowances_use_remaining_not_held(session: AsyncSession) -> None:
    """A drawdown reduces the allowance the estimate carries (remaining, not held)."""
    project = await _make_project(session)
    await _add_boq_with_leaves(session, project, ["1000.00"])
    # Provisional sum held 300 with a 120 drawdown -> remaining 180 rolls up.
    await _add_allowance(
        session,
        project,
        allowance_type="provisional_sum",
        held="300.00",
        drawdowns=["120.00"],
    )
    # Contingency held 400 with a 100 drawdown -> remaining 300.
    await _add_allowance(
        session,
        project,
        allowance_type="contingency",
        held="400.00",
        drawdowns=["100.00"],
    )

    rollup = await compute_estimate_rollup(session, project.id)
    body = EstimateRollupResponse.from_rollup(rollup, project_id=project.id)

    assert body.allowances.provisional_sum_total == "180.00"
    assert body.allowances.contingency_total == "300.00"
    assert body.allowances.total == "480.00"
    # 1000 base + 480 remaining allowances = 1480 (NOT 1000 + 700 held).
    assert body.estimate_total == "1480.00"


@pytest.mark.asyncio
async def test_rollup_folds_foreign_currency_allowance_to_base(session: AsyncSession) -> None:
    """A foreign-currency allowance is converted to the project base at the FX rate."""
    project = await _make_project(
        session,
        currency="EUR",
        fx_rates=[{"code": "USD", "rate": "2", "label": "US Dollar"}],
    )
    await _add_boq_with_leaves(session, project, ["1000.00"])
    # 100 USD contingency at 1 USD = 2 EUR -> 200 EUR.
    await _add_allowance(session, project, allowance_type="contingency", held="100.00", currency="USD")

    rollup = await compute_estimate_rollup(session, project.id)
    body = EstimateRollupResponse.from_rollup(rollup, project_id=project.id)

    assert body.allowances.contingency_total == "200.00"
    assert body.estimate_total == "1200.00"
    assert body.allowances.unconverted_currencies == []


# ── Degenerate paths ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rollup_no_prelims_no_allowances_is_boq_base(session: AsyncSession) -> None:
    """With only a BOQ, the total is the BOQ base and the only line is the base."""
    project = await _make_project(session)
    await _add_boq_with_leaves(session, project, ["750.00", "250.00"])

    rollup = await compute_estimate_rollup(session, project.id)
    body = EstimateRollupResponse.from_rollup(rollup, project_id=project.id)

    assert body.boq_base == "1000.00"
    assert body.estimate_total == "1000.00"
    assert body.preliminaries.total == "0.00"
    assert body.allowances.total == "0.00"
    assert [line.key for line in body.lines] == ["boq_base"]


@pytest.mark.asyncio
async def test_rollup_empty_project_is_zero_not_error(session: AsyncSession) -> None:
    """A project with no BOQ, prelims or allowances composes to zeros, never raising."""
    project = await _make_project(session)

    rollup = await compute_estimate_rollup(session, project.id)
    body = EstimateRollupResponse.from_rollup(rollup, project_id=project.id)

    assert body.boq_base == "0.00"
    assert body.estimate_total == "0.00"
    assert body.preliminaries.item_count == 0
    assert body.allowances.allowance_count == 0
    assert [line.key for line in body.lines] == ["boq_base"]
