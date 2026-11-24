"""Reporting KPI snapshot must agree with the source modules for the same project.

Worked example: 3 incidents (2 not closed), 3 observations (open, in_progress,
closed), a schedule with a 10-day task at 100%, a 30-day task at 20% and a
summary row that must not be counted. Expected: open_defects 2,
open_observations 2, schedule progress (100*10 + 20*30) / 40 = 40.0.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reporting.models import KPISnapshot
from app.modules.reporting.service import ReportingService
from app.modules.safety.models import SafetyIncident, SafetyObservation
from app.modules.safety.service import SafetyService
from app.modules.schedule.models import Activity, Schedule
from tests._pg import transactional_session

TODAY = "2026-11-24"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session(disable_fks=True) as s:
        yield s


def _incident(pid: uuid.UUID, n: int, status: str) -> SafetyIncident:
    return SafetyIncident(
        project_id=pid,
        incident_number=f"INC-{n}",
        incident_date="2026-11-01",
        incident_type="near_miss",
        description="x",
        status=status,
    )


def _observation(pid: uuid.UUID, n: int, status: str) -> SafetyObservation:
    return SafetyObservation(
        project_id=pid,
        observation_number=f"OBS-{n}",
        observation_type="unsafe_act",
        description="x",
        status=status,
    )


def _activity(sid: uuid.UUID, name: str, dur: int, pct: str, kind: str = "task") -> Activity:
    return Activity(
        schedule_id=sid,
        name=name,
        start_date="2026-11-01",
        end_date="2026-12-01",
        duration_days=dur,
        progress_pct=pct,
        activity_type=kind,
    )


@pytest.mark.asyncio
async def test_kpi_snapshot_matches_safety_and_schedule_sources(session: AsyncSession) -> None:
    pid = uuid.uuid4()
    sched = Schedule(project_id=pid, name="Master")
    session.add(sched)
    session.add_all(
        [
            _incident(pid, 1, "reported"),
            _incident(pid, 2, "investigating"),
            _incident(pid, 3, "closed"),
            _observation(pid, 1, "open"),
            _observation(pid, 2, "in_progress"),
            _observation(pid, 3, "closed"),
        ]
    )
    await session.flush()
    session.add_all(
        [
            _activity(sched.id, "Foundations", 10, "100"),
            _activity(sched.id, "Frame", 30, "20"),
            _activity(sched.id, "Phase 1", 40, "60", kind="summary"),
        ]
    )
    await session.flush()

    svc = ReportingService(session)
    await svc._recalc_project_kpis(session, pid, TODAY)
    kpi = await svc.get_latest_kpi(pid)

    stats = await SafetyService(session).get_stats(pid)
    source_open_incidents = stats.total_incidents - stats.incidents_by_status.get("closed", 0)
    assert kpi is not None
    assert kpi.open_defects == source_open_incidents == 2
    assert kpi.open_observations == 2
    assert float(kpi.schedule_progress_pct) == 40.0


@pytest.mark.asyncio
async def test_stale_snapshot_is_refreshed_and_todays_is_kept(session: AsyncSession) -> None:
    pid = uuid.uuid4()
    session.add(_incident(pid, 1, "reported"))
    session.add(KPISnapshot(project_id=pid, snapshot_date="2000-01-01", open_defects=99, metadata_={}))
    await session.flush()

    svc = ReportingService(session)
    fresh = await svc.get_fresh_kpi(pid)
    assert fresh is not None
    assert fresh.snapshot_date != "2000-01-01"
    assert fresh.open_defects == 1

    again = await svc.get_fresh_kpi(pid)
    assert again.id == fresh.id


@pytest.mark.asyncio
async def test_report_converts_finance_to_override_currency_or_keeps_source_code(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = uuid.uuid4()
    project = SimpleNamespace(
        name="P",
        status="active",
        phase=None,
        planned_start_date=None,
        planned_end_date=None,
        currency="EUR",
        fx_rates=[{"code": "USD", "rate": "0.5"}],
    )

    async def _get_by_id(self, _pid):
        return project

    async def _dash(self, **_kw):
        return {"currency": "EUR", "total_budget_revised": "1000.00", "total_payable": "10"}

    monkeypatch.setattr("app.modules.projects.repository.ProjectRepository.get_by_id", _get_by_id)
    monkeypatch.setattr("app.modules.finance.service.FinanceService.get_dashboard", _dash)

    svc = ReportingService(session)
    # 1 USD = 0.5 EUR, so 1000 EUR = 2000 USD.
    snap = await svc._build_default_snapshot(pid, "financial", currency="USD")
    assert snap["summary"]["budget"] == "2000.00 USD"

    # No rate for GBP: the figure keeps its own currency code, never relabelled.
    snap = await svc._build_default_snapshot(pid, "financial", currency="GBP")
    assert snap["summary"]["budget"] == "1000.00 EUR"
    assert snap["currency_note"] == {"figures_currency": "EUR", "report_currency": "GBP"}
