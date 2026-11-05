# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Price index rules: each rule firing, a valid record passing, the API refusing a blocking one."""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.price_index.models import LocationFactor
from app.modules.price_index.permissions import register_price_index_permissions
from app.modules.price_index.router import router as price_router
from app.modules.price_index.validators import (
    PRICE_INDEX_RULE_SET,
    IndexSourceStatedRule,
    IndexStepPlausibleRule,
    LocationFactorBandRule,
    PeriodUniqueRule,
    RegionUniqueRule,
    month_number,
    register_price_index_validation_rules,
)
from tests.modules._api_support import api_client


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (
        PeriodUniqueRule,
        {"point": {"id": "p1", "period": "2026-03"}, "points": [{"id": "p2", "period": "2026-02"}]},
        {"point": {"id": "p1", "period": "2026-03"}, "points": [{"id": "p2", "period": "2026-03"}]},
    ),
    (
        RegionUniqueRule,
        {"location": {"id": "l1", "region_code": "BY"}, "locations": [{"id": "l2", "region_code": "BE"}]},
        {"location": {"id": "l1", "region_code": "BY"}, "locations": [{"id": "l2", "region_code": "BY"}]},
    ),
    (
        LocationFactorBandRule,
        {"location": {"id": "l1", "region_code": "BY", "factor": "1.08"}},
        {"location": {"id": "l1", "region_code": "BY", "factor": "10.8"}},
    ),
    (
        IndexStepPlausibleRule,
        {
            "step": {"id": "s", "at": "2026-Q2", "value": "104"},
            "neighbours": [{"at": "2026-Q1", "value": "100"}],
        },
        {
            "step": {"id": "s", "at": "2026-Q2", "value": "1040"},
            "neighbours": [{"at": "2026-Q1", "value": "100"}],
        },
    ),
    (
        IndexSourceStatedRule,
        {"index": {"id": "i", "source": "Quarterly letter 1/2026", "is_sample": False}},
        {"index": {"id": "i", "source": " ", "is_sample": False}},
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES)
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "price_index." not in failed[0].message
    assert failed[0].suggestion and "price_index." not in failed[0].suggestion


@pytest.mark.asyncio
async def test_sample_index_needs_no_source_and_empty_context_passes() -> None:
    assert all(r.passed for r in await _run(IndexSourceStatedRule(), {"index": {"id": "i", "is_sample": True}}))
    for rule_cls, _, _ in CASES:
        assert all(r.passed for r in await _run(rule_cls(), {}))


def test_month_number_reads_months_and_quarters() -> None:
    assert month_number("2026-03") == month_number("2026-Q1")
    assert month_number("garbage") is None


@pytest.mark.asyncio
async def test_message_follows_locale() -> None:
    bad = CASES[2][2]
    de = (await _run(LocationFactorBandRule(), bad, locale="de"))[0]
    assert "Regionalfaktor" in de.message


def test_registered_under_rule_set() -> None:
    register_price_index_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([PRICE_INDEX_RULE_SET])}
    assert ids == {
        "price_index.period_unique",
        "price_index.region_unique",
        "price_index.location_factor_band",
        "price_index.step_plausible",
        "price_index.source_stated",
    }


# ── API on real PostgreSQL ───────────────────────────────────────────────────


@pytest_asyncio.fixture
async def ctx():
    async with api_client(
        price_router, "/v1/price-index", register_price_index_permissions, register_price_index_validation_rules
    ) as (client, session, _user):
        yield client, session


@pytest.mark.asyncio
async def test_api_blocks_duplicate_period_with_code(ctx) -> None:
    client, _ = ctx
    s = await client.post("/v1/price-index/series/", json={"name": "BCI"})
    sid = s.json()["id"]
    first = await client.post(f"/v1/price-index/series/{sid}/points/", json={"period": "2026-01", "factor": "100"})
    assert first.status_code == 201, first.text
    assert first.json()["warnings"] == []
    dup = await client.post(f"/v1/price-index/series/{sid}/points/", json={"period": "2026-01", "factor": "101"})
    assert dup.status_code == 422, dup.text
    assert dup.json()["detail"]["code"] == "price_index.period_unique"
    assert dup.json()["detail"]["error"] == "price_index_rules_failed"
    assert "2026-01" in dup.text
    assert "duplicate_" not in dup.text


@pytest.mark.asyncio
async def test_api_point_jump_warns_but_saves(ctx) -> None:
    client, _ = ctx
    sid = (await client.post("/v1/price-index/series/", json={"name": "BCI jump"})).json()["id"]
    await client.post(f"/v1/price-index/series/{sid}/points/", json={"period": "2026-01", "factor": "100"})
    r = await client.post(f"/v1/price-index/series/{sid}/points/", json={"period": "2026-02", "factor": "400"})
    assert r.status_code == 201, r.text
    assert [w["rule_id"] for w in r.json()["warnings"]] == ["price_index.step_plausible"]


@pytest.mark.asyncio
async def test_api_region_duplicate_blocks_and_outlier_warns(ctx) -> None:
    client, _ = ctx
    ok = await client.post("/v1/price-index/location-factors/", json={"region_code": "BY", "factor": "1.05"})
    assert ok.status_code == 201, ok.text
    assert ok.json()["warnings"] == []
    dup = await client.post("/v1/price-index/location-factors/", json={"region_code": "BY", "factor": "1.1"})
    assert dup.status_code == 422, dup.text
    assert dup.json()["detail"]["code"] == "price_index.region_unique"
    assert "BY" in dup.text
    assert "duplicate_" not in dup.text
    odd = await client.post("/v1/price-index/location-factors/", json={"region_code": "NRW", "factor": "9"})
    assert odd.status_code == 201, odd.text
    assert [w["rule_id"] for w in odd.json()["warnings"]] == ["price_index.location_factor_band"]


@pytest.mark.asyncio
async def test_api_update_blocks_new_duplicate_but_legacy_outlier_stays_editable(ctx) -> None:
    # The database keys periods and regions, so a stored duplicate cannot exist; a stored outlier can.
    client, session = ctx
    legacy = LocationFactor(region_code="HH", label="old", factor=Decimal("9"))
    session.add(legacy)
    await session.flush()

    relabel = await client.patch(f"/v1/price-index/location-factors/{legacy.id}/", json={"label": "Hamburg"})
    assert relabel.status_code == 200, relabel.text
    assert [w["rule_id"] for w in relabel.json()["warnings"]] == ["price_index.location_factor_band"]

    other = (await client.post("/v1/price-index/location-factors/", json={"region_code": "SN", "factor": "1"})).json()
    clash = await client.patch(f"/v1/price-index/location-factors/{other['id']}/", json={"region_code": "HH"})
    assert clash.status_code == 422, clash.text
    assert clash.json()["detail"]["code"] == "price_index.region_unique"

    sid = (await client.post("/v1/price-index/series/", json={"name": "BCI edit"})).json()["id"]
    await client.post(f"/v1/price-index/series/{sid}/points/", json={"period": "2026-01", "factor": "100"})
    p2 = (
        await client.post(f"/v1/price-index/series/{sid}/points/", json={"period": "2026-02", "factor": "101"})
    ).json()
    move = await client.patch(f"/v1/price-index/series/{sid}/points/{p2['id']}/", json={"period": "2026-01"})
    assert move.status_code == 422, move.text
    assert move.json()["detail"]["code"] == "price_index.period_unique"
