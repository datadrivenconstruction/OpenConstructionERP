# DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The cash-flow forecast reads the project's own records and finds the funding peak.

Two demo projects get the cash-flow demo rows: a back-loaded payment plan on
the first, an even one on the second (in another currency). The first goes
negative between the first and last month and recovers; the portfolio keeps the
two currencies apart; the rules report the funding gap and the overdue client
invoice; a project with nothing to forecast from is named.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.costmodel.cashflow_forecast import Scenario
from app.modules.costmodel.cashflow_forecast_demo import seed_cashflow_forecast_demo
from app.modules.costmodel.cashflow_forecast_rules import register_cashflow_forecast_rules
from app.modules.costmodel.cashflow_forecast_service import CashFlowForecastService, project_workbook
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()
TODAY = date(2026, 10, 15)


@pytest_asyncio.fixture
async def session():
    register_cashflow_forecast_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"cashflow-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _project(session, name: str, currency: str) -> Project:
    project = Project(id=uuid.uuid4(), name=name, owner_id=OWNER_ID, currency=currency, status="active")
    session.add(project)
    await session.flush()
    return project


async def test_the_back_loaded_project_dips_and_recovers(session) -> None:
    dip = await _project(session, "Dip works", "EUR")
    even = await _project(session, "Even works", "USD")
    idle = await _project(session, "Idle works", "EUR")
    assert await seed_cashflow_forecast_demo(session, dip.id, dip=True, today=TODAY) > 0
    assert await seed_cashflow_forecast_demo(session, even.id, dip=False, today=TODAY) > 0
    assert await seed_cashflow_forecast_demo(session, dip.id, dip=True, today=TODAY) == 0

    service = CashFlowForecastService(session, today=TODAY)
    forecast = await service.project(dip.id, Scenario())
    assert forecast is not None and forecast.has_inputs
    (eur,) = forecast.currencies
    periods = [m.period for m in eur.months]
    assert eur.peak_funding is not None
    assert periods[0] < eur.peak_funding.period < periods[-1]
    assert Decimal(eur.peak_funding.amount) > 0
    assert Decimal(eur.closing_position) > 0
    past = [m for m in eur.months if m.is_past and Decimal(m.actual_in) > 0]
    assert len(past) >= 2
    sources = {(s.source, s.direction) for s in eur.sources}
    assert {
        ("milestone", "in"),
        ("retention_release", "in"),
        ("subcontract", "out"),
        ("purchase_order", "out"),
    } <= sources
    rules = {f.rule_id for f in forecast.findings}
    assert "cashflow_forecast.negative_position" in rules
    assert "cashflow_forecast.receipt_overdue" in rules

    worse = await service.project(dip.id, Scenario(receipt_delay_days=60, cost_overrun_pct=Decimal("10")))
    assert worse is not None
    assert Decimal(worse.currencies[0].peak_funding.amount) > Decimal(eur.peak_funding.amount)

    loose = await service.project(dip.id, Scenario(), threshold=Decimal("100000000"))
    assert "cashflow_forecast.negative_position" not in {f.rule_id for f in loose.findings}

    portfolio = await service.portfolio([dip.id, even.id, idle.id], Scenario())
    assert [c.currency for c in portfolio.currencies] == ["EUR", "USD"]
    eur_rows = {p.project_name for p in portfolio.currencies[0].projects}
    assert eur_rows == {"Dip works"}
    assert [p.project_name for p in portfolio.projects_without_forecast] == ["Idle works"]

    missing = await service.project(idle.id, Scenario())
    assert {f.rule_id for f in missing.findings} == {"cashflow_forecast.forecast_missing"}

    assert project_workbook(forecast, "en")[:2] == b"PK"
