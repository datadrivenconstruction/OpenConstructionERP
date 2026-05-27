"""Tests for ``app.modules.bim_requirements.rule_runtime``.

Covers all 11 operators, multi-predicate selectors, mustache-style
templating, missing-property semantics, pack-level aggregation, and
unicode safety.
"""

from __future__ import annotations

from typing import Any

from app.modules.bim_requirements.rule_runtime import (
    evaluate_predicate,
    evaluate_rule,
    evaluate_rule_pack,
    matches_selector,
    render_message,
)
from app.modules.bim_requirements.yaml_loader import (
    Predicate,
    Rule,
    RulePack,
    Selector,
    load_rule_pack,
)


def _pred(op: str, value: Any = None, key: str = "X") -> Predicate:
    return Predicate(key=key, op=op, value=value)


# ── Operators ──────────────────────────────────────────────────────────────


def test_op_eq() -> None:
    assert evaluate_predicate(_pred("eq", 5), 5) is True
    assert evaluate_predicate(_pred("eq", 5), "5") is True  # numeric coercion
    assert evaluate_predicate(_pred("eq", "F90"), "F90") is True
    assert evaluate_predicate(_pred("eq", "F90"), "F60") is False


def test_op_neq() -> None:
    assert evaluate_predicate(_pred("neq", 5), 6) is True
    assert evaluate_predicate(_pred("neq", 5), 5) is False


def test_op_gt_gte_lt_lte() -> None:
    assert evaluate_predicate(_pred("gt", 1.5), 2.0) is True
    assert evaluate_predicate(_pred("gt", 1.5), 1.5) is False
    assert evaluate_predicate(_pred("gte", 1.5), 1.5) is True
    assert evaluate_predicate(_pred("lt", 1.5), 1.4) is True
    assert evaluate_predicate(_pred("lt", 1.5), 1.5) is False
    assert evaluate_predicate(_pred("lte", 1.5), 1.5) is True


def test_op_gt_non_numeric_returns_false() -> None:
    """Comparing a string against a numeric threshold must not blow up."""
    assert evaluate_predicate(_pred("gt", 1.0), "abc") is False
    assert evaluate_predicate(_pred("gte", 1.0), None) is False


def test_op_in() -> None:
    pred = _pred("in", ["F30", "F60", "F90"])
    assert evaluate_predicate(pred, "F60") is True
    assert evaluate_predicate(pred, "F120") is False


def test_op_contains_on_string_and_list() -> None:
    assert evaluate_predicate(_pred("contains", "concrete"), "reinforced concrete") is True
    assert evaluate_predicate(_pred("contains", "tag1"), ["tag1", "tag2"]) is True
    assert evaluate_predicate(_pred("contains", "missing"), ["a", "b"]) is False


def test_op_regex_matches_and_fails() -> None:
    pred = _pred("regex", r"^[A-Z]{2}\.[0-9]{2}\.[0-9]{3}$")
    assert evaluate_predicate(pred, "OR.02.001") is True
    assert evaluate_predicate(pred, "or.02.001") is False
    assert evaluate_predicate(pred, "OR-02-001") is False


def test_op_exists() -> None:
    assert evaluate_predicate(_pred("exists", True), "anything") is True
    assert evaluate_predicate(_pred("exists", True), None) is False
    assert evaluate_predicate(_pred("exists", True), "") is False
    # `exists: false` flips the polarity (must NOT exist).
    assert evaluate_predicate(_pred("exists", False), None) is True
    assert evaluate_predicate(_pred("exists", False), "value") is False


def test_op_between() -> None:
    pred = _pred("between", [10, 20])
    assert evaluate_predicate(pred, 10) is True
    assert evaluate_predicate(pred, 15) is True
    assert evaluate_predicate(pred, 20) is True
    assert evaluate_predicate(pred, 9.99) is False
    assert evaluate_predicate(pred, 20.01) is False


def test_boolean_not_treated_as_number_for_gt() -> None:
    """Defensive: True/False must NOT silently satisfy numeric comparisons."""
    assert evaluate_predicate(_pred("gt", 0), True) is False
    assert evaluate_predicate(_pred("eq", True), True) is True


# ── Templating ─────────────────────────────────────────────────────────────


def test_render_message_substitutes_property() -> None:
    element = {"properties": {"Width": 1.2}}
    msg = render_message("Width {{Width}} m below 1.5 m.", element)
    assert msg == "Width 1.2 m below 1.5 m."


