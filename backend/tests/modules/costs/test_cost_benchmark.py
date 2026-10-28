# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the regional cost-benchmark metric variants (#21).

PostgreSQL, py3.12. CostBenchmarkService.portfolio_distribution gained a metric
selector: the original currency-scoped ``cost_per_m2`` (BOQ grand total over
gross floor area) plus two dimensionless ratios benchmarked across the tenant's
own projects - ``overrun_pct`` (priced BOQ over approved budget) and
``recovery_rate`` (recovered share of chargeable cost). These tests seed real
projects (BOQ leaf positions, approved budgets, back-charges) and assert each
metric's distribution, that the ratio metrics are not currency-scoped, that the
region filter narrows the set, that projects lacking a metric's inputs are
skipped, and that an unknown metric falls back to cost_per_m2.

Under tests/modules (the single non-sharded job) so adding them never reshuffles
the pytest-split unit shards.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.cost_recovery.models import BackCharge
from app.modules.costs.service import CostBenchmarkService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _owner(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"bench-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Bench",
        role="admin",
    )
    session.add(user)
    await session.flush()
    return user.id


async def _project(
    session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    region: str = "DACH",
    currency: str = "EUR",
    project_type: str | None = None,
    gross_floor_area: str | None = None,
    budget_estimate: str | None = None,
) -> uuid.UUID:
    proj = Project(
        name=f"Bench {uuid.uuid4().hex[:6]}",
        owner_id=owner_id,
        region=region,
        currency=currency,
        project_type=project_type,
        gross_floor_area=gross_floor_area,
        budget_estimate=budget_estimate,
    )
    session.add(proj)
    await session.flush()
    return proj.id


async def _boq_total(session: AsyncSession, project_id: uuid.UUID, total: str) -> None:
    """Give a project a one-leaf BOQ whose grand total (base currency) is *total*."""
    boq = BOQ(project_id=project_id, name="Main BOQ")
    session.add(boq)
    await session.flush()
    # A leaf (non-section): real unit + non-zero quantity/rate. With no
    # metadata.currency the leaf total is read as-is in the project base currency.
    # ``ordinal`` and ``description`` are NOT NULL on the model, and omitting
    # them made every test that priced a BOQ fail in setup rather than on its
    # own assertion. One position per BOQ here, so the ordinal cannot collide.
    session.add(
        Position(
            boq_id=boq.id,
            ordinal="01",
            description="Benchmark leaf",
            unit="m2",
            quantity="1",
            unit_rate=total,
            total=total,
        )
    )
    await session.flush()


async def _back_charge(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    gross: str,
    chargeable_pct: str,
    recovered: str,
    currency: str = "EUR",
) -> None:
    session.add(
        BackCharge(
            project_id=project_id,
            responsible_party="subcontractor a",
            gross_amount=Decimal(gross),
            chargeable_pct=Decimal(chargeable_pct),
            recovered_amount=Decimal(recovered),
            currency=currency,
            status="agreed",
        )
    )
    await session.flush()


def _svc(session: AsyncSession) -> CostBenchmarkService:
    return CostBenchmarkService(session)


@pytest.mark.asyncio
async def test_cost_per_m2_is_the_default_metric(session: AsyncSession) -> None:
    """The default metric is the currency-scoped cost-per-m2 distribution."""
    owner = await _owner(session)
    for total, area in (("1000", "10"), ("3000", "10"), ("5000", "10")):
        pid = await _project(session, owner, gross_floor_area=area)
        await _boq_total(session, pid, total)

    result = await _svc(session).portfolio_distribution(owner_id=owner, is_admin=True)

    assert result["metric"] == "cost_per_m2"
    assert result["currency"] == "EUR"
    port = result["own_portfolio"]
    assert port is not None
    # cost/m2 of 100, 300, 500.
    assert port["min"] == Decimal("100")
    assert port["median"] == Decimal("300")
    assert port["max"] == Decimal("500")
    assert port["project_count"] == 3
    assert port["confidence"] == "medium"


@pytest.mark.asyncio
async def test_overrun_pct_distribution_is_currency_free(session: AsyncSession) -> None:
    """Overrun is (priced BOQ - approved budget) / budget, a signed fraction."""
    owner = await _owner(session)
    # 1200 vs 1000 -> +0.2; 800 vs 1000 -> -0.2; 1000 vs 1000 -> 0.
    for total, budget in (("1200", "1000"), ("800", "1000"), ("1000", "1000")):
        pid = await _project(session, owner, budget_estimate=budget)
        await _boq_total(session, pid, total)

    result = await _svc(session).portfolio_distribution(owner_id=owner, is_admin=True, metric="overrun_pct")

    assert result["metric"] == "overrun_pct"
    # A ratio is dimensionless, so no currency is reported.
    assert result["currency"] == ""
    port = result["own_portfolio"]
    assert port is not None
    assert port["min"] == Decimal("-0.2")
    assert port["median"] == Decimal("0")
    assert port["max"] == Decimal("0.2")
    assert port["project_count"] == 3


