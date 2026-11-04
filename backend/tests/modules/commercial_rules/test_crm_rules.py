"""The ``crm`` rule set: each rule fires, a valid deal passes, writes are gated."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.crm.validators import (
    CRM_RULE_SET,
    OpportunityCloseDateNotPassedRule,
    OpportunityCloseDateRule,
    OpportunityCurrencyRule,
    OpportunityOwnerRule,
    OpportunityWonHasValueRule,
    register_crm_validation_rules,
)

TODAY = "2026-11-04"


def _o(**kw):
    base = {
        "id": "o1",
        "status": "open",
        "estimated_value": "250000",
        "currency": "EUR",
        "expected_close_date": "2027-01-15",
        "owner_user_id": "u1",
    }
    base.update(kw)
    return base


async def _run(rule, opp, locale="en"):
    context = ValidationContext(data={"opportunity": opp}, metadata={"locale": locale, "today": TODAY})
    return await rule().validate(context)


CASES = [
    (OpportunityCurrencyRule, _o(currency=""), "crm.value_requires_currency", Severity.ERROR),
    (OpportunityCloseDateRule, _o(expected_close_date="2027-02-31"), "crm.close_date_valid", Severity.ERROR),
    (
        OpportunityCloseDateNotPassedRule,
        _o(expected_close_date="2026-09-01"),
        "crm.close_date_not_passed",
        Severity.WARNING,
    ),
    (OpportunityWonHasValueRule, _o(status="won", estimated_value="0"), "crm.won_has_value", Severity.WARNING),
    (OpportunityOwnerRule, _o(owner_user_id=None), "crm.open_deal_has_owner", Severity.WARNING),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "bad", "rule_id", "severity"), CASES)
async def test_rule_fires_on_a_violation_and_passes_a_valid_deal(rule, bad, rule_id, severity):
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert [r.rule_id for r in failed] == [rule_id]
    assert failed[0].severity == severity
    assert "{" not in failed[0].message
    assert all(r.passed for r in await _run(rule, _o()))


@pytest.mark.asyncio
async def test_zero_value_needs_no_currency_and_closed_deals_are_not_stale():
    assert all(r.passed for r in await _run(OpportunityCurrencyRule, _o(currency="", estimated_value="0")))
    assert all(
        r.passed
        for r in await _run(OpportunityCloseDateNotPassedRule, _o(status="lost", expected_close_date="2020-01-01"))
    )


@pytest.mark.asyncio
async def test_message_is_translated():
    failed = [r for r in await _run(OpportunityCurrencyRule, _o(currency=""), "ru") if not r.passed]
    assert "валют" in failed[0].message


def test_rule_set_is_registered():
    register_crm_validation_rules()
    assert len({r.rule_id for r in rule_registry.get_rules_for_sets([CRM_RULE_SET])}) == 5


@pytest_asyncio.fixture(scope="module")
async def pipeline(client, admin_auth):
    """An account, a pipeline stage and a loss reason, created through the API."""
    uid, h = admin_auth
    tag = uuid.uuid4().hex[:8]
    acc = await client.post("/api/v1/crm/accounts/", json={"name": f"Owner {tag}"}, headers=h)
    assert acc.status_code == 201, acc.text
    stage = await client.post(
        "/api/v1/crm/pipeline-stages/",
        json={"code": f"bid-{tag}", "name": "Bid", "default_probability_percent": 30},
        headers=h,
    )
    assert stage.status_code == 201, stage.text
    reason = await client.post(
        "/api/v1/crm/win-loss-reasons/",
        json={"code": f"price-{tag}", "label": "Price", "category": "price", "is_loss_reason": True},
        headers=h,
    )
    assert reason.status_code == 201, reason.text
    return {
        "uid": uid,
        "h": h,
        "account": acc.json()["id"],
        "stage": stage.json()["id"],
        "reason": reason.json()["code"],
    }


def _body(p, **over):
    body = {
        "account_id": p["account"],
        "stage_id": p["stage"],
        "title": f"Hospital wing {uuid.uuid4().hex[:6]}",
        "estimated_value": "250000",
        "currency": "EUR",
        "expected_close_date": (date.today() + timedelta(days=60)).isoformat(),
        "owner_user_id": p["uid"],
    }
    body.update(over)
    return body


def _codes(resp):
    return {e["rule_id"] for e in resp.json()["detail"]["errors"]}


async def _make(client, p, **over):
    r = await client.post("/api/v1/crm/opportunities/", json=_body(p, **over), headers=p["h"])
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_blocking_rules_reject_api_create_with_code(client, pipeline):
    p = pipeline
    r = await client.post("/api/v1/crm/opportunities/", json=_body(p, currency=""), headers=p["h"])
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "crm_rules_failed"
    assert _codes(r) == {"crm.value_requires_currency"}
    r = await client.post("/api/v1/crm/opportunities/", json=_body(p, expected_close_date="2027-02-31"), headers=p["h"])
    assert r.status_code == 422 and _codes(r) == {"crm.close_date_valid"}


@pytest.mark.asyncio
async def test_valid_deal_is_clean_and_stale_unowned_deal_is_warned(client, pipeline):
    p = pipeline
    ok = await _make(client, p)
    assert ok["validation_warnings"] == []
    stale = await _make(client, p, owner_user_id=None, expected_close_date="2020-01-01")
    assert {w["rule_id"] for w in stale["validation_warnings"]} == {
        "crm.close_date_not_passed",
        "crm.open_deal_has_owner",
    }


@pytest.mark.asyncio
async def test_update_blocks_an_introduced_error_and_keeps_the_stored_deal(client, pipeline):
    p = pipeline
    deal = await _make(client, p)
    bad = await client.patch(f"/api/v1/crm/opportunities/{deal['id']}", json={"currency": ""}, headers=p["h"])
    assert bad.status_code == 422 and _codes(bad) == {"crm.value_requires_currency"}
    assert (await client.get(f"/api/v1/crm/opportunities/{deal['id']}", headers=p["h"])).json()["currency"] == "EUR"


@pytest.mark.asyncio
async def test_legacy_deal_without_currency_stays_editable_movable_and_closable(client, pipeline):
    p = pipeline
    from app.database import async_session_factory
    from app.modules.crm.service import CrmService

    deal = await _make(client, p)
    async with async_session_factory() as s:
        await CrmService(s).opportunity_repo.update_fields(uuid.UUID(deal["id"]), currency="")
        await s.commit()
    edit = await client.patch(
        f"/api/v1/crm/opportunities/{deal['id']}", json={"notes": "site visit done"}, headers=p["h"]
    )
    assert edit.status_code == 200, edit.text
    lost = await client.post(
        f"/api/v1/crm/opportunities/{deal['id']}/lose", json={"lost_reason_code": p["reason"]}, headers=p["h"]
    )
    assert lost.status_code == 200, lost.text


@pytest.mark.asyncio
async def test_win_without_value_is_allowed_with_a_warning(client, pipeline):
    p = pipeline
    deal = await _make(client, p, estimated_value="0", currency="")
    won = await client.post(f"/api/v1/crm/opportunities/{deal['id']}/win", json={}, headers=p["h"])
    assert won.status_code == 200, won.text
    assert [w["rule_id"] for w in won.json()["validation_warnings"]] == ["crm.won_has_value"]


@pytest.mark.asyncio
async def test_convert_lead_is_gated(client, pipeline):
    p = pipeline
    lead = await client.post("/api/v1/crm/leads/", json={"contact_name": "Site Manager"}, headers=p["h"])
    assert lead.status_code == 201, lead.text
    lead_id = lead.json()["id"]
    q = await client.post(
        f"/api/v1/crm/leads/{lead_id}/qualify", json={"qualification_notes": "budget"}, headers=p["h"]
    )
    assert q.status_code == 200, q.text
    payload = {"account_id": p["account"], "stage_id": p["stage"], "title": "Car park", "estimated_value": "90000"}
    bad = await client.post(f"/api/v1/crm/leads/{lead_id}/convert", json=payload, headers=p["h"])
    assert bad.status_code == 422 and _codes(bad) == {"crm.value_requires_currency"}
    ok = await client.post(f"/api/v1/crm/leads/{lead_id}/convert", json={**payload, "currency": "EUR"}, headers=p["h"])
    assert ok.status_code == 201, ok.text
    assert [w["rule_id"] for w in ok.json()["validation_warnings"]] == []


@pytest.mark.asyncio
async def test_stage_move_runs_the_rules_and_never_freezes_a_legacy_deal(client, pipeline):
    p = pipeline
    deal = await _make(client, p)
    other = await client.post(
        "/api/v1/crm/pipeline-stages/",
        json={"code": f"tender-{uuid.uuid4().hex[:6]}", "name": "Tender", "default_probability_percent": 60},
        headers=p["h"],
    )
    assert other.status_code == 201, other.text
    moved = await client.post(
        f"/api/v1/crm/opportunities/{deal['id']}/move-stage",
        json={"to_stage_id": other.json()["id"]},
        headers=p["h"],
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["validation_warnings"] == []
