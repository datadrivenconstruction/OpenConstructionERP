# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-backed end-to-end test for the forecast service (TOP-30 #19).

Seeds a real project with an EVM snapshot, a dated schedule with progress and
a high-severity unmitigated risk into an isolated PostgreSQL database (rolled
back on teardown), then drives ``ForecastService.get_project_forecast`` end to
end. Asserts the three sections (cost / schedule / risk) compose correctly from
real rows, and that a project with no sibling data degrades gracefully.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

# Import the sibling ORM modules so their tables exist in Base.metadata.
import app.modules.finance.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.risk.models  # noqa: F401
import app.modules.schedule.models  # noqa: F401
from app.modules.finance.models import EVMSnapshot
from app.modules.project_intelligence.forecast import TCPI_NOT_ACHIEVABLE
from app.modules.project_intelligence.service import ForecastService
from app.modules.projects.models import Project
from app.modules.risk.models import RiskItem
from app.modules.schedule.models import Activity, Schedule, ScheduleBaseline
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Yield an isolated PostgreSQL session rolled back on teardown.

    FK triggers are disabled so the seed rows can reference an owner / project
    without first materialising users in other modules; the forecast service
    only reads these tables, never enforces their cross-module FKs.
    """
    async with transactional_session(disable_fks=True) as sess:
        yield sess


async def _make_project(session: AsyncSession) -> Project:
    project = Project(
        name="Forecast Demo Tower",
        owner_id=uuid.uuid4(),
        currency="EUR",
    )
    session.add(project)
    await session.flush()
    return project


@pytest.mark.asyncio
async def test_forecast_service_full_chain(session: AsyncSession) -> None:
    """A fully seeded project yields cost + schedule + risk analytics."""
    project = await _make_project(session)

    # EVM snapshot — over budget (CPI < 1).
    session.add(
        EVMSnapshot(
            project_id=project.id,
            snapshot_date="2026-06-01",
            bac="1000000",
            pv="630000",
            ev="600000",
            ac="700000",
        )
    )

    # Schedule with a baseline finish + two activities behind plan.
    schedule = Schedule(
        project_id=project.id,
        name="Master",
        start_date="2026-01-01",
        end_date="2026-12-31",
        data_date="2026-06-01",
    )
    session.add(schedule)
    await session.flush()
    session.add(
        ScheduleBaseline(
            schedule_id=schedule.id,
            project_id=project.id,
            name="Original",
            baseline_date="2026-12-31",
            snapshot_data={},
            is_active=True,
        )
    )
    session.add_all(
        [
            Activity(
                schedule_id=schedule.id,
                name="Earthworks",
                start_date="2026-01-01",
                end_date="2026-12-31",
                progress_pct="30",
                status="in_progress",
            ),
            Activity(
                schedule_id=schedule.id,
                name="Structure",
                start_date="2026-01-01",
                end_date="2026-12-31",
                progress_pct="25",
                status="in_progress",
            ),
        ]
    )

    # One open high-severity unmitigated risk.
    session.add(
        RiskItem(
            project_id=project.id,
            code="R-001",
            title="Soil instability",
            impact_severity="high",
            status="identified",
            mitigation_strategy="",
        )
    )
    await session.flush()

    forecast = await ForecastService(session).get_project_forecast(project.id)

    # Project meta carried through.
    assert forecast.project_name == "Forecast Demo Tower"
    assert forecast.currency == "EUR"
    assert forecast.review_required is True

    # Cost section — recomputed EVM, over budget.
    assert forecast.cost.available is True
    assert forecast.cost.cpi == 0.8571
    assert forecast.cost.eac == "1166666.67"
    assert forecast.cost.vac == "-166666.67"
    assert forecast.cost.tcpi == "1.3333"

    # Schedule section — behind plan, both activities at risk, late finish.
    assert forecast.schedule.available is True
    assert forecast.schedule.activities_total == 2
    assert forecast.schedule.baseline_finish == "2026-12-31"
    assert forecast.schedule.finish_variance_days is not None
    assert forecast.schedule.finish_variance_days > 0
    assert forecast.schedule.at_risk_task_count == 2

    # Risk section — composed from CPI/SPI/VAC + the open risk; non-empty
    # rationale and a confidence reflecting all signals present.
    assert forecast.risk.band in {"amber", "red"}
    assert forecast.risk.score > 0.0
    assert forecast.risk.confidence == 1.0
    assert forecast.risk.rationale
    assert any("risk" in r.lower() for r in forecast.risk.rationale)


@pytest.mark.asyncio
async def test_forecast_service_empty_project_degrades(session: AsyncSession) -> None:
    """A bare project (no EVM snapshot, no schedule, no risks) degrades cleanly."""
    project = await _make_project(session)
    await session.flush()

    forecast = await ForecastService(session).get_project_forecast(project.id)

    assert forecast.cost.available is False
    assert forecast.cost.reason == "no_evm_snapshot"
    assert forecast.schedule.available is False
    assert forecast.schedule.reason == "no_schedule"
    # Risk still computes (deterministic) — green with risks-only confidence.
    assert forecast.risk.band == "green"
    assert forecast.risk.confidence == 0.2
    assert forecast.risk.rationale


@pytest.mark.asyncio
async def test_forecast_service_tcpi_not_achievable_when_budget_spent(session: AsyncSession) -> None:
    """Budget fully consumed with work remaining → TCPI not-achievable sentinel."""
    project = await _make_project(session)
    session.add(
        EVMSnapshot(
            project_id=project.id,
            snapshot_date="2026-06-01",
            bac="1000000",
            pv="900000",
            ev="800000",
            ac="1000000",  # BAC == AC, EV < BAC → work remains
        )
    )
    await session.flush()

    forecast = await ForecastService(session).get_project_forecast(project.id)
    assert forecast.cost.available is True
    assert forecast.cost.tcpi == TCPI_NOT_ACHIEVABLE
