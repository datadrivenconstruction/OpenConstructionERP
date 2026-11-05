"""Coordination rule sets: each rule fires, a valid record passes, severities and messages hold."""

from __future__ import annotations

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.approval_routes import validators as ar
from app.modules.clash import validators as cl
from app.modules.compliance_docs import validators as cd
from app.modules.coordination_hub import validators as ch
from app.modules.file_transmittals import validators as ft
from app.modules.plan_room import validators as pr

TODAY = "2026-11-05"
E, W = Severity.ERROR, Severity.WARNING
GOOD_DOC = {
    "id": "d",
    "doc_type": "insurance_general_liability",
    "policy_number": "P-1",
    "coverage_amount": "100000",
    "currency": "EUR",
    "status": "active",
    "expires_at": "2027-01-01",
}
GOOD_T = {
    "id": "t",
    "status": "sent",
    "reason_code": "for_construction",
    "recipients": [{"email": "a@b.io"}],
    "items": [{"name": "A.pdf", "version": "C01"}],
}
GOOD_ROUTE = {"id": "r", "is_active": True, "steps": [{"approver_role": "admin", "sla_hours": 24}]}
UUID = "7d2f0a52-8f3b-4c0e-9d51-3a1b2c3d4e5f"
THR = "open_clashes_total"

# (rule, key, bad record, valid record, rule id, severity)
CASES = [
    (
        pr.PinPhotoRefRule,
        "pin",
        {"id": "p", "photo_ref": "C:/x/a.jpg"},
        {"id": "p", "photo_ref": "ph/1.jpg"},
        "plan_room.pin_photo_ref",
        E,
    ),
    (
        pr.PinPhotoRefRule,
        "pin",
        {"id": "p", "photo_ref": "../a.jpg"},
        {"id": "p", "photo_ref": "ph/1.jpg"},
        "plan_room.pin_photo_ref",
        E,
    ),
    (
        pr.PinFileVersionRule,
        "pin",
        {"id": "p", "file_version_id": "nope"},
        {"id": "p", "file_version_id": UUID},
        "plan_room.pin_file_version",
        E,
    ),
    (pr.PinHasContentRule, "pin", {"id": "p", "page": 2}, {"id": "p", "note": "crack"}, "plan_room.pin_has_content", W),
    (
        cd.CoverageAmountRule,
        "doc",
        {**GOOD_DOC, "coverage_amount": None},
        GOOD_DOC,
        "compliance_docs.coverage_amount",
        E,
    ),
    (cd.CurrencyCodeRule, "doc", {**GOOD_DOC, "currency": "euro"}, GOOD_DOC, "compliance_docs.currency_code", E),
    (
        cd.StatusMatchesDatesRule,
        "doc",
        {**GOOD_DOC, "expires_at": "2026-01-01"},
        GOOD_DOC,
        "compliance_docs.status_matches_dates",
        E,
    ),
    (cd.PolicyNumberRule, "doc", {**GOOD_DOC, "policy_number": ""}, GOOD_DOC, "compliance_docs.policy_number", W),
    (ft.SendNeedsItemsRule, "transmittal", {**GOOD_T, "items": []}, GOOD_T, "file_transmittals.send_has_items", E),
    (
        ft.SendNeedsRecipientsRule,
        "transmittal",
        {**GOOD_T, "recipients": []},
        GOOD_T,
        "file_transmittals.send_has_recipients",
        E,
    ),
    (
        ft.DuplicateItemRule,
        "transmittal",
        {**GOOD_T, "items": [GOOD_T["items"][0]] * 2},
        GOOD_T,
        "file_transmittals.duplicate_item",
        E,
    ),
    (
        ft.ConstructionItemVersionRule,
        "transmittal",
        {**GOOD_T, "items": [{"name": "A.pdf"}]},
        GOOD_T,
        "file_transmittals.construction_item_version",
        W,
    ),
    (
        ar.ApproverRoleKnownRule,
        "route",
        {**GOOD_ROUTE, "steps": [{"approver_role": "no_such_role_x", "sla_hours": 4}]},
        GOOD_ROUTE,
        "approval_routes.approver_role_known",
        E,
    ),
    (
        ar.StepSlaRule,
        "route",
        {**GOOD_ROUTE, "steps": [{"approver_role": "admin"}]},
        GOOD_ROUTE,
        "approval_routes.step_sla",
        W,
    ),
    (
        ar.DelegationEndedRule,
        "delegation",
        {"id": "g", "ends_at": "2026-10-01"},
        {"id": "g", "ends_at": "2026-12-01"},
        "approval_routes.delegation_ended",
        E,
    ),
    (
        ar.DelegationOpenEndedRule,
        "delegation",
        {"id": "g"},
        {"id": "g", "ends_at": "2026-12-01"},
        "approval_routes.delegation_open_ended",
        W,
    ),
    (
        ch.ThresholdOrderRule,
        "threshold",
        {"metric": THR, "warn_value": 9, "error_value": 3},
        {"metric": THR, "warn_value": 3, "error_value": 9},
        "coordination_hub.threshold_order",
        E,
    ),
    (
        ch.ThresholdValueRule,
        "threshold",
        {"metric": THR, "warn_value": -1},
        {"metric": THR, "warn_value": 3},
        "coordination_hub.threshold_value",
        E,
    ),
    (
        ch.ThresholdValueRule,
        "threshold",
        {"metric": "model_age_days_max", "warn_value": 2.5},
        {"metric": "model_age_days_max", "warn_value": 3},
        "coordination_hub.threshold_value",
        E,
    ),
    (
        ch.ThresholdEnabledRule,
        "threshold",
        {"metric": THR, "enabled": False},
        {"metric": THR, "enabled": True},
        "coordination_hub.threshold_enabled",
        W,
    ),
    (
        cl.DueDateFormatRule,
        "clash",
        {"id": "c", "due_date": "next week"},
        {"id": "c", "due_date": "2026-12-01"},
        "clash.due_date_format",
        E,
    ),
    (
        cl.DueDatePastRule,
        "clash",
        {"id": "c", "status": "active", "due_date": "2026-10-01"},
        {"id": "c", "status": "resolved", "due_date": "2026-10-01"},
        "clash.due_date_past",
        W,
    ),
    (
        cl.SevereClashOwnerRule,
        "clash",
        {"id": "c", "status": "active", "severity": "critical"},
        {"id": "c", "status": "active", "severity": "critical", "assigned_to": "u"},
        "clash.severe_has_assignee",
        W,
    ),
    (
        cl.ClearanceDistanceRule,
        "run",
        {"id": "r", "clash_type": "clearance", "clearance_m": 0},
        {"id": "r", "clash_type": "clearance", "clearance_m": 0.05},
        "clash.clearance_distance",
        E,
    ),
]


async def _run(rule, key, record, locale="en"):
    ctx = ValidationContext(data={key: record}, metadata={"locale": locale, "today": TODAY})
    return await rule().validate(ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "key", "bad", "good", "rule_id", "severity"), CASES)
async def test_rule_fires_and_a_valid_record_passes(rule, key, bad, good, rule_id, severity):
    failed = [r for r in await _run(rule, key, bad) if not r.passed]
    assert [r.rule_id for r in failed] == [rule_id]
    assert failed[0].severity == severity
    assert "{" not in failed[0].message
    assert all(r.passed for r in await _run(rule, key, good))


@pytest.mark.asyncio
async def test_message_is_translated():
    bad = {**GOOD_T, "items": []}
    failed = [r for r in await _run(ft.SendNeedsItemsRule, "transmittal", bad, "de") if not r.passed]
    assert "Datei" in failed[0].message
