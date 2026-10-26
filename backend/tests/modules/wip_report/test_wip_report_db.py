# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""WIP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ report against a real database, read from contracts, change orders, CVR and invoices.

Each test asks one cross-module question: does the live row read every source at the
right date, does a close freeze a period and compare against the previous one, does
the project manager's forecast win over the cost report, and does the demo seed give
one over-billed, one under-billed and one fading job.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.changeorders.models import ChangeOrder
from app.modules.contracts.models import Contract, ProgressClaim
from app.modules.cvr.models import CvrLine, CvrReport
from app.modules.finance.models import Invoice
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.wip_report.service import WipReportService
from tests._pg import isolated_engine


@pytest.fixture(autouse=True)
def _rules_registered():
    from app.modules.wip_report.validators import register_wip_report_rules

    register_wip_report_rules()


async def _report(session, project, period: str, ctd: str, forecast: str) -> None:
    report = CvrReport(project_id=project.id, period=period, currency="USD", status="final")
    session.add(report)
    await session.flush()
    session.add(
        CvrLine(report_id=report.id, cost_code="01", cost_to_date=Decimal(ctd), forecast_cost=Decimal(forecast))
    )
    await session.flush()


async def _claim(session, contract, number: str, gross: str, period_to: date, status: str = "certified") -> None:
    session.add(
        ProgressClaim(
            contract_id=contract.id,
            claim_number=number,
            gross_amount=Decimal(gross),
            status=status,
            period_to=period_to,
            currency="USD",
        )
    )
    await session.flush()


@pytest_asyncio.fixture
async def ctx():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            owner = User(email=f"o-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", role="admin")
            session.add(owner)
            await session.flush()
            project = Project(name=f"P-{uuid.uuid4().hex[:6]}", owner_id=owner.id, currency="USD")
            session.add(project)
            await session.flush()
            contract = Contract(
                code=f"HC-{uuid.uuid4().hex[:6]}",
                title="Head contract",
                project_id=project.id,
                total_value=Decimal("1000000"),
                currency="USD",
                status="active",
                counterparty_type="client",
            )
            sub = Contract(
                code=f"SC-{uuid.uuid4().hex[:6]}",
                title="Subcontract",
                project_id=project.id,
                total_value=Decimal("300000"),
                currency="USD",
                status="active",
                counterparty_type="subcontractor",
            )
            session.add_all([contract, sub])
            await session.flush()
            yield session, project, contract, sub


@pytest.mark.asyncio
async def test_live_row_reads_every_source_at_its_date(ctx) -> None:
    session, project, contract, sub = ctx
    session.add_all(
        [
            ChangeOrder(
                project_id=project.id,
                code="CO-1",
                title="Extra",
                status="approved",
                cost_impact=Decimal("40000"),
                approved_amount=Decimal("50000"),
                approved_at="2026-08-15T10:00:00+00:00",
            ),
            ChangeOrder(
                project_id=project.id, code="CO-2", title="Pending", status="submitted", cost_impact=Decimal("99999")
            ),
            ChangeOrder(
                project_id=project.id,
                code="CO-3",
                title="Late",
                status="approved",
                cost_impact=Decimal("10000"),
                approved_at="2026-10-02",
            ),
            Invoice(
                project_id=project.id,
                invoice_direction="receivable",
                invoice_number="INV-1",
                invoice_date="2026-09-20",
                amount_subtotal=Decimal("20000"),
                amount_total=Decimal("23800"),
                status="sent",
            ),
            Invoice(
                project_id=project.id,
                invoice_direction="receivable",
                invoice_number="INV-2",
                invoice_date="2026-09-21",
                amount_subtotal=Decimal("5000"),
                status="draft",
            ),
        ]
    )
    await _report(session, project, "2026-08", "300000", "820000")
    await _report(session, project, "2026-09", "420000", "840000")
    await _claim(session, contract, "1", "250000.25", date(2026, 8, 31))
    await _claim(session, contract, "2", "200000", date(2026, 9, 30))
    await _claim(session, contract, "3", "70000", date(2026, 9, 30), status="draft")
    await _claim(session, sub, "S1", "90000", date(2026, 9, 30))

    row = await WipReportService(session).row(project.id, date(2026, 9, 30))
    assert row["contract_value"] == Decimal("1050000.00")
    assert row["approved_changes"] == Decimal("50000.00")
    assert row["cost_to_date"] == Decimal("420000.00") and row["estimated_cost"] == Decimal("840000.00")
    assert row["percent_complete"] == Decimal("50.00")
    assert row["earned_revenue"] == Decimal("525000.00")
    assert row["billed_to_date"] == Decimal("470000.25")
    assert row["under_billing"] == Decimal("54999.75")
    assert row["projected_gross_profit"] == Decimal("210000.00")
    assert row["backlog"] == Decimal("525000.00")

    august = await WipReportService(session).row(project.id, date(2026, 8, 31))
    assert august["cost_to_date"] == Decimal("300000.00")
    assert august["billed_to_date"] == Decimal("250000.25")


