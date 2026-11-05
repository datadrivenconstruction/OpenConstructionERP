"""The ``requirements`` and ``bim_requirements`` rule sets: each rule fires, writes are gated."""

from __future__ import annotations

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.bim_requirements.validators import (
    BIM_REQUIREMENTS_RULE_SET,
    BoundsOrderedRule,
    ElementFilterPresentRule,
    PatternCompilesRule,
    PropertyNamedRule,
    register_bim_requirements_validation_rules,
)
from app.modules.requirements.models import Requirement
from app.modules.requirements.validators import (
    REQUIREMENTS_RULE_SET,
    ConstraintValueUsableRule,
    LockedSetNotEmptyRule,
    MustHaveVerificationRule,
    NumericUnitRule,
    register_requirements_validation_rules,
)

from ._helpers import force_update


def _req(**kw):
    base = {
        "id": "r1",
        "entity": "Wall",
        "attribute": "FireRating",
        "constraint_type": "min",
        "constraint_value": "60",
        "unit": "min",
        "priority": "must",
        "verification_method": "model_check",
    }
    return base | kw


async def _run(rule, key, record, locale="en"):
    context = ValidationContext(data={key: record}, metadata={"locale": locale})
    return await rule().validate(context)


REQ_CASES = [
    (
        ConstraintValueUsableRule,
        "requirement",
        _req(constraint_value=""),
        "requirements.constraint_value_usable",
        Severity.ERROR,
    ),
    (
        ConstraintValueUsableRule,
        "requirement",
        _req(constraint_type="range", constraint_value="10 to 20"),
        "requirements.constraint_value_usable",
        Severity.ERROR,
    ),
    (
        ConstraintValueUsableRule,
        "requirement",
        _req(constraint_type="regex", constraint_value="([0-9"),
        "requirements.constraint_value_usable",
        Severity.ERROR,
    ),
    (NumericUnitRule, "requirement", _req(unit=""), "requirements.numeric_unit", Severity.WARNING),
    (
        MustHaveVerificationRule,
        "requirement",
        _req(verification_method=""),
        "requirements.must_have_verification",
        Severity.WARNING,
    ),
    (
        LockedSetNotEmptyRule,
        "set",
        {"id": "s1", "status": "locked", "requirement_count": 0},
        "requirements.locked_set_not_empty",
        Severity.ERROR,
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "key", "bad", "rule_id", "severity"), REQ_CASES)
async def test_requirements_rule_fires_on_a_violation(rule, key, bad, rule_id, severity):
    failed = [r for r in await _run(rule, key, bad) if not r.passed]
    assert [r.rule_id for r in failed] == [rule_id]
    assert failed[0].severity == severity
    assert "{" not in failed[0].message


@pytest.mark.asyncio
async def test_a_valid_requirement_passes_every_rule_and_exists_needs_no_value():
    for rule in (ConstraintValueUsableRule, NumericUnitRule, MustHaveVerificationRule):
        assert all(r.passed for r in await _run(rule, "requirement", _req()))
    assert all(
        r.passed
        for r in await _run(
            ConstraintValueUsableRule, "requirement", _req(constraint_type="exists", constraint_value="", unit="")
        )
    )
    assert all(r.passed for r in await _run(LockedSetNotEmptyRule, "set", {"status": "locked", "requirement_count": 3}))
    assert all(r.passed for r in await _run(LockedSetNotEmptyRule, "set", {"status": "draft", "requirement_count": 0}))


@pytest.mark.asyncio
async def test_requirements_message_is_translated():
    failed = [
        r for r in await _run(ConstraintValueUsableRule, "requirement", _req(constraint_value=""), "ru") if not r.passed
    ]
    assert "значения" in failed[0].message


def test_requirements_rule_set_is_registered():
    register_requirements_validation_rules()
    assert len({r.rule_id for r in rule_registry.get_rules_for_sets([REQUIREMENTS_RULE_SET])}) == 4


