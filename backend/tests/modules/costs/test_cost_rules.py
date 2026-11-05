# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Cost item rule set: every rule fires, a valid item passes, and the write points enforce it."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import update

from app.core.validation.engine import ValidationContext
from app.database import async_session_factory
from app.modules.costs.models import CostItem
from app.modules.costs.validators import (
    CostAssemblyMatchesComponentsRule,
    CostCurrencyStatedRule,
    CostMassPricingCompleteRule,
    CostRateInRangeRule,
)
from tests.modules.ncr.conftest import admin_auth, app_instance, client, project_id  # noqa: F401


def _item(**kw: object) -> dict:
    base = {
        "code": "C-1",
        "unit": "m",
        "rate": "82.70",
        "currency": "EUR",
        "mass_per_unit": "",
        "mass_basis": "",
        "components": [],
        "metadata": {},
    }
    base.update(kw)
    return {"cost_items": [base]}


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (CostRateInRangeRule, _item(), _item(rate="1e15")),
    (CostRateInRangeRule, _item(), _item(rate="abc")),
    (CostMassPricingCompleteRule, _item(mass_basis="t", mass_per_unit="44.7"), _item(mass_basis="t")),
    (CostMassPricingCompleteRule, _item(), _item(mass_per_unit="44.7")),
    (CostCurrencyStatedRule, _item(), _item(currency="")),
    (
        CostAssemblyMatchesComponentsRule,
        _item(rate="30", components=[{"cost": "10"}, {"cost": "20"}]),
        _item(rate="45", components=[{"cost": "10"}, {"cost": "20"}]),
    ),
]


@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES)
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert failed[0].element_ref == "C-1"
    assert "estimating." not in failed[0].message
    assert "money." not in failed[0].message


async def test_zero_rate_needs_no_currency_and_mass_priced_item_skips_assembly_check() -> None:
    assert (await _run(CostCurrencyStatedRule(), _item(rate="0", currency="")))[0].passed
    mass = _item(rate="1850", mass_basis="t", mass_per_unit="44.7", components=[{"cost": "5"}])
    assert (await _run(CostAssemblyMatchesComponentsRule(), mass))[0].passed


async def test_batch_reports_each_failing_row() -> None:
    data = {"cost_items": [_item(mass_basis="kg")["cost_items"][0], _item(code="C-2", mass_basis="t")["cost_items"][0]]}
    refs = [r.element_ref for r in await _run(CostMassPricingCompleteRule(), data) if not r.passed]
    assert refs == ["C-1", "C-2"]


async def test_message_follows_locale() -> None:
    de = await _run(CostMassPricingCompleteRule(), _item(mass_basis="t"), locale="de")
    assert "Masse" in de[0].message


def _payload(**kw: object) -> dict:
    base = {"code": f"R-{uuid.uuid4().hex[:8]}", "unit": "m", "rate": 82.7, "currency": "EUR", "source": "manual"}
    base.update(kw)
    return base


async def test_valid_item_is_created_without_findings(client, admin_auth) -> None:  # noqa: F811
    _, header = admin_auth
    resp = await client.post("/api/v1/costs/", json=_payload(), headers=header)
    assert resp.status_code == 201, resp.text
    assert resp.json()["validation_warnings"] == []


async def test_blocking_rule_rejects_api_create_with_its_code(client, admin_auth) -> None:  # noqa: F811
    _, header = admin_auth
    resp = await client.post("/api/v1/costs/", json=_payload(mass_basis="t"), headers=header)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == "costs_rules_failed"
    assert [e["rule_id"] for e in detail["errors"]] == ["costs.mass_pricing_complete"]


async def test_warning_is_reported_and_does_not_block(client, admin_auth) -> None:  # noqa: F811
    _, header = admin_auth
    resp = await client.post("/api/v1/costs/", json=_payload(currency=""), headers=header)
    assert resp.status_code == 201, resp.text
    assert [w["rule_id"] for w in resp.json()["validation_warnings"]] == ["costs.currency_stated"]


async def test_update_that_introduces_an_error_is_rejected_and_not_written(client, admin_auth) -> None:  # noqa: F811
    _, header = admin_auth
    created = (await client.post("/api/v1/costs/", json=_payload(), headers=header)).json()
    resp = await client.patch(f"/api/v1/costs/{created['id']}", json={"mass_basis": "kg"}, headers=header)
    assert resp.status_code == 422
    assert resp.json()["detail"]["errors"][0]["rule_id"] == "costs.mass_pricing_complete"
    assert (await client.get(f"/api/v1/costs/{created['id']}", headers=header)).json()["mass_basis"] == ""


async def test_legacy_item_with_existing_violation_stays_editable(client, admin_auth) -> None:  # noqa: F811
    _, header = admin_auth
    created = (await client.post("/api/v1/costs/", json=_payload(), headers=header)).json()
    async with async_session_factory() as session:
        await session.execute(update(CostItem).where(CostItem.id == uuid.UUID(created["id"])).values(mass_basis="t"))
        await session.commit()
    resp = await client.patch(f"/api/v1/costs/{created['id']}", json={"description": "Renamed"}, headers=header)
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "Renamed"


async def test_bulk_import_rejects_the_batch_on_a_blocking_row(client, admin_auth) -> None:  # noqa: F811
    _, header = admin_auth
    good, bad = _payload(), _payload(mass_basis="kg")
    resp = await client.post("/api/v1/costs/bulk/", json=[good, bad], headers=header)
    assert resp.status_code == 422
    assert resp.json()["detail"]["errors"][0]["element_ref"] == bad["code"]
    ok = await client.post("/api/v1/costs/bulk/", json=[good], headers=header)
    assert ok.status_code == 201, ok.text


async def test_renaming_a_legacy_item_does_not_turn_its_old_violation_into_a_new_one(client, admin_auth) -> None:  # noqa: F811
    _, header = admin_auth
    created = (await client.post("/api/v1/costs/", json=_payload(), headers=header)).json()
    async with async_session_factory() as session:
        await session.execute(update(CostItem).where(CostItem.id == uuid.UUID(created["id"])).values(mass_basis="t"))
        await session.commit()
    new_code = f"R-{uuid.uuid4().hex[:8]}"
    resp = await client.patch(f"/api/v1/costs/{created['id']}", json={"code": new_code}, headers=header)
    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == new_code
