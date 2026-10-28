"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Project Controls aggregation tests (feature 09).

Exercises the six new KPIs and the snapshot orchestrator against a real
PostgreSQL session (the only dialect the app runs on) in a per-test
transaction that is rolled back on teardown.

Coverage:
    * each new KPI returns the expected value/unit/source_record_count for a
      seeded single project;
    * a two-currency portfolio buckets money per ISO code and never blends;
    * an empty project degrades to Decimal("0") with source_record_count 0;
    * status banding stamps green/amber/red correctly;
    * the snapshot returns all six domain groups with drill URLs;
    * drill-down returns the seeded rows with cross-module deep links.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bi_dashboards import kpis
from app.modules.project_controls.service import SPINE, ProjectControlsService
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as sess:
        yield sess


# ── Seed helpers ────────────────────────────────────────────────────────────


async def _seed_project(
    session: AsyncSession,
    *,
    currency: str = "EUR",
    fx_rates: list | None = None,
) -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"pc-{uuid.uuid4().hex[:10]}@controls.io",
        hashed_password="x",
        full_name="Controls Owner",
        role="admin",
    )
    session.add(owner)
    await session.flush()
    project = Project(
        id=uuid.uuid4(),
        name="Controls project",
        owner_id=owner.id,
        currency=currency,
        fx_rates=fx_rates or [],
    )
    session.add(project)
    await session.flush()
    return project.id


async def _seed_risk(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    impact_cost: str,
    status: str = "identified",
    severity: str = "high",
    mitigation: str = "",
    probability: str = "0.5",
    currency: str = "EUR",
) -> None:
    from app.modules.risk.models import RiskItem

    session.add(
        RiskItem(
            project_id=project_id,
            code=f"R-{uuid.uuid4().hex[:6]}",
            title="Test risk",
            impact_cost=impact_cost,
            impact_severity=severity,
            status=status,
            mitigation_strategy=mitigation,
            probability=probability,
            currency=currency,
        )
    )
    await session.flush()


async def _seed_ncr(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    status: str = "identified",
) -> None:
    from app.modules.ncr.models import NCR

    session.add(
        NCR(
            project_id=project_id,
            ncr_number=f"NCR-{uuid.uuid4().hex[:5]}",
            title="Defect",
            description="x",
            ncr_type="material",
            severity="major",
            status=status,
        )
    )
    await session.flush()


async def _seed_incident(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    incident_date: str = "2026-03-15",
) -> None:
    from app.modules.safety.models import SafetyIncident

    session.add(
        SafetyIncident(
            project_id=project_id,
            incident_number=f"INC-{uuid.uuid4().hex[:5]}",
            incident_date=incident_date,
            incident_type="slip",
            severity="minor",
            description="x",
        )
    )
    await session.flush()


async def _seed_variation(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    amount: str,
    status: str = "submitted",
    currency: str = "EUR",
) -> None:
    from app.modules.variations.models import VariationRequest

    session.add(
        VariationRequest(
            project_id=project_id,
            code=f"VR-{uuid.uuid4().hex[:6]}",
            estimated_cost_impact=Decimal(amount),
            status=status,
            currency=currency,
        )
    )
    await session.flush()


# ── Single-project KPI cases ──────────────────────────────────────────────


async def test_risk_open_exposure_single_project(session: AsyncSession) -> None:
    pid = await _seed_project(session)
    await _seed_risk(session, pid, impact_cost="10000", status="identified")
    await _seed_risk(session, pid, impact_cost="5000", status="open")
    # Closed risk is excluded.
    await _seed_risk(session, pid, impact_cost="99999", status="closed")

    comp = await kpis.compute("risk_open_exposure", session, project_id=pid)
    assert comp.unit == "currency"
    assert comp.value == Decimal("15000")
    assert comp.source_record_count == 2
    assert comp.breakdown["currency"] == "EUR"


async def test_risk_high_unmitigated_count(session: AsyncSession) -> None:
    pid = await _seed_project(session)
    # high + no mitigation -> counts
    await _seed_risk(session, pid, impact_cost="1", severity="critical", mitigation="")
    # high + mitigated -> excluded
    await _seed_risk(session, pid, impact_cost="1", severity="high", mitigation="Plan B")
    # low severity -> excluded
    await _seed_risk(session, pid, impact_cost="1", severity="low", mitigation="")

    comp = await kpis.compute("risk_high_unmitigated_count", session, project_id=pid)
    assert comp.unit == "count"
    assert comp.value == Decimal("1")