def _row(**kw):
    return {
        "row": 1,
        "property_name": "FireRating",
        "element_filter": {"ifc_class": "IfcWall"},
        "constraint_def": {"min": 30, "max": 120},
    } | kw


async def _run_bim(rule, rows, locale="en"):
    context = ValidationContext(data={"requirements": rows}, metadata={"locale": locale})
    return await rule().validate(context)


BIM_CASES = [
    (PropertyNamedRule, [_row(property_name=" ")], "bim_requirements.property_named", Severity.ERROR),
    (
        BoundsOrderedRule,
        [_row(constraint_def={"min": 120, "max": 30})],
        "bim_requirements.bounds_ordered",
        Severity.ERROR,
    ),
    (
        PatternCompilesRule,
        [_row(constraint_def={"pattern": "(["})],
        "bim_requirements.pattern_compiles",
        Severity.ERROR,
    ),
    (
        ElementFilterPresentRule,
        [_row(), _row(row=2, element_filter={})],
        "bim_requirements.element_filter_present",
        Severity.WARNING,
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule", "rows", "rule_id", "severity"), BIM_CASES)
async def test_bim_rule_fires_on_a_violation_and_passes_a_valid_batch(rule, rows, rule_id, severity):
    failed = [r for r in await _run_bim(rule, rows) if not r.passed]
    assert [r.rule_id for r in failed] == [rule_id]
    assert failed[0].severity == severity
    assert "{" not in failed[0].message
    assert all(r.passed for r in await _run_bim(rule, [_row()]))


@pytest.mark.asyncio
async def test_bim_message_is_translated():
    failed = [
        r for r in await _run_bim(BoundsOrderedRule, [_row(constraint_def={"min": 5, "max": 1})], "de") if not r.passed
    ]
    assert "Minimum" in failed[0].message


def test_bim_rule_set_is_registered():
    register_bim_requirements_validation_rules()
    assert len({r.rule_id for r in rule_registry.get_rules_for_sets([BIM_REQUIREMENTS_RULE_SET])}) == 4


# -- write points: requirements -----------------------------------------------------------------------

REQ = "/api/v1/requirements"


async def _make_set(client, h, project_id) -> str:
    resp = await client.post(f"{REQ}/", json={"project_id": project_id, "name": "Fire safety"}, headers=h)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _body(**over):
    return {
        "entity": "Wall",
        "attribute": "FireRating",
        "constraint_type": "min",
        "constraint_value": "60",
        "unit": "min",
        "priority": "must",
        "verification_method": "model_check",
    } | over


@pytest.mark.asyncio
async def test_a_requirement_without_a_usable_value_is_refused_with_its_code(client, admin_auth, project_id):
    _, h = admin_auth
    set_id = await _make_set(client, h, project_id)
    resp = await client.post(f"{REQ}/{set_id}/requirements/", json=_body(constraint_value="sixty"), headers=h)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "requirements_rules_failed"
    assert [e["rule_id"] for e in detail["errors"]] == ["requirements.constraint_value_usable"]


@pytest.mark.asyncio
async def test_a_valid_requirement_passes_and_missing_unit_is_only_a_warning(client, admin_auth, project_id):
    _, h = admin_auth
    set_id = await _make_set(client, h, project_id)
    ok = await client.post(f"{REQ}/{set_id}/requirements/", json=_body(), headers=h)
    assert ok.status_code == 201, ok.text
    assert ok.json()["validation_warnings"] == []
    warned = await client.post(f"{REQ}/{set_id}/requirements/", json=_body(unit=""), headers=h)
    assert warned.status_code == 201, warned.text
    assert [w["rule_id"] for w in warned.json()["validation_warnings"]] == ["requirements.numeric_unit"]


@pytest.mark.asyncio
async def test_the_bulk_write_refuses_the_whole_batch_when_one_row_fails(client, admin_auth, project_id):
    _, h = admin_auth
    set_id = await _make_set(client, h, project_id)
    resp = await client.post(
        f"{REQ}/{set_id}/requirements/bulk/",
        json=[_body(), _body(attribute="Thickness", constraint_value="")],
        headers=h,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["error"] == "requirements_rules_failed"
    detail = await client.get(f"{REQ}/{set_id}", headers=h)
    assert detail.status_code == 200, detail.text
    assert detail.json()["requirements"] == []


@pytest.mark.asyncio
async def test_a_legacy_requirement_with_no_value_stays_editable(client, admin_auth, project_id):
    _, h = admin_auth
    set_id = await _make_set(client, h, project_id)
    created = await client.post(f"{REQ}/{set_id}/requirements/", json=_body(), headers=h)
    req_id = created.json()["id"]
    await force_update(Requirement, req_id, constraint_value="")
    edited = await client.patch(
        f"{REQ}/{set_id}/requirements/{req_id}", json={"notes": "Clarify with the fire engineer"}, headers=h
    )
    assert edited.status_code == 200, edited.text
    worse = await client.patch(
        f"{REQ}/{set_id}/requirements/{req_id}", json={"constraint_type": "regex", "constraint_value": "(["}, headers=h
    )
    assert worse.status_code == 422, worse.text


@pytest.mark.asyncio
async def test_an_empty_set_cannot_be_locked_but_a_filled_one_can(client, admin_auth, project_id):
    _, h = admin_auth
    set_id = await _make_set(client, h, project_id)
    refused = await client.patch(f"{REQ}/{set_id}", json={"status": "locked"}, headers=h)
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["error"] == "requirements_rules_failed"
    added = await client.post(f"{REQ}/{set_id}/requirements/", json=_body(), headers=h)
    assert added.status_code == 201, added.text
    locked = await client.patch(f"{REQ}/{set_id}", json={"status": "locked"}, headers=h)
    assert locked.status_code == 200, locked.text


@pytest.mark.asyncio
async def test_a_text_import_keeps_the_good_lines_and_reports_the_refused_ones(client, admin_auth, project_id):
    _, h = admin_auth
    set_id = await _make_set(client, h, project_id)
    resp = await client.post(
        f"{REQ}/{set_id}/import/text/",
        json={"text": "Wall | FireRating | min | 60 | min\nWall | Thickness | min | thick | mm\n"},
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    stored = await client.get(f"{REQ}/{set_id}", headers=h)
    assert [r["attribute"] for r in stored.json()["requirements"]] == ["FireRating"]
    errors = resp.json()["metadata"]["parse_errors"]
    assert len(errors) == 1
    assert "requirements.constraint_value_usable" in errors[0]


# -- write points: bim_requirements -------------------------------------------------------------------

BIM = "/api/v1/bim-requirements"


@pytest.mark.asyncio
async def test_an_imported_file_with_an_inverted_range_is_refused_whole(client, admin_auth, project_id):
    _, h = admin_auth
    csv = "element,property,constraint\nIfcWall,FireRating,120 - 30\n"
    resp = await client.post(
        f"{BIM}/import/upload/?project_id={project_id}",
        files={"file": ("rules.csv", csv.encode(), "text/csv")},
        headers=h,
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "bim_requirements_rules_failed"
    assert [e["rule_id"] for e in detail["errors"]] == ["bim_requirements.bounds_ordered"]


@pytest.mark.asyncio
async def test_a_clean_file_imports_and_reports_its_warnings(client, admin_auth, project_id):
    _, h = admin_auth
    csv = "element,property,constraint\nIfcWall,FireRating,30 - 120\n"
    ok = await client.post(
        f"{BIM}/import/upload/?project_id={project_id}",
        files={"file": ("rules.csv", csv.encode(), "text/csv")},
        headers=h,
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["total_requirements"] == 1
