"""The ``assets`` rule set: each rule fires, a valid entry passes, the service log is gated."""

from __future__ import annotations

import uuid

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.assets.validators import (
    ASSETS_RULE_SET,
    ServiceCostRule,
    ServiceDateNotFutureRule,
    ServiceDateRule,
    register_assets_validation_rules,
)

TODAY = "2026-11-04"


def _e(**kw):
    base = {"id": "s", "date": "2026-10-01", "cost": "180.50", "kind": "service"}
    base.update(kw)
    return base


async def _run(rule, entry, locale="en"):
    context = ValidationContext(data={"service": entry}, metadata={"locale": locale, "today": TODAY})
    return await rule().validate(context)


CASES = [
    (ServiceDateRule, _e(date="2026-02-31"), "assets.service_date_valid", Severity.ERROR),
    (ServiceDateRule, _e(date="last Tuesday"), "assets.service_date_valid", Severity.ERROR),
    (ServiceCostRule, _e(cost="about 200"), "assets.service_cost_valid", Severity.ERROR),
    (ServiceCostRule, _e(cost="-20"), "assets.service_cost_valid", Severity.ERROR),
    (ServiceDateNotFutureRule, _e(date="2999-01-01"), "assets.service_not_in_future", Severity.WARNING),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "bad", "rule_id", "severity"), CASES)
async def test_rule_fires_on_a_violation_and_passes_a_valid_entry(rule, bad, rule_id, severity):
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert [r.rule_id for r in failed] == [rule_id]
    assert failed[0].severity == severity
    assert "{" not in failed[0].message
    assert all(r.passed for r in await _run(rule, _e()))


@pytest.mark.asyncio
async def test_cost_is_optional_and_zero_is_a_valid_cost():
    assert all(r.passed for r in await _run(ServiceCostRule, _e(cost=None)))
    assert all(r.passed for r in await _run(ServiceCostRule, _e(cost="0")))


@pytest.mark.asyncio
async def test_message_is_translated():
    failed = [r for r in await _run(ServiceDateRule, _e(date="2026-02-31"), "ru") if not r.passed]
    assert "дата" in failed[0].message.lower()


def test_rule_set_is_registered():
    register_assets_validation_rules()
    assert len({r.rule_id for r in rule_registry.get_rules_for_sets([ASSETS_RULE_SET])}) == 3


def _codes(resp):
    return {e["rule_id"] for e in resp.json()["detail"]["errors"]}


async def _element(project_id, asset_info=None) -> str:
    from app.database import async_session_factory
    from app.modules.bim_hub.models import BIMElement, BIMModel

    async with async_session_factory() as s:
        model = BIMModel(project_id=uuid.UUID(project_id), name="Mechanical.rvt", status="ready")
        s.add(model)
        await s.flush()
        el = BIMElement(
            model_id=model.id,
            stable_id=f"AHU-{uuid.uuid4().hex[:6]}",
            element_type="Mechanical Equipment",
            name="Rooftop AHU",
            properties={},
            asset_info=asset_info or {},
            is_tracked_asset=True,
        )
        s.add(el)
        await s.commit()
        return str(el.id)


@pytest.mark.asyncio
async def test_blocking_rules_reject_the_service_log_write_with_code(client, admin_auth, project_id):
    _, h = admin_auth
    el = await _element(project_id)
    url = f"/api/v1/assets/{el}/service-log"
    bad = await client.post(url, json={"date": "2026-02-31", "note": "filter change"}, headers=h)
    assert bad.status_code == 422, bad.text
    assert bad.json()["detail"]["error"] == "asset_rules_failed"
    assert _codes(bad) == {"assets.service_date_valid"}
    bad = await client.post(url, json={"date": "2026-10-01", "note": "filter change", "cost": "n/a"}, headers=h)
    assert bad.status_code == 422 and _codes(bad) == {"assets.service_cost_valid"}


@pytest.mark.asyncio
async def test_valid_entry_is_clean_and_a_future_one_is_warned(client, admin_auth, project_id):
    _, h = admin_auth
    el = await _element(project_id)
    url = f"/api/v1/assets/{el}/service-log"
    ok = await client.post(url, json={"date": "2026-10-01", "note": "belt replaced", "cost": "180.50"}, headers=h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["validation_warnings"] == []
    future = await client.post(url, json={"date": "2999-01-01", "note": "booked"}, headers=h)
    assert future.status_code == 200, future.text
    assert [w["rule_id"] for w in future.json()["validation_warnings"]] == ["assets.service_not_in_future"]


@pytest.mark.asyncio
async def test_asset_with_a_legacy_bad_log_entry_still_takes_new_entries(client, admin_auth, project_id):
    _, h = admin_auth
    el = await _element(project_id, {"service_log": [{"date": "sometime in spring", "note": "old", "cost": "tbd"}]})
    ok = await client.post(
        f"/api/v1/assets/{el}/service-log", json={"date": "2026-10-01", "note": "annual service"}, headers=h
    )
    assert ok.status_code == 200, ok.text
    assert len(ok.json()["service_log"]) == 2