@pytest.mark.asyncio
async def test_overrun_skips_projects_without_a_budget(session: AsyncSession) -> None:
    """A project with a BOQ but no approved budget yields no overrun and is skipped."""
    owner = await _owner(session)
    with_budget = await _project(session, owner, budget_estimate="1000")
    await _boq_total(session, with_budget, "1500")
    no_budget = await _project(session, owner, budget_estimate=None)
    await _boq_total(session, no_budget, "2000")

    result = await _svc(session).portfolio_distribution(owner_id=owner, is_admin=True, metric="overrun_pct")

    port = result["own_portfolio"]
    assert port is not None
    assert port["project_count"] == 1
    assert port["median"] == Decimal("0.5")


@pytest.mark.asyncio
async def test_recovery_rate_distribution_is_currency_free(session: AsyncSession) -> None:
    """Recovery rate is recovered / chargeable per project, in [0, 1]."""
    owner = await _owner(session)
    # 600 chargeable, 150 recovered -> 0.25.
    p1 = await _project(session, owner)
    await _back_charge(session, p1, gross="1000", chargeable_pct="0.6", recovered="150")
    # 1000 chargeable, 1000 recovered -> 1.0.
    p2 = await _project(session, owner)
    await _back_charge(session, p2, gross="1000", chargeable_pct="1.0", recovered="1000")
    # No back-charge: nothing chargeable, so this project is skipped.
    await _project(session, owner)

    result = await _svc(session).portfolio_distribution(owner_id=owner, is_admin=True, metric="recovery_rate")

    assert result["metric"] == "recovery_rate"
    assert result["currency"] == ""
    port = result["own_portfolio"]
    assert port is not None
    assert port["project_count"] == 2
    assert port["min"] == Decimal("0.2500")
    assert port["max"] == Decimal("1.0000")
    assert port["confidence"] == "low"


@pytest.mark.asyncio
async def test_region_filter_narrows_the_distribution(session: AsyncSession) -> None:
    """The region filter scopes the distribution to one region's projects."""
    owner = await _owner(session)
    dach = await _project(session, owner, region="DACH")
    await _back_charge(session, dach, gross="1000", chargeable_pct="1.0", recovered="500")
    uk = await _project(session, owner, region="UK")
    await _back_charge(session, uk, gross="1000", chargeable_pct="1.0", recovered="900")

    result = await _svc(session).portfolio_distribution(
        owner_id=owner, is_admin=True, region="UK", metric="recovery_rate"
    )

    port = result["own_portfolio"]
    assert port is not None
    assert port["project_count"] == 1
    # Only the UK project's 0.9 rate is in the distribution.
    assert port["min"] == Decimal("0.9000")
    assert port["max"] == Decimal("0.9000")


@pytest.mark.asyncio
async def test_metric_with_no_qualifying_data_is_empty_but_echoes_metric(session: AsyncSession) -> None:
    """A metric with no usable project yields an empty portfolio that names the metric."""
    owner = await _owner(session)
    # A project with neither a budget nor a back-charge: nothing for either ratio.
    await _project(session, owner)

    result = await _svc(session).portfolio_distribution(owner_id=owner, is_admin=True, metric="recovery_rate")

    assert result["metric"] == "recovery_rate"
    assert result["own_portfolio"] is None
    assert result["percentile_vs_own"] is None


@pytest.mark.asyncio
async def test_unknown_metric_falls_back_to_cost_per_m2(session: AsyncSession) -> None:
    """An unrecognised metric behaves as the default cost-per-m2 distribution."""
    owner = await _owner(session)
    pid = await _project(session, owner, gross_floor_area="10")
    await _boq_total(session, pid, "2000")

    result = await _svc(session).portfolio_distribution(owner_id=owner, is_admin=True, metric="bogus")

    assert result["metric"] == "cost_per_m2"
    port = result["own_portfolio"]
    assert port is not None
    assert port["median"] == Decimal("200")


@pytest.mark.asyncio
async def test_overrun_positions_a_supplied_value(session: AsyncSession) -> None:
    """A supplied value is positioned against the ratio distribution (percentile)."""
    owner = await _owner(session)
    for total, budget in (("1100", "1000"), ("1200", "1000"), ("1300", "1000")):
        pid = await _project(session, owner, budget_estimate=budget)
        await _boq_total(session, pid, total)

    # Overruns are 0.1, 0.2, 0.3; a 0.3 value sits at the top of the distribution.
    result = await _svc(session).portfolio_distribution(
        owner_id=owner, is_admin=True, metric="overrun_pct", cost_per_m2=Decimal("0.3")
    )

    assert result["percentile_vs_own"] == 100.0
    assert result["explanation"] != ""
