# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Catalogue kind ``quality_concept``: every shipped file validates and every cross-reference is checked.

Each negative case mutates the shipped neutral body in exactly one place and
asserts the validator names it, so a validator that stopped checking that
reference fails here.
"""

from __future__ import annotations

import copy
import json

import pytest

from app.modules.closeout.checklist_templates import CHECKLIST_TEMPLATES, EXTRA_SLOT_DEFS
from app.modules.defects_liability.limitation import ALL_LIMITATION_REGIMES
from app.modules.project_governance.catalogue import InvalidCatalogueError
from app.modules.project_governance.catalogue_kinds import get_catalogue_kind
from app.modules.quality_concept import vocab
from app.modules.quality_concept.catalogue import (
    CATALOGUE_DIR,
    QUALITY_CONCEPT_KIND,
    QualityConceptCatalogue,
    known_closeout_slot_keys,
    register_kinds,
    shipped_catalogue,
    validate_quality_catalogue,
)


def _neutral_body() -> dict:
    return json.loads((CATALOGUE_DIR / "neutral.json").read_text(encoding="utf-8"))


def _errors(body: dict) -> list[str]:
    return validate_quality_catalogue(QualityConceptCatalogue.model_validate(body), "shipped")


def test_every_shipped_catalogue_validates() -> None:
    register_kinds()
    kind = get_catalogue_kind(QUALITY_CONCEPT_KIND)
    shipped = kind.shipped()
    assert {c.id for c in shipped} >= {"neutral"}
    for path in sorted(CATALOGUE_DIR.glob("*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        assert _errors(body) == [], path.name


def test_neutral_content_covers_the_spec() -> None:
    cat = shipped_catalogue()
    assert [s.code for s in sorted(cat.commissioning_stages, key=lambda s: s.order)] == [
        "delivery_limit",
        "factory_test",
        "installation_check",
        "startup_prefunctional",
        "functional_test",
        "integrated_systems_test",
        "performance_proof",
    ]
    assert {r.code for r in cat.acceptance_regimes} == {
        "de_bgb",
        "de_vob_b",
        "uk_jct_practical",
        "us_aia_substantial",
        "fidic_taking_over",
    }
    assert {c.code.split(".")[1] for c in cat.requirement_categories} == {
        "standards_basis",
        "availability",
        "energy",
        "user",
        "material",
        "durability",
        "acoustics",
        "fire",
        "fm_data",
    }
    vob = cat.regime("de_vob_b")
    triggers = {d.trigger: d.working_days for d in vob.deemed_acceptance}
    assert triggers == {"completion_notice": 12, "use_start": 6}


def test_shipped_references_resolve_against_other_modules() -> None:
    cat = shipped_catalogue()
    link_kinds = {lk for e in cat.evidence_types for lk in e.fulfilled_by}
    assert link_kinds <= set(vocab.LINK_KINDS)
    assert {s.default_release_party for s in cat.commissioning_stages} <= set(vocab.PARTY_ROLES)
    assert {r.limitation_regime_code for r in cat.acceptance_regimes if r.limitation_regime_code} <= set(
        ALL_LIMITATION_REGIMES
    )
    assert {c.verification_method for c in cat.requirement_categories} <= set(vocab.VERIFICATION_METHODS)
    template_keys = {s["slot_key"] for slots in CHECKLIST_TEMPLATES.values() for s in slots}
    extra = {s["slot_key"] for s in EXTRA_SLOT_DEFS}
    assert not (extra & template_keys), "an extra slot must not redefine a template key"
    assert {k for d in cat.documentation_sets for k in d.slot_keys} <= known_closeout_slot_keys()
    for r in cat.acceptance_regimes:
        for e in r.effects:
            assert e.source_url or e.source_title, (r.code, e.effect)
        for d in r.deemed_acceptance:
            assert d.source_url or d.source_title, (r.code, d.trigger)


def test_scheme_content_is_codes_only_and_unconfirmed() -> None:
    cat = shipped_catalogue()
    for s in cat.certification_schemes:
        for lv in s.levels:
            assert lv.review_status.value == "unconfirmed", (s.code, lv.code)
    for p in cat.material_test_plans:
        assert p.review_status.value == "unconfirmed", p.code


def _mutate(path: list, value) -> dict:
    body = copy.deepcopy(_neutral_body())
    target = body
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    return body


def _index(body: dict, group: str, code: str) -> int:
    return next(i for i, x in enumerate(body[group]) if x["code"] == code)


@pytest.mark.parametrize(
    ("group", "code", "field", "value", "needle"),
    [
        ("evidence_types", "load_test", "fulfilled_by", ["cc_test_result", "spreadsheet"], "unknown link kind"),
        ("commissioning_stages", "functional_test", "default_release_party", "site_manager", "not a gate role"),
        ("acceptance_regimes", "de_bgb", "limitation_regime_code", "fr_civil", "unknown limitation regime"),
        ("requirement_categories", "quality.fire", "verification_method", "guess", "unknown verification_method"),
        ("documentation_sets", "residential", "slot_keys", ["as_built_drawings", "golden_key"], "closeout slot key"),
        ("evidence_types", "load_test", "default_deliverer", "nobody", "default_deliverer"),
    ],
)
def test_cross_reference_errors_are_named(group, code, field, value, needle) -> None:
    body = _neutral_body()
    body = _mutate([group, _index(body, group, code), field], value)
    errors = _errors(body)
    assert any(needle in e for e in errors), errors


def test_effect_without_source_is_refused() -> None:
    body = _neutral_body()
    i = _index(body, "acceptance_regimes", "de_vob_b")
    body["acceptance_regimes"][i]["effects"][0]["source_url"] = None
    body["acceptance_regimes"][i]["effects"][0]["source_title"] = None
    assert any("without source_url" in e for e in _errors(body))


def test_unknown_precondition_predicate_is_refused() -> None:
    body = _neutral_body()
    i = _index(body, "commissioning_stages", "functional_test")
    body["commissioning_stages"][i]["default_preconditions"].append({"code": "custom_python", "params": {}})
    assert any("unknown precondition" in e for e in _errors(body))


def test_verified_fact_needs_source() -> None:
    body = _neutral_body()
    i = _index(body, "acceptance_regimes", "de_bgb")
    body["acceptance_regimes"][i]["source_url"] = None
    assert any("verified without source_url" in e for e in _errors(body))


def test_levels_must_ascend() -> None:
    body = _neutral_body()
    i = _index(body, "certification_schemes", "dgnb_new_construction")
    body["certification_schemes"][i]["levels"][1]["min_score"] = "10"
    assert any("ascend" in e for e in _errors(body))


def test_duplicate_stage_order_is_refused() -> None:
    body = _neutral_body()
    body["commissioning_stages"][1]["order"] = body["commissioning_stages"][0]["order"]
    assert any("duplicate order" in e for e in _errors(body))


def test_kind_parse_raises_invalid_catalogue() -> None:
    register_kinds()
    body = _neutral_body()
    body["evidence_types"][0]["fulfilled_by"] = ["telepathy"]
    with pytest.raises(InvalidCatalogueError):
        get_catalogue_kind(QUALITY_CONCEPT_KIND).parse_body(body, source="tenant", origin="test")
