"""The ``construction_control`` rule set: each rule fires, writes are gated."""

from __future__ import annotations

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.construction_control.models import AcceptanceCriterion
from app.modules.construction_control.validators import (
    CONSTRUCTION_CONTROL_RULE_SET,
    CertificateInDateRule,
    CertificateWindowRule,
    CriterionToleranceBandRule,
    EvidenceDatesRule,
    TestLabAccreditedRule,
    register_construction_control_validation_rules,
)

from ._helpers import force_update

TODAY = "2026-11-04"


def _crit(**kw):
    return {
        "id": "c1",
        "acceptance_rule": "range",
        "nominal_value": "30",
        "tolerance_lower": "28",
        "tolerance_upper": "32",
    } | kw


def _mat(**kw):
    return {
        "id": "m1",
        "status": "accepted",
        "issued_at": "2026-01-02",
        "valid_from": "2026-01-02",
        "valid_until": "2027-01-02",
    } | kw


def _test(**kw):
    return {
        "id": "t1",
        "status": "recorded",
        "lab_name": "Concrete Lab Ltd",
        "lab_accreditation": "ACC-1042",
        "is_accredited": True,
        "sampled_at": "2026-10-01",
        "tested_at": "2026-10-29",
    } | kw


async def _run(rule, data, locale="en"):
    context = ValidationContext(data=data, metadata={"locale": locale, "today": TODAY})
    return await rule().validate(context)


CASES = [
    (
        CriterionToleranceBandRule,
        {"criterion": _crit(tolerance_lower="33")},
        "construction_control.criterion_tolerance_band",
        Severity.ERROR,
    ),
    (
        CriterionToleranceBandRule,
        {"criterion": _crit(nominal_value="40")},
        "construction_control.criterion_tolerance_band",
        Severity.ERROR,
    ),
    (
        CertificateWindowRule,
        {"material": _mat(valid_until="2025-12-31")},
        "construction_control.certificate_window",
        Severity.ERROR,
    ),
    (
        CertificateInDateRule,
        {"material": _mat(valid_until="2026-06-30")},
        "construction_control.certificate_in_date",
        Severity.WARNING,
    ),
    (
        EvidenceDatesRule,
        {"test": _test(sampled_at="2026-12-24", tested_at=None)},
        "construction_control.evidence_dates",
        Severity.ERROR,
    ),
    (
        EvidenceDatesRule,
        {"test": _test(sampled_at="2026-10-20", tested_at="2026-10-10")},
        "construction_control.evidence_dates",
        Severity.ERROR,
    ),
    (
        EvidenceDatesRule,
        {"asbuilt": {"id": "a1", "survey_date": "2027-05-01"}},
        "construction_control.evidence_dates",
        Severity.ERROR,
    ),
    (
        TestLabAccreditedRule,
        {"test": _test(is_accredited=False, lab_accreditation="")},
        "construction_control.test_lab_accredited",
        Severity.WARNING,
    ),
]
VALID = {
    CriterionToleranceBandRule: {"criterion": _crit()},
    CertificateWindowRule: {"material": _mat()},
    CertificateInDateRule: {"material": _mat()},
    EvidenceDatesRule: {"test": _test(), "inspection": {"id": "i1", "performed_at": "2026-10-30"}},
    TestLabAccreditedRule: {"test": _test()},
}


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "data", "rule_id", "severity"), CASES)
async def test_rule_fires_on_a_violation_and_passes_a_valid_record(rule, data, rule_id, severity):
    failed = [r for r in await _run(rule, data) if not r.passed]
    assert [r.rule_id for r in failed] == [rule_id]
    assert failed[0].severity == severity
    assert "{" not in failed[0].message
    assert all(r.passed for r in await _run(rule, VALID[rule]))


@pytest.mark.asyncio
async def test_open_ended_bands_text_criteria_and_draft_materials_are_left_alone():
    assert all(r.passed for r in await _run(CriterionToleranceBandRule, {"criterion": _crit(tolerance_upper=None)}))
    assert all(
        r.passed
        for r in await _run(
            CriterionToleranceBandRule, {"criterion": _crit(acceptance_rule="text", tolerance_lower="40")}
        )
    )
    assert all(
        r.passed
        for r in await _run(CertificateInDateRule, {"material": _mat(status="draft", valid_until="2020-01-01")})
    )
    assert all(
        r.passed
        for r in await _run(
            TestLabAccreditedRule, {"test": _test(status="planned", is_accredited=False, lab_accreditation="")}
        )
    )


