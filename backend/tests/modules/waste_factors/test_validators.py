# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Waste factor rules: each rule firing, a valid record passing, the API refusing a blocking one."""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.waste_factors.models import WasteFactor
from app.modules.waste_factors.permissions import register_waste_factors_permissions
from app.modules.waste_factors.router import router as waste_router
from app.modules.waste_factors.validators import (
    WASTE_FACTORS_RULE_SET,
    CategoryCaseVariantRule,
    FactorPlausibleRule,
    UniqueCategoryRule,
    register_waste_factors_validation_rules,
)
from tests.modules._api_support import api_client


def _data(**kw: object) -> dict:
    base: dict = {"factor": {"id": "f1", "category": "Concrete", "factor": "1.05", "tenant_id": ""}, "siblings": []}
    base.update(kw)
    return base


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (UniqueCategoryRule, _data(), _data(siblings=[{"id": "f2", "category": " Concrete", "tenant_id": ""}])),
    (CategoryCaseVariantRule, _data(), _data(siblings=[{"id": "f2", "category": "concrete", "tenant_id": ""}])),
    (FactorPlausibleRule, _data(), _data(factor={"id": "f1", "category": "Concrete", "factor": "1.9"})),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES)
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "waste_factors." not in failed[0].message
    assert failed[0].suggestion and "waste_factors." not in failed[0].suggestion


@pytest.mark.asyncio
async def test_other_tenant_scope_is_not_a_duplicate() -> None:
    other = _data(siblings=[{"id": "f2", "category": "Concrete", "tenant_id": "t-1"}])
    assert all(r.passed for r in await _run(UniqueCategoryRule(), other))


@pytest.mark.asyncio
async def test_empty_context_passes_every_rule() -> None:
    for rule_cls, _, _ in CASES:
        assert all(r.passed for r in await _run(rule_cls(), {}))


@pytest.mark.asyncio
async def test_message_follows_locale() -> None:
    bad = _data(factor={"id": "f1", "category": "Concrete", "factor": "1.9"})
    de = (await _run(FactorPlausibleRule(), bad, locale="de"))[0]
    assert "Concrete" in de.message
    assert "Verschnitt" in de.message


def test_registered_under_rule_set() -> None:
    register_waste_factors_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([WASTE_FACTORS_RULE_SET])}
    assert ids == {
        "waste_factors.unique_category",
        "waste_factors.category_case_variant",
        "waste_factors.factor_plausible",
    }


# ── API on real PostgreSQL ───────────────────────────────────────────────────


@pytest_asyncio.fixture
async def ctx():
    async with api_client(
        waste_router, "/v1/waste-factors", register_waste_factors_permissions, register_waste_factors_validation_rules
    ) as (client, session, _user):
        yield client, session


@pytest.mark.asyncio
async def test_api_blocks_duplicate_category_with_code(ctx) -> None:
    client, _ = ctx
    first = await client.post("/v1/waste-factors/factors/", json={"category": "Brick", "factor": "1.05"})
    assert first.status_code == 201, first.text
    assert first.json()["warnings"] == []
    dup = await client.post("/v1/waste-factors/factors/", json={"category": " Brick", "factor": "1.07"})
    assert dup.status_code == 422, dup.text
    assert dup.json()["detail"]["code"] == "waste_factors.unique_category"
    assert dup.json()["detail"]["error"] == "waste_factors_rules_failed"


@pytest.mark.asyncio
async def test_api_warns_on_case_variant_and_high_factor(ctx) -> None:
    client, _ = ctx
    await client.post("/v1/waste-factors/factors/", json={"category": "Tile", "factor": "1.10"})
    r = await client.post("/v1/waste-factors/factors/", json={"category": "tile", "factor": "1.8"})
    assert r.status_code == 201, r.text
    assert {w["rule_id"] for w in r.json()["warnings"]} == {
        "waste_factors.category_case_variant",
        "waste_factors.factor_plausible",
    }


@pytest.mark.asyncio
async def test_api_update_blocks_new_duplicate_but_legacy_duplicate_stays_editable(ctx) -> None:
    client, session = ctx
    a = WasteFactor(category="Steel", label="a", factor=Decimal("1.03"))
    b = WasteFactor(category="Steel", label="b", factor=Decimal("1.04"))
    session.add_all([a, b])
    await session.flush()

    ok = await client.patch(f"/v1/waste-factors/factors/{a.id}", json={"factor": "1.06"})
    assert ok.status_code == 200, ok.text

    other = await client.post("/v1/waste-factors/factors/", json={"category": "Timber", "factor": "1.1"})
    r = await client.patch(f"/v1/waste-factors/factors/{other.json()['id']}", json={"category": "Steel"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "waste_factors.unique_category"
