# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Labor rate rules: each rule firing, a valid record passing, and the API refusing a blocking one."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.core.audit_log  # noqa: F401 - registers ActivityLog with Base
from app.core.validation.engine import ValidationContext, rule_registry
from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.labor_rates.permissions import register_labor_rates_permissions
from app.modules.labor_rates.router import router as labor_router
from app.modules.labor_rates.validators import (
    LABOR_RATES_RULE_SET,
    BurdenPlausibleRule,
    CrewRatesInRangeRule,
    DuplicateLinesRule,
    LaborCurrencyRule,
    OnCostInRangeRule,
    register_labor_rates_validation_rules,
)
from app.modules.users.models import User
from tests._pg import transactional_session


def _data(**kw: object) -> dict:
    base: dict = {
        "template": {"id": "t1", "name": "Mason", "base_wage": "20", "currency": "EUR"},
        "components": [
            {"label": "Social charges", "kind": "percentage", "value": "21"},
            {"label": "Holiday pay", "kind": "percentage", "value": "12"},
            {"label": "Tools", "kind": "fixed", "value": "1.5"},
        ],
        "crew": {"id": "c1", "currency": "EUR", "members": [{"trade": "Mason", "count": 2, "all_in_rate": "32"}]},
    }
    base.update(kw)
    return base


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (OnCostInRangeRule, _data(), _data(components=[{"label": "Social", "kind": "percentage", "value": "3000"}])),
    (OnCostInRangeRule, _data(), _data(components=[{"label": "Bonus", "kind": "fixed", "value": "-2"}])),
    (
        CrewRatesInRangeRule,
        _data(),
        _data(crew={"id": "c1", "currency": "EUR", "members": [{"trade": "Mason", "count": 1, "all_in_rate": "-5"}]}),
    ),
    (
        BurdenPlausibleRule,
        _data(),
        _data(
            components=[
                {"label": "A", "kind": "percentage", "value": "90"},
                {"label": "B", "kind": "percentage", "value": "80"},
            ]
        ),
    ),
    (LaborCurrencyRule, _data(), _data(template={"id": "t1", "base_wage": "20", "currency": ""})),
    (
        DuplicateLinesRule,
        _data(),
        _data(
            components=[
                {"label": "Social", "kind": "percentage", "value": "5"},
                {"label": " social ", "kind": "percentage", "value": "6"},
            ]
        ),
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES)
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "cost_rules." not in failed[0].message  # translated, not a raw key


@pytest.mark.asyncio
async def test_drafts_and_partial_records_pass() -> None:
    for rule_cls, _, _ in CASES:
        assert all(r.passed for r in await _run(rule_cls(), {}))
        assert all(r.passed for r in await _run(rule_cls(), {"template": {"name": "Draft", "base_wage": "0"}}))
    # a crew with no priced line needs no currency
    crew = {"crew": {"id": "c", "currency": "", "members": [{"trade": "Mason", "count": 1, "all_in_rate": "0"}]}}
    assert all(r.passed for r in await _run(LaborCurrencyRule(), crew))


@pytest.mark.asyncio
async def test_burden_message_follows_locale_and_names_numbers() -> None:
    bad = _data(components=[{"label": "A", "kind": "percentage", "value": "200"}])
    de = (await _run(BurdenPlausibleRule(), bad, locale="de"))[0]
    assert "200" in de.message
    assert "Grundlohn" in de.message


def test_registered_under_rule_set() -> None:
    register_labor_rates_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([LABOR_RATES_RULE_SET])}
    assert {"labor_rates.oncost_in_range", "labor_rates.duplicate_lines"} <= ids
    assert len(ids) == 5


# ── API on real PostgreSQL ───────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    register_labor_rates_permissions()
    register_labor_rates_validation_rules()
    async with transactional_session() as session:
        user = User(email=f"lr-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", role="admin")
        session.add(user)
        await session.flush()
        await session.commit()
        app = FastAPI()
        app.include_router(labor_router, prefix="/v1/labor-rates")

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
            yield c


@pytest.mark.asyncio
async def test_api_blocks_out_of_range_oncost_with_code(client: AsyncClient) -> None:
    body = {
        "name": "Mason",
        "base_wage": "20",
        "currency": "EUR",
        "components": [{"label": "Social", "kind": "percentage", "value": "3000"}],
    }
    r = await client.post("/v1/labor-rates/templates/", json=body)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "labor_rates.oncost_in_range"
    assert detail["error"] == "labor_rates_rules_failed"


@pytest.mark.asyncio
async def test_api_valid_template_saves_and_reports_warnings(client: AsyncClient) -> None:
    ok = {
        "name": "Mason",
        "base_wage": "20",
        "currency": "EUR",
        "components": [{"label": "Social", "kind": "percentage", "value": "33"}],
    }
    r = await client.post("/v1/labor-rates/templates/", json=ok)
    assert r.status_code == 201, r.text
    assert r.json()["warnings"] == []

    heavy = {
        **ok,
        "name": "Heavy",
        "currency": "",
        "components": [{"label": "Load", "kind": "percentage", "value": "200"}],
    }
    r = await client.post("/v1/labor-rates/templates/", json=heavy)
    assert r.status_code == 201, r.text
    assert {w["rule_id"] for w in r.json()["warnings"]} == {
        "labor_rates.burden_plausible",
        "labor_rates.currency_stated",
    }


@pytest.mark.asyncio
async def test_api_blocks_negative_crew_rate_and_update_keeps_rules(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/labor-rates/crews/",
        json={"currency": "EUR", "members": [{"trade": "Mason", "count": 1, "all_in_rate": "-4"}]},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "labor_rates.crew_rate_in_range"

    created = await client.post(
        "/v1/labor-rates/templates/", json={"name": "T", "base_wage": "20", "currency": "EUR", "components": []}
    )
    tid = created.json()["id"]
    r = await client.patch(
        f"/v1/labor-rates/templates/{tid}",
        json={"components": [{"label": "Bad", "kind": "fixed", "value": "-1"}]},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "labor_rates.oncost_in_range"