@pytest.mark.asyncio
async def test_message_is_translated():
    failed = [
        r for r in await _run(CertificateWindowRule, {"material": _mat(valid_until="2025-12-31")}, "de") if not r.passed
    ]
    assert "Zertifikat" in failed[0].message


def test_rule_set_is_registered():
    register_construction_control_validation_rules()
    assert len({r.rule_id for r in rule_registry.get_rules_for_sets([CONSTRUCTION_CONTROL_RULE_SET])}) == 5


# -- write points --------------------------------------------------------------------------------------

CC = "/api/v1/construction-control"


def _criterion(project_id, **over):
    return {
        "project_id": project_id,
        "code": "C30-slump",
        "title": "Concrete cube strength",
        "acceptance_rule": "range",
        "nominal_value": "30",
        "tolerance_lower": "28",
        "tolerance_upper": "32",
    } | over


@pytest.mark.asyncio
async def test_a_criterion_whose_nominal_is_outside_its_band_is_refused_with_its_code(client, admin_auth, project_id):
    _, h = admin_auth
    resp = await client.post(f"{CC}/criteria", json=_criterion(project_id, nominal_value="40", code="C-bad"), headers=h)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "construction_control_rules_failed"
    assert [e["rule_id"] for e in detail["errors"]] == ["construction_control.criterion_tolerance_band"]
    ok = await client.post(f"{CC}/criteria", json=_criterion(project_id, code="C-ok"), headers=h)
    assert ok.status_code == 201, ok.text
    assert ok.json()["validation_warnings"] == []


@pytest.mark.asyncio
async def test_a_legacy_criterion_stays_editable_but_an_edit_cannot_break_a_good_one(client, admin_auth, project_id):
    _, h = admin_auth
    legacy = await client.post(f"{CC}/criteria", json=_criterion(project_id, code="C-legacy"), headers=h)
    assert legacy.status_code == 201, legacy.text
    await force_update(AcceptanceCriterion, legacy.json()["id"], nominal_value="45")
    edited = await client.patch(f"{CC}/criteria/{legacy.json()['id']}", json={"title": "Cube strength 28d"}, headers=h)
    assert edited.status_code == 200, edited.text

    good = await client.post(f"{CC}/criteria", json=_criterion(project_id, code="C-good"), headers=h)
    # only the nominal changes, so pydantic sees no bounds and cannot catch it; the rule does
    bad = await client.patch(f"{CC}/criteria/{good.json()['id']}", json={"nominal_value": "45"}, headers=h)
    assert bad.status_code == 422, bad.text
    assert bad.json()["detail"]["error"] == "construction_control_rules_failed"


@pytest.mark.asyncio
async def test_an_edit_that_makes_a_certificate_expire_before_it_starts_is_refused(client, admin_auth, project_id):
    _, h = admin_auth
    ok = await client.post(
        f"{CC}/materials",
        json={
            "project_id": project_id,
            "name": "Reinforcing steel B500B",
            "valid_from": "2026-06-01",
            "valid_until": "2999-01-01",
        },
        headers=h,
    )
    assert ok.status_code == 201, ok.text
    resp = await client.patch(f"{CC}/materials/{ok.json()['id']}", json={"valid_until": "2026-01-01"}, headers=h)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "construction_control_rules_failed"
    assert [e["rule_id"] for e in detail["errors"]] == ["construction_control.certificate_window"]


@pytest.mark.asyncio
async def test_a_test_dated_in_the_future_is_refused(client, admin_auth, project_id):
    _, h = admin_auth
    resp = await client.post(
        f"{CC}/test-results",
        json={"project_id": project_id, "title": "Cube crush 28d", "sampled_at": "2999-01-01"},
        headers=h,
    )
    assert resp.status_code == 422, resp.text
    assert [e["rule_id"] for e in resp.json()["detail"]["errors"]] == ["construction_control.evidence_dates"]
    ok = await client.post(
        f"{CC}/test-results",
        json={"project_id": project_id, "title": "Cube crush 28d", "sampled_at": "2026-10-01"},
        headers=h,
    )
    assert ok.status_code == 201, ok.text


@pytest.mark.asyncio
async def test_an_as_built_survey_in_the_future_is_refused(client, admin_auth, project_id):
    _, h = admin_auth
    resp = await client.post(
        f"{CC}/asbuilt",
        json={"project_id": project_id, "title": "Slab level 2", "survey_date": "2999-01-01"},
        headers=h,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["error"] == "construction_control_rules_failed"
    ok = await client.post(
        f"{CC}/asbuilt",
        json={"project_id": project_id, "title": "Slab level 2", "survey_date": "2026-10-01"},
        headers=h,
    )
    assert ok.status_code == 201, ok.text
