"""The ``qms`` rule set: each rule fires, a valid record passes, writes are gated."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.qms.models import QMSNCR, QMSCalibration
from app.modules.qms.validators import (
    QMS_RULE_SET,
    CalibrationLapsedRule,
    CalibrationWindowRule,
    NcrCostCurrencyRule,
    NcrRootCauseRule,
    PunchDueDateRule,
    register_qms_validation_rules,
)

from ._helpers import force_update

TODAY = "2026-11-04"
NCR = "ncr"
PUNCH = "punch"
CAL = "calibration"


def _ncr(**kw):
    base = {
        "id": "n1",
        "severity": "major",
        "status": "open",
        "root_cause": "",
        "cost_impact_amount": "1200",
        "cost_impact_currency": "EUR",
    }
    return base | kw


def _punch(**kw):
    return {"id": "p1", "raised_at": "2026-10-01T08:00:00+00:00", "due_date": "2026-10-20T00:00:00+00:00"} | kw


def _cal(**kw):
    return {
        "id": "c1",
        "status": "valid",
        "calibration_date": "2026-01-10",
        "valid_until": "2027-01-10",
    } | kw


async def _run(rule, key, record, locale="en"):
    context = ValidationContext(data={key: record}, metadata={"locale": locale, "today": TODAY})
    return await rule().validate(context)


CASES = [
    (NcrCostCurrencyRule, NCR, _ncr(cost_impact_currency=""), "qms.ncr_cost_currency", Severity.ERROR),
    (
        NcrRootCauseRule,
        NCR,
        _ncr(status="verifying", severity="critical"),
        "qms.ncr_root_cause",
        Severity.ERROR,
    ),
    (PunchDueDateRule, PUNCH, _punch(due_date="2026-09-01T00:00:00+00:00"), "qms.punch_due_date", Severity.ERROR),
    (CalibrationWindowRule, CAL, _cal(valid_until="2026-01-10"), "qms.calibration_window", Severity.ERROR),
    (CalibrationLapsedRule, CAL, _cal(valid_until="2026-06-30"), "qms.calibration_lapsed", Severity.WARNING),
]
VALID = {NCR: _ncr(root_cause="Wrong mix"), PUNCH: _punch(), CAL: _cal()}


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "key", "bad", "rule_id", "severity"), CASES)
async def test_rule_fires_on_a_violation_and_passes_a_valid_record(rule, key, bad, rule_id, severity):
    failed = [r for r in await _run(rule, key, bad) if not r.passed]
    assert [r.rule_id for r in failed] == [rule_id]
    assert failed[0].severity == severity
    assert "{" not in failed[0].message
    assert all(r.passed for r in await _run(rule, key, VALID[key]))


@pytest.mark.asyncio
async def test_minor_and_open_ncrs_need_no_root_cause_yet_and_zero_cost_needs_no_currency():
    assert all(r.passed for r in await _run(NcrRootCauseRule, NCR, _ncr(status="open", severity="critical")))
    assert all(r.passed for r in await _run(NcrRootCauseRule, NCR, _ncr(status="closed", severity="minor")))
    assert all(
        r.passed for r in await _run(NcrCostCurrencyRule, NCR, _ncr(cost_impact_amount="0", cost_impact_currency=""))
    )


@pytest.mark.asyncio
async def test_an_expired_calibration_is_not_flagged_as_lapsed():
    assert all(
        r.passed for r in await _run(CalibrationLapsedRule, CAL, _cal(status="expired", valid_until="2025-01-01"))
    )


@pytest.mark.asyncio
async def test_message_is_translated():
    failed = [r for r in await _run(NcrCostCurrencyRule, NCR, _ncr(cost_impact_currency=""), "de") if not r.passed]
    assert "Währung" in failed[0].message


def test_rule_set_is_registered():
    register_qms_validation_rules()
    assert len({r.rule_id for r in rule_registry.get_rules_for_sets([QMS_RULE_SET])}) == 5


# -- write points --------------------------------------------------------------------------------------

BASE = "/api/v1/qms"


def _ncr_body(project_id):
    return {
        "project_id": project_id,
        "title": "Honeycombing",
        "description": "Wall W2",
        "cost_impact_amount": "900",
        "cost_impact_currency": "EUR",
    }


@pytest.mark.asyncio
async def test_an_edit_that_drops_the_currency_of_a_costed_ncr_is_refused_with_its_code(client, admin_auth, project_id):
    _, h = admin_auth
    ok = await client.post(f"{BASE}/ncrs", json=_ncr_body(project_id), headers=h)
    assert ok.status_code == 201, ok.text
    assert ok.json()["validation_warnings"] == []
    resp = await client.patch(f"{BASE}/ncrs/{ok.json()['id']}", json={"cost_impact_currency": ""}, headers=h)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "qms_rules_failed"
    assert [e["rule_id"] for e in detail["errors"]] == ["qms.ncr_cost_currency"]


@pytest.mark.asyncio
async def test_a_legacy_violating_ncr_stays_editable(client, admin_auth, project_id):
    _, h = admin_auth
    ok = await client.post(f"{BASE}/ncrs", json=_ncr_body(project_id), headers=h)
    ncr_id = ok.json()["id"]
    await force_update(QMSNCR, ncr_id, cost_impact_currency="")
    edited = await client.patch(f"{BASE}/ncrs/{ncr_id}", json={"title": "Honeycombing, wall W2"}, headers=h)
    assert edited.status_code == 200, edited.text


@pytest.mark.asyncio
async def test_a_punch_item_due_before_it_was_raised_is_refused(client, admin_auth, project_id):
    _, h = admin_auth
    resp = await client.post(
        f"{BASE}/punch-items",
        json={"project_id": project_id, "title": "Paint touch-up", "due_date": "2020-01-01"},
        headers=h,
    )
    assert resp.status_code == 422, resp.text
    assert [e["rule_id"] for e in resp.json()["detail"]["errors"]] == ["qms.punch_due_date"]
    ok = await client.post(
        f"{BASE}/punch-items",
        json={"project_id": project_id, "title": "Paint touch-up", "due_date": "2999-01-01"},
        headers=h,
    )
    assert ok.status_code == 201, ok.text


def _calibration(project_id, **over):
    body = {
        "project_id": project_id,
        "instrument_id": "TH-17",
        "instrument_name": "Concrete thermometer",
        "instrument_type": "thermometer",
        "calibration_date": "2026-01-10",
        "valid_until": "2999-01-10",
    }
    return body | over


@pytest.mark.asyncio
async def test_an_edit_that_ends_a_calibration_before_it_starts_is_refused(client, admin_auth, project_id):
    _, h = admin_auth
    ok = await client.post(f"{BASE}/calibrations", json=_calibration(project_id), headers=h)
    assert ok.status_code == 201, ok.text
    assert ok.json()["validation_warnings"] == []
    bad = await client.patch(f"{BASE}/calibrations/{ok.json()['id']}", json={"valid_until": "2025-01-01"}, headers=h)
    assert bad.status_code == 422, bad.text
    detail = bad.json()["detail"]
    assert detail["error"] == "qms_rules_failed"
    assert "qms.calibration_window" in [e["rule_id"] for e in detail["errors"]]


@pytest.mark.asyncio
async def test_a_lapsed_calibration_is_saved_with_a_warning_and_a_legacy_window_stays_editable(
    client, admin_auth, project_id
):
    _, h = admin_auth
    resp = await client.post(
        f"{BASE}/calibrations",
        json=_calibration(project_id, calibration_date="2019-01-10", valid_until="2020-01-10"),
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    assert [w["rule_id"] for w in resp.json()["validation_warnings"]] == ["qms.calibration_lapsed"]
    cal_id = resp.json()["id"]
    await force_update(QMSCalibration, cal_id, valid_until=date(2018, 1, 10))
    edited = await client.patch(f"{BASE}/calibrations/{cal_id}", json={"notes": "Sent for service"}, headers=h)
    assert edited.status_code == 200, edited.text