def test_render_message_handles_missing_property() -> None:
    element = {"properties": {}}
    msg = render_message("Width {{Width}} below limit.", element)
    assert msg == "Width <missing> below limit."


def test_render_message_unicode_safe() -> None:
    element = {"properties": {"Name": "Büro 2.OG — Süd"}}
    msg = render_message("Space '{{Name}}' breaks pattern.", element)
    assert "Büro 2.OG — Süd" in msg


def test_render_message_empty_template_is_empty() -> None:
    assert render_message("", {"properties": {"X": 1}}) == ""


# ── Selectors ──────────────────────────────────────────────────────────────


def test_selector_ifc_class_only() -> None:
    sel = Selector(ifc_class="IfcWall")
    assert matches_selector(sel, {"ifc_class": "IfcWall"}) is True
    assert matches_selector(sel, {"ifc_class": "IfcSlab"}) is False
    assert matches_selector(sel, {"ifc_class": "ifcwall"}) is True  # case-insensitive


def test_selector_anded_predicates() -> None:
    """Multiple property predicates must all hold (logical AND)."""
    sel = Selector(
        ifc_class="IfcWall",
        properties=[
            _pred("eq", False, "IsExternal"),
            _pred("exists", True, "FireRating"),
        ],
    )
    elem_ok = {
        "ifc_class": "IfcWall",
        "properties": {"IsExternal": False, "FireRating": "F90"},
    }
    elem_external = {
        "ifc_class": "IfcWall",
        "properties": {"IsExternal": True, "FireRating": "F90"},
    }
    elem_no_rating = {
        "ifc_class": "IfcWall",
        "properties": {"IsExternal": False},
    }
    assert matches_selector(sel, elem_ok) is True
    assert matches_selector(sel, elem_external) is False
    assert matches_selector(sel, elem_no_rating) is False


def test_selector_classification_wildcard() -> None:
    sel = Selector(classification={"din276": "330*"})
    assert matches_selector(sel, {"classification": {"din276": "330.1"}}) is True
    assert matches_selector(sel, {"classification": {"din276": "350"}}) is False


# ── Per-rule evaluation ────────────────────────────────────────────────────


def test_evaluate_rule_passes() -> None:
    rule = Rule.model_validate(
        {
            "id": "ok",
            "name": "ok",
            "selector": {"ifc_class": "IfcSpace"},
            "assertion": {"property": {"key": "Width", "op": "gte", "value": 1.5}},
        }
    )
    elem = {"id": "e1", "ifc_class": "IfcSpace", "properties": {"Width": 1.6}}
    result = evaluate_rule(rule, elem)
    assert result is not None
    assert result.passed is True
    assert result.message is None


def test_evaluate_rule_fails_with_templated_message() -> None:
    rule = Rule.model_validate(
        {
            "id": "narrow",
            "name": "narrow corridor",
            "selector": {"ifc_class": "IfcSpace"},
            "assertion": {"property": {"key": "Width", "op": "gte", "value": 1.5}},
            "failure_message": "Width {{Width}} m below 1.5 m.",
        }
    )
    elem = {"id": "e1", "ifc_class": "IfcSpace", "properties": {"Width": 1.2}}
    result = evaluate_rule(rule, elem)
    assert result is not None
    assert result.passed is False
    assert result.message == "Width 1.2 m below 1.5 m."
    assert result.evidence == {"property": "Width", "actual": 1.2, "expected": 1.5}


def test_evaluate_rule_skips_non_matching_element() -> None:
    """Returns None when the selector does not match."""
    rule = Rule.model_validate(
        {
            "id": "x",
            "name": "x",
            "selector": {"ifc_class": "IfcSpace"},
            "assertion": {"property": {"key": "Width", "op": "gte", "value": 1.5}},
        }
    )
    elem = {"id": "e1", "ifc_class": "IfcWall", "properties": {"Width": 1.0}}
    assert evaluate_rule(rule, elem) is None


