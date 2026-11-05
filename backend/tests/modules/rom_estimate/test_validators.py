# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""ROM estimate rules: each rule firing, a valid record passing, the API refusing a blocking one."""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.rom_estimate.permissions import register_rom_estimate_permissions
from app.modules.rom_estimate.router import router as rom_router
from app.modules.rom_estimate.validators import (
    ROM_ESTIMATE_RULE_SET,
    BaselineReplacedRule,
    ConceptBoqBesideDetailedRule,
    CurrencyStatedRule,
    GrossFloorAreaRule,
    RegionSetRule,
    register_rom_estimate_validation_rules,
)
from tests.modules._api_support import api_client, make_project


def _data(estimate: dict | None = None, project: dict | None = None) -> dict:
    est = {"id": "e1", "gfa_m2": "5000", "currency": "EUR", "localized": True, "operation": "save"}
    est.update(estimate or {})
    return {"estimate": est, "project": {"saved_estimates": 0, "boqs": 0, **(project or {})}}


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (GrossFloorAreaRule, _data(), _data({"gfa_m2": "50000000"})),
    (GrossFloorAreaRule, _data(), _data({"gfa_m2": "0.2"})),
    (CurrencyStatedRule, _data(), _data({"currency": ""})),
    (RegionSetRule, _data(), _data({"localized": False})),
    (BaselineReplacedRule, _data(), _data(project={"saved_estimates": 2})),
    (ConceptBoqBesideDetailedRule, _data(), _data({"operation": "create_boq"}, {"boqs": 1})),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES)
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "rom_estimate." not in failed[0].message
    assert failed[0].suggestion and "rom_estimate." not in failed[0].suggestion


@pytest.mark.asyncio
async def test_boq_beside_detailed_only_when_seeding_a_bill() -> None:
    plain_save = _data(project={"boqs": 3})
    assert all(r.passed for r in await _run(ConceptBoqBesideDetailedRule(), plain_save))


@pytest.mark.asyncio
async def test_empty_context_passes_every_rule() -> None:
    for rule_cls, _, _ in CASES:
        assert all(r.passed for r in await _run(rule_cls(), {}))


@pytest.mark.asyncio
async def test_message_follows_locale() -> None:
    de = (await _run(RegionSetRule(), _data({"localized": False}), locale="de"))[0]
    assert "Region" in de.message and "Regionalfaktor" in de.message


def test_registered_under_rule_set() -> None:
    register_rom_estimate_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([ROM_ESTIMATE_RULE_SET])}
    assert ids == {
        "rom_estimate.area_in_range",
        "rom_estimate.currency_stated",
        "rom_estimate.region_set",
        "rom_estimate.baseline_replaced",
        "rom_estimate.boq_beside_detailed",
    }


# ── API on real PostgreSQL ───────────────────────────────────────────────────


@pytest_asyncio.fixture
async def ctx():
    async with api_client(
        rom_router, "/v1/rom-estimate", register_rom_estimate_permissions, register_rom_estimate_validation_rules
    ) as (client, session, user):
        yield client, await make_project(session, user)


def _body(**kw: object) -> dict:
    body = {"building_type": "office", "gross_floor_area": "5000", "currency": "EUR", "region": "global"}
    body.update(kw)
    return body


@pytest.mark.asyncio
async def test_api_blocks_unit_slip_area_with_code(ctx) -> None:
    client, pid = ctx
    r = await client.post(f"/v1/rom-estimate/projects/{pid}/estimates/", json=_body(gross_floor_area="50000000"))
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "rom_estimate.area_in_range"
    assert r.json()["detail"]["error"] == "rom_estimate_rules_failed"


@pytest.mark.asyncio
async def test_api_valid_save_reports_warnings_and_second_save_moves_baseline(ctx) -> None:
    client, pid = ctx
    first = await client.post(f"/v1/rom-estimate/projects/{pid}/estimates/", json=_body())
    assert first.status_code in (200, 201), first.text
    assert {w["rule_id"] for w in first.json()["warnings"]} == {"rom_estimate.region_set"}
    second = await client.post(f"/v1/rom-estimate/projects/{pid}/estimates/", json=_body())
    assert {w["rule_id"] for w in second.json()["warnings"]} == {
        "rom_estimate.region_set",
        "rom_estimate.baseline_replaced",
    }
    nocurrency = await client.post(f"/v1/rom-estimate/projects/{pid}/estimates/", json=_body(currency=""))
    assert "rom_estimate.currency_stated" in {w["rule_id"] for w in nocurrency.json()["warnings"]}
