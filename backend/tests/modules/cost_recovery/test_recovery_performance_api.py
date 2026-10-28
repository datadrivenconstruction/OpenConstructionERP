# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for cost-recovery performance analytics (PG, py3.12).

Exercises the recovery-performance service end to end on real PostgreSQL: the
overall recovery rate over the back-charge ledger, the high-vs-low traceability
cohort split (the band read from the back-charge metadata, defaulting to the
conservative low cohort), the absorbed-cost figure, currencies kept separate,
and the portfolio rollup across several projects.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cost_recovery.models import BackCharge
from app.modules.cost_recovery.schemas import BackChargeCreate, BackChargeUpdate
from app.modules.cost_recovery.service import (
    build_portfolio_recovery_performance,
    build_recovery_performance,
    create_back_charge,
    update_back_charge,
)
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession, *, currency: str = "USD") -> uuid.UUID:
    user = User(
        email=f"crp-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="CRP",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"CRP {uuid.uuid4().hex[:6]}", owner_id=user.id, currency=currency)
    session.add(proj)
    await session.flush()
    return proj.id


async def _back_charge(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    gross: Decimal,
    pct: Decimal = Decimal("1"),
    currency: str = "USD",
    band: str | None = None,
    status: str = "agreed",
    recovered: Decimal | None = None,
) -> BackCharge:
    bc = await create_back_charge(
        session,
        project_id,
        BackChargeCreate(
            responsible_party="sub",
            gross_amount=gross,
            chargeable_pct=pct,
            currency=currency,
        ),
    )
    if band is not None:
        bc.metadata_ = {"traceability_band": band}
    if status != "proposed" or recovered is not None:
        # Only set recovered_amount when supplied: passing None would clear a
        # NOT NULL column (model_dump(exclude_unset) keeps an explicit None).
        update_fields: dict[str, object] = {"status": status}
        if recovered is not None:
            update_fields["recovered_amount"] = recovered
        await update_back_charge(
            session,
            project_id,
            bc.id,
            BackChargeUpdate(**update_fields),
        )
    await session.flush()
    return bc


@pytest.mark.asyncio
async def test_recovery_rate_overall(session: AsyncSession) -> None:
    pid = await _project(session)
    # 1000 chargeable, 690 recovered -> 0.6900 rate.
    await _back_charge(
        session,
        pid,
        gross=Decimal("1000.00"),
        status="recovered",
        recovered=Decimal("690.00"),
    )
    perf = await build_recovery_performance(session, pid)
    assert perf.item_count == 1
    assert perf.primary_currency == "USD"
    assert perf.primary_rate == Decimal("0.6900")


@pytest.mark.asyncio
async def test_recovery_high_vs_low_cohort_split(session: AsyncSession) -> None:
    pid = await _project(session)
    # Strong-traceability item recovers fully; weak-traceability item recovers
    # nothing - the headline contrast the engine exists to surface.
    await _back_charge(
        session,
        pid,
        gross=Decimal("1000.00"),
        band="strong",
        status="recovered",
        recovered=Decimal("1000.00"),
    )
    await _back_charge(
        session,
        pid,
        gross=Decimal("1000.00"),
        band="weak",
        status="agreed",
        recovered=Decimal("0"),
    )
    perf = await build_recovery_performance(session, pid)
    usd = next(c for c in perf.by_currency if c.currency == "USD")
    by_cohort = {c.cohort: c for c in usd.by_cohort}
    assert by_cohort["high"].rate == Decimal("1.0000")
    assert by_cohort["low"].rate == Decimal("0.0000")


@pytest.mark.asyncio
async def test_recovery_band_defaults_to_low(session: AsyncSession) -> None:
    pid = await _project(session)
    # No band stamped -> conservative weak -> LOW cohort, never inflating HIGH.
    await _back_charge(
        session,
        pid,
        gross=Decimal("500.00"),
        status="agreed",
    )
    perf = await build_recovery_performance(session, pid)
    usd = next(c for c in perf.by_currency if c.currency == "USD")
    cohorts = {c.cohort for c in usd.by_cohort}
    assert cohorts == {"low"}
    bands = {c.cohort for c in usd.by_band}
    assert bands == {"weak"}


@pytest.mark.asyncio
async def test_recovery_absorbed_total(session: AsyncSession) -> None:
    pid = await _project(session)
    # A waived back-charge gives up its chargeable amount: absorbed.
    await _back_charge(
        session,
        pid,
        gross=Decimal("800.00"),
        status="waived",
        recovered=Decimal("0"),
    )
    perf = await build_recovery_performance(session, pid)
    usd = next(c for c in perf.by_currency if c.currency == "USD")
    assert usd.absorbed_total == Decimal("800.00")


@pytest.mark.asyncio
async def test_recovery_currencies_kept_separate(session: AsyncSession) -> None:
    pid = await _project(session, currency="USD")
    await _back_charge(session, pid, gross=Decimal("1000.00"), currency="USD", status="agreed")
    await _back_charge(session, pid, gross=Decimal("400.00"), currency="EUR", status="agreed")
    perf = await build_recovery_performance(session, pid)
    currencies = {c.currency for c in perf.by_currency}
    assert currencies == {"USD", "EUR"}
    # Largest chargeable currency is the headline.
    assert perf.primary_currency == "USD"


@pytest.mark.asyncio
async def test_recovery_performance_scoped_to_project(session: AsyncSession) -> None:
    pid = await _project(session)
    other = await _project(session)
    await _back_charge(session, pid, gross=Decimal("100.00"), status="agreed")
    await _back_charge(session, other, gross=Decimal("999.00"), status="agreed")
    perf = await build_recovery_performance(session, pid)
    assert perf.item_count == 1


@pytest.mark.asyncio
async def test_portfolio_recovery_pools_projects(session: AsyncSession) -> None:
    a = await _project(session)
    b = await _project(session)
    await _back_charge(session, a, gross=Decimal("1000.00"), status="recovered", recovered=Decimal("1000.00"))
    await _back_charge(session, b, gross=Decimal("1000.00"), status="agreed", recovered=Decimal("0"))
    perf = await build_portfolio_recovery_performance(session, [a, b])
    assert perf.item_count == 2
    usd = next(c for c in perf.by_currency if c.currency == "USD")
    # 1000 recovered out of 2000 chargeable across the two projects.
    assert usd.chargeable_total == Decimal("2000.00")
    assert usd.recovered_total == Decimal("1000.00")
    assert usd.rate == Decimal("0.5000")


@pytest.mark.asyncio
async def test_portfolio_recovery_empty_ids(session: AsyncSession) -> None:
    perf = await build_portfolio_recovery_performance(session, [])
    assert perf.item_count == 0
    assert perf.primary_currency == ""
    assert perf.primary_rate is None
    assert perf.by_currency == ()
