"""Project intelligence rules: each rule firing, a clean forecast passing, and the forecast endpoint reporting findings."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.core.audit_log  # noqa: F401 - registers ActivityLog with Base
from app.core.validation.engine import ValidationContext, rule_registry
from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.finance.models import EVMSnapshot
from app.modules.project_intelligence.forecast import (
    CostOverrunRisk,
    ProjectForecast,
    ScheduleSlip,
    compute_cost_forecast,
)
from app.modules.project_intelligence.permissions import register_project_intelligence_permissions
from app.modules.project_intelligence.router import router as pi_router
from app.modules.project_intelligence.service import check_forecast
from app.modules.project_intelligence.validators import (
    PROJECT_INTELLIGENCE_RULE_SET,
    CurrencyStatedRule,
    EarnedWithinBudgetRule,
    EvmArithmeticRule,
    EvmInputsSaneRule,
    PerformanceIndexRule,
    RiskScoreRule,
    ScheduleProgressRule,
    register_project_intelligence_validation_rules,
)
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


def _data(**cost: object) -> dict:
    """Worked example: BAC 1000, EV 400, AC 500, PV 450 -> CPI 0.8, EAC 1250, ETC 750, VAC -250."""
    return {
        "forecast": {
            "project_id": "p1",
            "currency": "EUR",
            "cost": {
                "available": True,
                "currency": "EUR",
                "bac": "1000.00",
                "ev": "400.00",
                "ac": "500.00",
                "pv": "450.00",
                "cpi": 0.8,
                "spi": 0.8889,
                "eac": "1250.00",
                "etc": "750.00",
                "vac": "-250.00",
                **cost,
            },
            "schedule": {
                "available": True,
                "planned_pct_complete": 45.0,
                "actual_pct_complete": 40.0,
                "finish_variance_days": 12,
            },
            "risk": {"score": 0.55, "confidence": 0.8},
        }
    }


def _with(section: str, **fields: object) -> dict:
    data = _data()
    data["forecast"][section] = {**data["forecast"][section], **fields}
    return data


def _no_currency() -> dict:
    data = _data(currency="")
    data["forecast"]["currency"] = ""
    return data


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (EvmArithmeticRule, _data(), _data(etc="900.00")),
    (EvmArithmeticRule, _data(), _data(vac="250.00")),
    (CurrencyStatedRule, _data(), _no_currency()),
    (EvmInputsSaneRule, _data(), _data(ac="-5.00")),
    (EvmInputsSaneRule, _data(), _data(bac="5e15")),
    (EarnedWithinBudgetRule, _data(), _data(ev="1200.00")),
    (PerformanceIndexRule, _data(), _data(cpi=40.0)),
    (RiskScoreRule, _data(), _with("risk", score=1.4)),
    (RiskScoreRule, _data(), _with("risk", confidence=-0.1)),
    (ScheduleProgressRule, _data(), _with("schedule", actual_pct_complete=140.0)),
    (ScheduleProgressRule, _data(), _with("schedule", finish_variance_days=9000)),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES)
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "money." not in failed[0].message


@pytest.mark.asyncio
async def test_unavailable_sections_and_empty_payload_pass_every_rule() -> None:
    off = {
        "forecast": {
            "currency": "",
            "cost": {"available": False, "reason": "no_evm_snapshot"},
            "schedule": {"available": False},
            "risk": {},
        }
    }
    for rule_cls, _, _ in CASES:
        assert all(r.passed for r in await _run(rule_cls(), off)), rule_cls.__name__
        assert all(r.passed for r in await _run(rule_cls(), {})), rule_cls.__name__


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("currency", "bac", "ev", "ac", "pv"),
    [
        ("EUR", "1000", "400", "500", "450"),
        ("JPY", "1234567", "400111", "500333", "450777"),
        ("KWD", "999.999", "123.457", "321.001", "200"),
    ],
)
async def test_every_computed_forecast_ties_in_its_currency(currency, bac, ev, ac, pv) -> None:
    cost = compute_cost_forecast(bac=Decimal(bac), ev=Decimal(ev), ac=Decimal(ac), pv=Decimal(pv), currency=currency)
    data = {"forecast": {"currency": currency, "cost": cost.__dict__}}
    assert all(r.passed for r in await _run(EvmArithmeticRule(), data))


def _forecast(ev: str, currency: str = "EUR") -> ProjectForecast:
    return ProjectForecast(
        project_id="p1",
        currency=currency,
        cost=compute_cost_forecast(
            bac=Decimal("1000"), ev=Decimal(ev), ac=Decimal("500"), pv=Decimal("450"), currency=currency
        ),
        schedule=ScheduleSlip(),
        risk=CostOverrunRisk(score=0.2, confidence=0.5, rationale=["x"]),
    )


@pytest.mark.asyncio
async def test_check_forecast_reports_warnings_and_errors() -> None:
    register_project_intelligence_validation_rules()
    forecast = _forecast("1200")
    findings = await check_forecast(forecast)
    assert {f["rule_id"] for f in findings} == {"project_intelligence.earned_within_budget"}
    assert findings[0]["severity"] == "warning"
    broken = replace(forecast, risk=CostOverrunRisk(score=3.0, confidence=0.5, rationale=["x"]))
    assert "project_intelligence.risk_score_bounded" in {f["rule_id"] for f in await check_forecast(broken)}
    assert await check_forecast(_forecast("400")) == []


@pytest.mark.asyncio
async def test_message_follows_locale() -> None:
    en = (await _run(RiskScoreRule(), _with("risk", score=1.4), "en"))[0]
    de = (await _run(RiskScoreRule(), _with("risk", score=1.4), "de"))[0]
    assert en.message != de.message
    assert "1.4" in de.message


def test_registered_under_rule_set() -> None:
    register_project_intelligence_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([PROJECT_INTELLIGENCE_RULE_SET])}
    assert "project_intelligence.evm_ties" in ids
    assert len(ids) == 7


# ── API on real PostgreSQL ───────────────────────────────────────────────────


@pytest_asyncio.fixture
async def ctx() -> AsyncIterator[tuple[AsyncClient, object, User]]:
    register_project_intelligence_permissions()
    register_project_intelligence_validation_rules()
    async with transactional_session() as session:
        user = User(email=f"pi-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", role="admin")
        session.add(user)
        await session.flush()
        await session.commit()
        app = FastAPI()
        app.include_router(pi_router, prefix="/v1/pi")

        async def _session():
            yield session

        app.dependency_overrides[get_session] = _session
        app.dependency_overrides[get_current_user_id] = lambda: str(user.id)
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": str(user.id),
            "role": "admin",
            "permissions": [],
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c, session, user


async def _project(session, user: User, *, currency: str, ev: str | None) -> uuid.UUID:
    project = Project(name="PI test", owner_id=user.id, currency=currency)
    session.add(project)
    await session.flush()
    if ev is not None:
        session.add(
            EVMSnapshot(project_id=project.id, snapshot_date="2026-11-01", bac="1000", pv="450", ev=ev, ac="500")
        )
    await session.flush()
    await session.commit()
    return project.id


@pytest.mark.asyncio
async def test_api_forecast_without_snapshot_has_no_findings(ctx) -> None:
    c, session, user = ctx
    pid = await _project(session, user, currency="EUR", ev=None)
    r = await c.get(f"/v1/pi/{pid}/forecast")
    assert r.status_code == 200, r.text
    assert r.json()["cost"]["available"] is False
    assert r.json()["findings"] == []


@pytest.mark.asyncio
async def test_api_clean_forecast_has_no_findings(ctx) -> None:
    c, session, user = ctx
    pid = await _project(session, user, currency="EUR", ev="400")
    r = await c.get(f"/v1/pi/{pid}/forecast")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cost"]["eac"] == "1250.00"
    assert body["findings"] == []


@pytest.mark.asyncio
async def test_api_reports_earned_above_budget_and_missing_currency(ctx) -> None:
    c, session, user = ctx
    pid = await _project(session, user, currency="", ev="1200")
    r = await c.get(f"/v1/pi/{pid}/forecast")
    assert r.status_code == 200, r.text
    ids = {f["rule_id"] for f in r.json()["findings"]}
    assert {"project_intelligence.earned_within_budget", "project_intelligence.currency_stated"} <= ids
