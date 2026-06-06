"""Project Controls connectivity tests (CONN-77 / CONN-78).

Two gaps the connectivity audit flagged on the executive spine:

    * CONN-77 - four spine tiles (first_pass_yield, copq, rfi_close_avg_days,
      change_order_ratio) had no registered drill-down provider, so their
      drawer opened empty (dead end). Each now returns the underlying rows,
      deep-linked back to the owning module.
    * CONN-78 - the cost baseline (BAC) ignored the priced BOQ estimate. When
      a project has no budget / contract value the snapshot now falls back to
      the sum of its BOQ position totals and records ``baseline_source=boq``
      so the UI can offer a "View BOQ baseline" drill.

Run against a real PostgreSQL session in a rolled-back transaction.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bi_dashboards import kpis
from app.modules.project_controls.service import ProjectControlsService
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
    budget: Decimal | None = None,
    contract_value: Decimal | None = None,
    fx_rates: list | None = None,
) -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"conn-{uuid.uuid4().hex[:10]}@controls.io",
        hashed_password="x",
        full_name="Controls Owner",
        role="admin",
    )
    session.add(owner)
    await session.flush()
    # NB: the Project model has no ``budget`` column (the EVM snapshot reads
    # it defensively via getattr and falls back); the persisted budget field
    # is ``contract_value``. ``budget`` here maps onto it for the precedence
    # test so we exercise a real, settable baseline source.
    kwargs: dict = {}
    cv = contract_value if contract_value is not None else budget
    if cv is not None:
        kwargs["contract_value"] = str(cv)
    project = Project(
        id=uuid.uuid4(),
        name="Conn project",
        owner_id=owner.id,
        currency=currency,
        fx_rates=fx_rates or [],
        **kwargs,
    )
    session.add(project)
    await session.flush()
    return project.id


async def _seed_inspection(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    result: str | None = None,
    status: str = "scheduled",
) -> None:
    from app.modules.inspections.models import QualityInspection

    session.add(
        QualityInspection(
            project_id=project_id,
            inspection_number=f"QI-{uuid.uuid4().hex[:5]}",
            inspection_type="structural",
            title="Slab pour",
            status=status,
            result=result,
        )
    )
    await session.flush()


async def _seed_ncr(session: AsyncSession, project_id: uuid.UUID, *, cost_impact: str) -> None:
    from app.modules.ncr.models import NCR

    session.add(
        NCR(
            project_id=project_id,
            ncr_number=f"NCR-{uuid.uuid4().hex[:5]}",
            title="Defect",
            description="x",
            ncr_type="material",
            severity="major",
            status="identified",
            cost_impact=cost_impact,
        )
    )
    await session.flush()


async def _seed_rfi(session: AsyncSession, project_id: uuid.UUID) -> None:
    from app.modules.rfi.models import RFI

    session.add(
        RFI(
            project_id=project_id,
            rfi_number=f"RFI-{uuid.uuid4().hex[:5]}",
            subject="Beam clash",
            question="Which detail governs?",
            raised_by=uuid.uuid4(),
            status="open",
        )
    )
    await session.flush()


async def _seed_change_order(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    cost_impact: str,
    currency: str = "EUR",
) -> None:
    from app.modules.changeorders.models import ChangeOrder

    session.add(
        ChangeOrder(
            project_id=project_id,
            code=f"CO-{uuid.uuid4().hex[:5]}",
            title="Added scope",
            status="submitted",
            cost_impact=Decimal(cost_impact),
            currency=currency,
        )
    )
    await session.flush()


async def _seed_boq_position(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    total: str,
    currency: str | None = None,
) -> None:
    from app.modules.boq.models import BOQ, Position

    boq = BOQ(project_id=project_id, name="Estimate")
    session.add(boq)
    await session.flush()
    meta = {"currency": currency} if currency else {}
    session.add(
        Position(
            boq_id=boq.id,
            ordinal="01.001",
            description="Concrete C30/37",
            unit="m3",
            quantity="10",
            unit_rate="100",
            total=total,
            metadata_=meta,
        )
    )
    await session.flush()


# ── CONN-77: the four previously dead drill tiles ───────────────────────────


async def test_first_pass_yield_drill_returns_inspections(session: AsyncSession) -> None:
    pid = await _seed_project(session)
    await _seed_inspection(session, pid, result="passed")
    await _seed_inspection(session, pid, result="failed")

    rows = await kpis.drilldown("first_pass_yield", session, project_id=pid)
    assert len(rows) == 2
    assert {r["kind"] for r in rows} == {"inspection"}

    svc = ProjectControlsService(session)
    drill = await svc.drill("first_pass_yield", project_id=pid)
    assert drill["record_count"] == 2
    assert drill["records"][0]["deep_link"].startswith("/inspections?id=")


async def test_first_pass_yield_kpi_counts_inspections(session: AsyncSession) -> None:
    # Regression: the formula previously imported a non-existent ``Inspection``
    # class and silently degraded to 0/no-data. It must now read real rows.
    pid = await _seed_project(session)
    await _seed_inspection(session, pid, result="passed")
    await _seed_inspection(session, pid, result="passed")
    await _seed_inspection(session, pid, result="failed")

    comp = await kpis.compute("first_pass_yield", session, project_id=pid)
    assert comp.source_record_count == 3
    # 2 of 3 passed -> 66.66…%
    assert comp.value > Decimal("66") and comp.value < Decimal("67")


async def test_copq_drill_returns_ncrs(session: AsyncSession) -> None:
    pid = await _seed_project(session)
    await _seed_ncr(session, pid, cost_impact="1500")

    svc = ProjectControlsService(session)
    drill = await svc.drill("copq", project_id=pid)
    assert drill["record_count"] == 1
    rec = drill["records"][0]
    assert rec["fields"]["kind"] == "ncr"
    assert rec["deep_link"].startswith("/ncr?id=")


async def test_rfi_close_avg_days_drill_returns_rfis(session: AsyncSession) -> None:
    pid = await _seed_project(session)
    await _seed_rfi(session, pid)

    svc = ProjectControlsService(session)
    drill = await svc.drill("rfi_close_avg_days", project_id=pid)
    assert drill["record_count"] == 1
    rec = drill["records"][0]
    assert rec["fields"]["kind"] == "rfi"
    assert rec["deep_link"].startswith("/rfi/")


async def test_change_order_ratio_drill_returns_change_orders(session: AsyncSession) -> None:
    pid = await _seed_project(session)
    await _seed_change_order(session, pid, cost_impact="25000")

    rows = await kpis.drilldown("change_order_ratio", session, project_id=pid)
    assert len(rows) == 1
    assert rows[0]["kind"] == "change_order"
    assert Decimal(rows[0]["cost_impact"]) == Decimal("25000")

    svc = ProjectControlsService(session)
    drill = await svc.drill("change_order_ratio", project_id=pid)
    assert drill["records"][0]["deep_link"].startswith("/changeorders?id=")


# ── CONN-78: BOQ cost baseline fallback ──────────────────────────────────────


async def test_bac_falls_back_to_boq_total(session: AsyncSession) -> None:
    # No budget / contract value -> BAC is the priced BOQ estimate.
    pid = await _seed_project(session)
    await _seed_boq_position(session, pid, total="40000")
    await _seed_boq_position(session, pid, total="10000")

    snap = await kpis._evm_snapshot_for_project(session, pid)
    assert snap.bac == Decimal("50000")
    assert snap.breakdown["baseline_source"] == "boq"


async def test_bac_prefers_project_budget_over_boq(session: AsyncSession) -> None:
    pid = await _seed_project(session, budget=Decimal("90000"))
    await _seed_boq_position(session, pid, total="40000")

    snap = await kpis._evm_snapshot_for_project(session, pid)
    assert snap.bac == Decimal("90000")
    assert snap.breakdown["baseline_source"] == "budget"


async def test_bac_boq_baseline_converts_foreign_currency(session: AsyncSession) -> None:
    # Project base EUR, one position priced in USD at 0.9 EUR/USD.
    pid = await _seed_project(
        session,
        currency="EUR",
        fx_rates=[{"code": "USD", "rate": "0.9"}],
    )
    await _seed_boq_position(session, pid, total="1000", currency="USD")

    snap = await kpis._evm_snapshot_for_project(session, pid)
    assert snap.bac == Decimal("900.0")
    assert snap.breakdown["baseline_source"] == "boq"


async def test_bac_no_baseline_at_all(session: AsyncSession) -> None:
    pid = await _seed_project(session)
    snap = await kpis._evm_snapshot_for_project(session, pid)
    assert snap.bac == Decimal("0")
    assert snap.breakdown["baseline_source"] == ""