@pytest.mark.asyncio
async def test_close_freezes_and_compares_with_previous(ctx) -> None:
    session, project, contract, _ = ctx
    await _report(session, project, "2026-08", "300000", "800000")
    await _claim(session, contract, "1", "450000", date(2026, 8, 31))
    svc = WipReportService(session)
    aug = await svc.close_period(project.id, "2026-08", "u1")
    assert aug.over_billing == Decimal("75000.0000") and aug.fade is None

    with pytest.raises(HTTPException) as exc:
        await svc.close_period(project.id, "2026-08")
    assert exc.value.status_code == 409

    await svc.set_forecast(project.id, Decimal("900000"), "Overrun", "u1")
    await _report(session, project, "2026-09", "450000", "800000")
    sep = await svc.close_period(project.id, "2026-09")
    assert sep.estimated_cost == Decimal("900000.0000")
    assert sep.previous_gross_profit == Decimal("200000.0000")
    assert sep.fade == Decimal("-100000.0000")
    found = {f["rule_id"] for f in await svc.findings(project.id, date(2026, 10, 31))}
    assert "wip_report.large_fade" in found

    with pytest.raises(HTTPException):
        await svc.reopen_period(project.id, "2026-08")
    await svc.reopen_period(project.id, "2026-09")
    assert [p.period for p in await svc.list_periods(project.id)] == ["2026-08"]
    await svc.set_forecast(project.id, None, None, "u1")
    assert await svc.forecast(project.id) is None


@pytest.mark.asyncio
async def test_portfolio_scopes_and_totals(ctx) -> None:
    session, project, contract, _ = ctx
    await _report(session, project, "2026-09", "100000", "800000")
    svc = WipReportService(session)
    data = await svc.portfolio({project.id}, date(2026, 9, 30))
    assert [r["project_id"] for r in data["rows"]] == [project.id]
    assert data["totals"][0]["currency"] == "USD"
    assert (await svc.portfolio({uuid.uuid4()}, date(2026, 9, 30)))["rows"] == []


@pytest.mark.asyncio
async def test_demo_seed_shapes_over_under_and_fade(ctx) -> None:
    from app.modules.wip_report.demo import seed_wip_report_demo

    session, first, contract, _ = ctx
    first.metadata_ = {"demo_id": "wip-a"}
    projects = [first]
    for i in range(2):
        p = Project(
            name=f"Q{i}-{uuid.uuid4().hex[:6]}",
            owner_id=first.owner_id,
            currency="USD",
            metadata_={"demo_id": f"wip-{i}"},
        )
        session.add(p)
        await session.flush()
        c = Contract(
            code=f"HC{i}-{uuid.uuid4().hex[:6]}",
            title="Head",
            project_id=p.id,
            total_value=Decimal("1000000"),
            currency="USD",
            status="active",
        )
        session.add(c)
        await session.flush()
        projects.append(p)
        contract_i = c
        for m in ("2026-07", "2026-08", "2026-09"):
            await _report(session, p, m, "400000", "800000")
        await _claim(session, contract_i, "1", "450000", date(2026, 7, 31))
    for m in ("2026-07", "2026-08", "2026-09"):
        await _report(session, first, m, "400000", "800000")
    await _claim(session, contract, "1", "450000", date(2026, 7, 31))
    session.add(first)
    await session.flush()

    totals = await seed_wip_report_demo(session, [p.id for p in projects], today=date(2026, 10, 26))
    assert totals == {"projects": 3, "periods": 9}
    svc = WipReportService(session)
    lasts = [(await svc.list_periods(p.id))[0] for p in sorted(projects, key=lambda p: p.name)]
    assert sum(1 for s in lasts if s.over_billing > 0) >= 1
    assert sum(1 for s in lasts if s.under_billing > 0) >= 1
    assert any(s.fade is not None and s.fade < 0 for s in lasts)
    again = await seed_wip_report_demo(session, [p.id for p in projects], today=date(2026, 10, 26))
    assert again["periods"] == 0