def test_evaluate_rule_set_vs_set_fails_when_clearance_too_small() -> None:
    rule = Rule.model_validate(
        {
            "id": "clr",
            "name": "clearance",
            "rule_type": "set_vs_set",
            "selector": {"ifc_class": "IfcPipeSegment"},
            "assertion": {
                "set_vs_set": {
                    "other_selector": {"ifc_class": "IfcBeam"},
                    "metric": "clearance",
                    "property": {"key": "ClearanceToStructure", "op": "gte", "value": 0.1},
                },
            },
            "failure_message": "Pipe {{id}} too close.",
        }
    )
    pipe = {"id": "p1", "ifc_class": "IfcPipeSegment", "properties": {"ClearanceToStructure": 0.05}}
    beam = {"id": "b1", "ifc_class": "IfcBeam"}
    result = evaluate_rule(rule, pipe, other_elements=[beam])
    assert result is not None
    assert result.passed is False
    assert "p1" in (result.message or "")


def test_evaluate_rule_set_vs_set_passes_when_no_other_set_members() -> None:
    """When the other selector matches nothing, the rule trivially passes."""
    rule = Rule.model_validate(
        {
            "id": "clr",
            "name": "clearance",
            "rule_type": "set_vs_set",
            "selector": {"ifc_class": "IfcPipeSegment"},
            "assertion": {
                "set_vs_set": {
                    "other_selector": {"ifc_class": "IfcBeam"},
                    "metric": "clearance",
                    "property": {"key": "ClearanceToStructure", "op": "gte", "value": 0.1},
                },
            },
        }
    )
    pipe = {"id": "p1", "ifc_class": "IfcPipeSegment", "properties": {"ClearanceToStructure": 0.05}}
    # No beams at all in the model.
    result = evaluate_rule(rule, pipe, other_elements=[])
    assert result is not None
    assert result.passed is True


# ── Pack aggregation ──────────────────────────────────────────────────────


def _corridor_pack() -> RulePack:
    return load_rule_pack(
        "<inline>",
        text=(
            "schema_version: '1.0'\n"
            "pack: { id: corridor, name: corridor }\n"
            "rules:\n"
            "  - id: width\n"
            "    name: corridor width\n"
            "    selector:\n"
            "      ifc_class: IfcSpace\n"
            "      properties:\n"
            "        - { key: SpaceType, op: eq, value: Corridor }\n"
            "    assertion:\n"
            "      property: { key: Width, op: gte, value: 1.5 }\n"
            "    failure_message: 'Width {{Width}} m below 1.5 m.'\n"
        ),
    )


def test_pack_summary_counts() -> None:
    pack = _corridor_pack()
    elements = [
        {"id": "c1", "ifc_class": "IfcSpace", "properties": {"SpaceType": "Corridor", "Width": 1.8}},  # pass
        {"id": "c2", "ifc_class": "IfcSpace", "properties": {"SpaceType": "Corridor", "Width": 1.2}},  # fail
        {"id": "r1", "ifc_class": "IfcSpace", "properties": {"SpaceType": "Office", "Width": 0.5}},  # n/a
        {"id": "w1", "ifc_class": "IfcWall"},  # n/a
    ]
    result = evaluate_rule_pack(pack, elements)
    assert result.pack_id == "corridor"
    assert result.total_elements == 4
    assert result.passed == 1
    assert result.failed == 1
    assert result.not_applicable == 2
    assert len(result.results) == 2  # only applicable pairs emit rows


def test_pack_summary_on_empty_input() -> None:
    pack = _corridor_pack()
    result = evaluate_rule_pack(pack, [])
    assert result.total_elements == 0
    assert result.passed == result.failed == result.not_applicable == 0


# ── Defensive ──────────────────────────────────────────────────────────────


def test_unicode_property_keys_and_values() -> None:
    """The runtime must not corrupt non-ASCII property values."""
    rule = Rule.model_validate(
        {
            "id": "umlaut",
            "name": "umlaut",
            "selector": {"ifc_class": "IfcSpace"},
            "assertion": {"property": {"key": "Name", "op": "regex", "value": r"^Büro"}},
        }
    )
    elem = {"id": "e1", "ifc_class": "IfcSpace", "properties": {"Name": "Büro 2.OG"}}
    result = evaluate_rule(rule, elem)
    assert result is not None
    assert result.passed is True


def test_evaluate_predicate_unknown_op_returns_false() -> None:
    """A predicate whose op slips past validation (shouldn't, but defence in depth)."""
    pred = Predicate.model_construct(key="X", op="bogus", value=1)
    assert evaluate_predicate(pred, 1) is False