async def test_ncr_open_count(session: AsyncSession) -> None:
    pid = await _seed_project(session)
    await _seed_ncr(session, pid, status="identified")
    await _seed_ncr(session, pid, status="in_progress")
    await _seed_ncr(session, pid, status="closed")

    comp = await kpis.compute("ncr_open_count", session, project_id=pid)
    assert comp.value == Decimal("2")
    assert comp.source_record_count == 2


async def test_incident_count_with_period(session: AsyncSession) -> None:
    from datetime import date

    pid = await _seed_project(session)
    await _seed_incident(session, pid, incident_date="2026-03-15")
    await _seed_incident(session, pid, incident_date="2026-03-20")
    await _seed_incident(session, pid, incident_date="2025-01-01")  # out of window

    # No window: all three.
    comp_all = await kpis.compute("incident_count", session, project_id=pid)
    assert comp_all.value == Decimal("3")

    # Windowed to March 2026: two.
    comp_win = await kpis.compute(
        "incident_count",
        session,
        project_id=pid,
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
    )
    assert comp_win.value == Decimal("2")


async def test_pending_variation_value(session: AsyncSession) -> None:
    pid = await _seed_project(session)
    await _seed_variation(session, pid, amount="2000", status="submitted")
    await _seed_variation(session, pid, amount="3000", status="draft")
    # Approved variation excluded from "pending".
    await _seed_variation(session, pid, amount="99999", status="approved")

    comp = await kpis.compute("pending_variation_value", session, project_id=pid)
    assert comp.unit == "currency"
    assert comp.value == Decimal("5000")
    assert comp.source_record_count == 2


# ── Portfolio currency-honesty (R4) ────────────────────────────────────────


async def test_pending_variation_portfolio_never_blends(session: AsyncSession) -> None:
    eur_pid = await _seed_project(session, currency="EUR")
    usd_pid = await _seed_project(session, currency="USD")
    await _seed_variation(session, eur_pid, amount="1000", status="submitted", currency="EUR")
    await _seed_variation(session, usd_pid, amount="2000", status="submitted", currency="USD")

    comp = await kpis.compute("pending_variation_value", session, project_id=None)
    by_currency = comp.breakdown.get("by_currency", {})
    # Two distinct currency buckets, never collapsed into one scalar.
    assert comp.breakdown.get("multi_currency") is True
    assert Decimal(by_currency["EUR"]) == Decimal("1000")
    assert Decimal(by_currency["USD"]) == Decimal("2000")


# ── Graceful degradation (R8) ──────────────────────────────────────────────


async def test_empty_project_degrades_to_zero(session: AsyncSession) -> None:
    pid = await _seed_project(session)
    for code in ("risk_open_exposure", "ncr_open_count", "incident_count", "pending_variation_value"):
        comp = await kpis.compute(code, session, project_id=pid)
        assert comp.value == Decimal("0"), code
        assert comp.source_record_count == 0, code


# ── Snapshot orchestrator ──────────────────────────────────────────────────


async def test_snapshot_returns_full_spine_with_banding(session: AsyncSession) -> None:
    pid = await _seed_project(session)
    await _seed_ncr(session, pid, status="identified")
    await _seed_risk(session, pid, impact_cost="10000", severity="critical", mitigation="")

    svc = ProjectControlsService(session)
    snap = await svc.snapshot(project_id=pid)

    # All six domains present, in order.
    domains = [g["domain"] for g in snap["groups"]]
    assert domains == [g["domain"] for g in SPINE]

    # Every KPI tile carries a drill URL scoped to the project.
    for group in snap["groups"]:
        for tile in group["kpis"]:
            assert tile["drill_url"].startswith("/api/v1/project-controls/drill/")
            assert str(pid) in tile["drill_url"]
            assert tile["status"] in ("green", "amber", "red")

    # The high-unmitigated risk should band amber/red and raise an alert.
    risk_group = next(g for g in snap["groups"] if g["domain"] == "risk")
    high = next(t for t in risk_group["kpis"] if t["code"] == "risk_high_unmitigated_count")
    assert high["value"] == "1"
    assert high["status"] in ("amber", "red")
    assert any(a["kpi_code"] == "risk_high_unmitigated_count" for a in snap["alerts"])


async def test_drill_returns_rows_with_deep_links(session: AsyncSession) -> None:
    pid = await _seed_project(session)
    await _seed_ncr(session, pid, status="identified")

    svc = ProjectControlsService(session)
    drill = await svc.drill("ncr_open_count", project_id=pid)
    assert drill["record_count"] == 1
    rec = drill["records"][0]
    assert rec["fields"]["kind"] == "ncr"
    assert rec["deep_link"] is not None
    assert rec["deep_link"].startswith("/ncr?id=")
