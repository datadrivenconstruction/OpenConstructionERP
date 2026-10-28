"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the Forms conditional (branching) logic engine.

Two pure modules are exercised together:

* ``app.modules.forms.conditional`` - the evaluator (``evaluate_visibility``), the
  static checker (``collect_rule_issues``) and the persistence sanitiser
  (``sanitize_expr``);
* ``app.modules.forms.validation`` - to prove the branching logic is wired into
  the real submission / template validation path.

Both are pure (stdlib only, no ORM or app imports), so they are loaded here
directly from their file paths. That keeps the test independent of the FastAPI
dependency graph (which boots a database on import) while still exercising the
real modules, identically here and in CI.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_FORMS_DIR = Path(__file__).resolve().parents[2] / "app" / "modules" / "forms"


def _load(module_name: str, filename: str):  # noqa: ANN202 - dynamic module handle
    path = _FORMS_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec: dataclasses under ``from __future__ import
    # annotations`` resolve field types via ``sys.modules[cls.__module__]``.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


conditional = _load("forms_conditional_under_test", "conditional.py")
validation = _load("forms_validation_under_test", "validation.py")

evaluate_visibility = conditional.evaluate_visibility
collect_rule_issues = conditional.collect_rule_issues
sanitize_expr = conditional.sanitize_expr


def _codes(issues) -> set[str]:  # noqa: ANN001
    return {i.code for i in issues}


def _field(key: str, ftype: str = "short_text", **extra) -> dict:  # noqa: ANN003
    return {"key": key, "type": ftype, "label": key.replace("_", " ").title(), "required": False, **extra}


# ── evaluate_visibility: baseline ────────────────────────────────────────────


def test_no_rules_all_visible_required_follows_static_flag() -> None:
    fields = [
        _field("a", required=True),
        _field("b", required=False),
        {"key": "sec", "type": "section", "label": "Head"},
    ]
    state = evaluate_visibility(fields, {})
    assert state["a"] == {"visible": True, "required": True}
    assert state["b"] == {"visible": True, "required": False}
    # Layout fields are covered too (a section can be branched on).
    assert state["sec"] == {"visible": True, "required": False}


def test_evaluate_visibility_tolerates_none_answers() -> None:
    fields = [_field("a")]
    assert evaluate_visibility(fields, None) == {"a": {"visible": True, "required": False}}


# ── visible_if ───────────────────────────────────────────────────────────────


def test_visible_if_true_shows_field() -> None:
    fields = [
        _field("has_defect", "single_choice", options=["Yes", "No"]),
        _field("defect_note", visible_if={"field": "has_defect", "op": "eq", "value": "Yes"}),
    ]
    shown = evaluate_visibility(fields, {"has_defect": "Yes"})
    assert shown["defect_note"]["visible"] is True


def test_visible_if_false_hides_field() -> None:
    fields = [
        _field("has_defect", "single_choice", options=["Yes", "No"]),
        _field("defect_note", visible_if={"field": "has_defect", "op": "eq", "value": "Yes"}),
    ]
    hidden = evaluate_visibility(fields, {"has_defect": "No"})
    assert hidden["defect_note"]["visible"] is False
    assert hidden["defect_note"]["required"] is False


def test_hidden_field_is_never_required_even_when_static_required() -> None:
    fields = [
        _field("has_defect", "single_choice", options=["Yes", "No"]),
        _field(
            "defect_note",
            required=True,
            visible_if={"field": "has_defect", "op": "eq", "value": "Yes"},
        ),
    ]
    hidden = evaluate_visibility(fields, {"has_defect": "No"})
    assert hidden["defect_note"] == {"visible": False, "required": False}


# ── required_if ──────────────────────────────────────────────────────────────


def test_required_if_enforced_when_active() -> None:
    fields = [
        _field("result", "pass_fail_na"),
        _field("corrective_action", required_if={"field": "result", "op": "eq", "value": "fail"}),
    ]
    active = evaluate_visibility(fields, {"result": "fail"})
    assert active["corrective_action"] == {"visible": True, "required": True}


def test_required_if_skipped_when_inactive() -> None:
    fields = [
        _field("result", "pass_fail_na"),
        _field("corrective_action", required_if={"field": "result", "op": "eq", "value": "fail"}),
    ]
    inactive = evaluate_visibility(fields, {"result": "pass"})
    assert inactive["corrective_action"] == {"visible": True, "required": False}


def test_required_if_never_weakens_a_static_required_field() -> None:
    # OR semantics: a statically-required field stays required even when the
    # required_if condition is false.
    fields = [
        _field("result", "pass_fail_na"),
        _field(
            "corrective_action",
            required=True,
            required_if={"field": "result", "op": "eq", "value": "fail"},
        ),
    ]
    assert evaluate_visibility(fields, {"result": "pass"})["corrective_action"]["required"] is True


# ── nested all / any groups ──────────────────────────────────────────────────


def test_nested_all_group_requires_every_subrule() -> None:
    fields = [
        _field("role", "single_choice", options=["op", "sub"]),
        _field("height", "number"),
        _field(
            "permit",
            visible_if={
                "all": [
                    {"field": "role", "op": "eq", "value": "op"},
                    {"field": "height", "op": "gt", "value": 2},
                ]
            },
        ),
    ]
    assert evaluate_visibility(fields, {"role": "op", "height": "3"})["permit"]["visible"] is True
    assert evaluate_visibility(fields, {"role": "op", "height": "1"})["permit"]["visible"] is False
    assert evaluate_visibility(fields, {"role": "sub", "height": "3"})["permit"]["visible"] is False


def test_nested_any_group_requires_one_subrule() -> None:
    fields = [
        _field("a", "single_choice", options=["x", "y"]),
        _field("b", "single_choice", options=["x", "y"]),
        _field(
            "extra",
            visible_if={
                "any": [
                    {"field": "a", "op": "eq", "value": "x"},
                    {"field": "b", "op": "eq", "value": "x"},
                ]
            },
        ),
    ]
    assert evaluate_visibility(fields, {"a": "y", "b": "x"})["extra"]["visible"] is True
    assert evaluate_visibility(fields, {"a": "y", "b": "y"})["extra"]["visible"] is False


def test_deeply_nested_all_of_any() -> None:
    fields = [
        _field("a", "single_choice", options=["1", "2"]),
        _field("b", "single_choice", options=["1", "2"]),
        _field("c", "single_choice", options=["1", "2"]),
        _field(
            "target",
            visible_if={
                "all": [
                    {"any": [{"field": "a", "op": "eq", "value": "1"}, {"field": "b", "op": "eq", "value": "1"}]},
                    {"field": "c", "op": "eq", "value": "2"},
                ]
            },
        ),
    ]
    assert evaluate_visibility(fields, {"a": "1", "b": "2", "c": "2"})["target"]["visible"] is True
    assert evaluate_visibility(fields, {"a": "2", "b": "2", "c": "2"})["target"]["visible"] is False
    assert evaluate_visibility(fields, {"a": "1", "b": "1", "c": "1"})["target"]["visible"] is False


# ── operators ────────────────────────────────────────────────────────────────


def test_in_and_not_in_with_lists() -> None:
    fields = [
        _field("card", "single_choice", options=["Yes", "No", "Exempt"]),
        _field("why_no", visible_if={"field": "card", "op": "in", "value": ["No", "Exempt"]}),
        _field("congrats", visible_if={"field": "card", "op": "not_in", "value": ["No", "Exempt"]}),
    ]
    on_no = evaluate_visibility(fields, {"card": "No"})
    assert on_no["why_no"]["visible"] is True
    assert on_no["congrats"]["visible"] is False

    on_yes = evaluate_visibility(fields, {"card": "Yes"})
    assert on_yes["why_no"]["visible"] is False
    assert on_yes["congrats"]["visible"] is True


def test_in_matches_any_item_of_a_multi_choice_answer() -> None:
    fields = [
        _field("hazards", "multi_choice", options=["Dust", "Noise", "Heat"]),
        _field("rpe", visible_if={"field": "hazards", "op": "in", "value": ["Dust"]}),
    ]
    assert evaluate_visibility(fields, {"hazards": ["Noise", "Dust"]})["rpe"]["visible"] is True
    assert evaluate_visibility(fields, {"hazards": ["Noise"]})["rpe"]["visible"] is False


def test_empty_and_not_empty() -> None:
    fields = [
        _field("notes", "long_text"),
        _field("why_blank", visible_if={"field": "notes", "op": "empty"}),
        _field("thanks", visible_if={"field": "notes", "op": "not_empty"}),
    ]
    blank = evaluate_visibility(fields, {"notes": "   "})
    assert blank["why_blank"]["visible"] is True
    assert blank["thanks"]["visible"] is False

    filled = evaluate_visibility(fields, {"notes": "cracked"})
    assert filled["why_blank"]["visible"] is False
    assert filled["thanks"]["visible"] is True


def test_empty_treats_unticked_checkbox_as_blank() -> None:
    fields = [
        _field("ack", "checkbox"),
        _field("chase", visible_if={"field": "ack", "op": "empty"}),
    ]
    assert evaluate_visibility(fields, {"ack": False})["chase"]["visible"] is True
    assert evaluate_visibility(fields, {"ack": True})["chase"]["visible"] is False


def test_numeric_comparisons() -> None:
    fields = [
        _field("slump", "number"),
        _field("gt", visible_if={"field": "slump", "op": "gt", "value": 100}),
        _field("gte", visible_if={"field": "slump", "op": "gte", "value": 100}),
        _field("lt", visible_if={"field": "slump", "op": "lt", "value": 100}),
        _field("lte", visible_if={"field": "slump", "op": "lte", "value": 100}),
    ]
    at = evaluate_visibility(fields, {"slump": "100"})
    assert at["gt"]["visible"] is False
    assert at["gte"]["visible"] is True
    assert at["lt"]["visible"] is False
    assert at["lte"]["visible"] is True


def test_numeric_comparison_against_non_numeric_answer_is_false() -> None:
    fields = [
        _field("slump", "number"),
        _field("hi", visible_if={"field": "slump", "op": "gt", "value": 10}),
    ]
    assert evaluate_visibility(fields, {"slump": "soft"})["hi"]["visible"] is False


def test_neq_operator() -> None:
    fields = [
        _field("status", "single_choice", options=["ok", "bad"]),
        _field("explain", visible_if={"field": "status", "op": "neq", "value": "ok"}),
    ]
    assert evaluate_visibility(fields, {"status": "bad"})["explain"]["visible"] is True
    assert evaluate_visibility(fields, {"status": "ok"})["explain"]["visible"] is False


def test_eq_matches_checkbox_boolean() -> None:
    fields = [
        _field("hot_works", "checkbox"),
        _field("permit_no", visible_if={"field": "hot_works", "op": "eq", "value": True}),
    ]
    assert evaluate_visibility(fields, {"hot_works": True})["permit_no"]["visible"] is True
    assert evaluate_visibility(fields, {"hot_works": False})["permit_no"]["visible"] is False


def test_eq_matches_number_across_string_and_int() -> None:
    fields = [
        _field("count", "number"),
        _field("single", visible_if={"field": "count", "op": "eq", "value": 1}),
    ]
    assert evaluate_visibility(fields, {"count": "1"})["single"]["visible"] is True
    assert evaluate_visibility(fields, {"count": 1})["single"]["visible"] is True
    assert evaluate_visibility(fields, {"count": "2"})["single"]["visible"] is False


# ── cascade: a hidden parent voids the answer its dependants read ─────────────


def test_hidden_parent_cascades_to_children() -> None:
    fields = [
        _field("owns_car", "single_choice", options=["Yes", "No"]),
        # make/model only shown when they own a car
        _field("make", visible_if={"field": "owns_car", "op": "eq", "value": "Yes"}),
        # colour depends on make being answered - but make is hidden, so its
        # answer must be treated as blank and colour must collapse too.
        _field("colour", visible_if={"field": "make", "op": "not_empty"}),
    ]
    # A stale make answer is present, but owns_car=No hides make, so colour hides.
    state = evaluate_visibility(fields, {"owns_car": "No", "make": "Ford"})
    assert state["make"]["visible"] is False
    assert state["colour"]["visible"] is False

    shown = evaluate_visibility(fields, {"owns_car": "Yes", "make": "Ford"})
    assert shown["make"]["visible"] is True
    assert shown["colour"]["visible"] is True


# ── guards: missing ref, self / cycle, unknown operator ──────────────────────


def test_missing_referenced_field_makes_condition_false() -> None:
    fields = [
        _field("shown_by_ghost", visible_if={"field": "ghost", "op": "eq", "value": "x"}),
        _field("required_by_ghost", required_if={"field": "ghost", "op": "not_empty"}),
    ]
    state = evaluate_visibility(fields, {"ghost": "anything"})
    # ``ghost`` is not a field in this form -> both rules resolve false.
    assert state["shown_by_ghost"]["visible"] is False
    assert state["required_by_ghost"]["required"] is False


def test_self_reference_does_not_crash() -> None:
    fields = [_field("loop", visible_if={"field": "loop", "op": "not_empty"})]
    state = evaluate_visibility(fields, {"loop": "value"})
    assert set(state) == {"loop"}
    assert isinstance(state["loop"]["visible"], bool)


def test_reference_cycle_is_broken_not_followed() -> None:
    fields = [
        _field("a", visible_if={"field": "b", "op": "not_empty"}),
        _field("b", visible_if={"field": "a", "op": "not_empty"}),
    ]
    # Must terminate and return a state for both fields rather than recursing.
    state = evaluate_visibility(fields, {"a": "x", "b": "y"})
    assert set(state) == {"a", "b"}
    assert isinstance(state["a"]["visible"], bool)
    assert isinstance(state["b"]["visible"], bool)


def test_unknown_operator_at_runtime_defaults_to_safe_shown() -> None:
    fields = [_field("x", visible_if={"field": "x", "op": "wormhole", "value": 1})]
    # A broken rule must never hide a field (data loss) - default is to show.
    assert evaluate_visibility(fields, {"x": "1"})["x"]["visible"] is True


def test_malformed_expression_shapes_do_not_crash() -> None:
    for bad in ("not-a-dict", {"all": "nope"}, {}, {"any": [{"broken": True}]}):
        fields = [_field("x", visible_if=bad)]
        state = evaluate_visibility(fields, {"x": "1"})
        assert isinstance(state["x"]["visible"], bool)


# ── collect_rule_issues: static rejection ────────────────────────────────────


def test_valid_rules_report_no_issues() -> None:
    fields = [
        _field("a", "single_choice", options=["Yes", "No"]),
        _field("b", visible_if={"field": "a", "op": "eq", "value": "Yes"}),
        _field("c", required_if={"any": [{"field": "a", "op": "in", "value": ["Yes"]}]}),
    ]
    assert collect_rule_issues(fields) == []


def test_unknown_operator_is_rejected() -> None:
    fields = [
        _field("a"),
        _field("b", visible_if={"field": "a", "op": "wormhole", "value": 1}),
    ]
    assert "unknown_operator" in _codes(collect_rule_issues(fields))


def test_unknown_referenced_field_is_rejected() -> None:
    fields = [_field("b", visible_if={"field": "ghost", "op": "eq", "value": 1})]
    assert "unknown_condition_ref" in _codes(collect_rule_issues(fields))


def test_self_reference_is_rejected() -> None:
    fields = [_field("loop", visible_if={"field": "loop", "op": "not_empty"})]
    assert "self_reference" in _codes(collect_rule_issues(fields))


def test_malformed_rule_missing_field_is_rejected() -> None:
    fields = [_field("b", visible_if={"op": "not_empty"})]
    assert "malformed_rule" in _codes(collect_rule_issues(fields))


def test_in_operator_without_list_value_is_rejected() -> None:
    fields = [
        _field("a", "single_choice", options=["Yes", "No"]),
        _field("b", visible_if={"field": "a", "op": "in", "value": "Yes"}),
    ]
    assert "condition_needs_list" in _codes(collect_rule_issues(fields))


def test_group_must_be_a_list() -> None:
    fields = [_field("b", visible_if={"all": {"field": "b", "op": "eq"}})]
    assert "malformed_rule" in _codes(collect_rule_issues(fields))


def test_over_deep_nesting_is_rejected() -> None:
    expr: dict = {"field": "a", "op": "not_empty"}
    for _ in range(conditional.MAX_RULE_DEPTH + 2):
        expr = {"all": [expr]}
    fields = [_field("a"), _field("b", visible_if=expr)]
    assert "rule_too_deep" in _codes(collect_rule_issues(fields))


# ── sanitize_expr ────────────────────────────────────────────────────────────


def test_sanitize_strips_none_keys_and_trims() -> None:
    raw = {"field": "  card ", "op": " eq ", "value": "No", "all": None, "any": None}
    assert sanitize_expr(raw) == {"field": "card", "op": "eq", "value": "No"}


def test_sanitize_keeps_group_and_drops_empties() -> None:
    raw = {"any": [{"field": "a", "op": "eq", "value": 1}, "junk", {}]}
    assert sanitize_expr(raw) == {"any": [{"field": "a", "op": "eq", "value": 1}]}


def test_sanitize_non_dict_and_empty_become_none() -> None:
    assert sanitize_expr(None) is None
    assert sanitize_expr("nope") is None
    assert sanitize_expr({}) is None
    assert sanitize_expr({"all": []}) is None


def test_sanitize_keeps_falsey_scalar_values() -> None:
    assert sanitize_expr({"field": "x", "op": "eq", "value": False}) == {"field": "x", "op": "eq", "value": False}
    assert sanitize_expr({"field": "x", "op": "eq", "value": 0}) == {"field": "x", "op": "eq", "value": 0}


# ── integration with validation.py ───────────────────────────────────────────


def test_normalize_carries_conditional_rules() -> None:
    raw = [
        {"type": "single_choice", "label": "Card", "options": ["Yes", "No"]},
        {
            "type": "short_text",
            "label": "Why not",
            "visible_if": {"field": "card", "op": "eq", "value": "No", "all": None},
            "required_if": {"field": "card", "op": "eq", "value": "No"},
        },
    ]
    clean = validation.normalize_fields(raw)
    assert clean[1]["visible_if"] == {"field": "card", "op": "eq", "value": "No"}
    assert clean[1]["required_if"] == {"field": "card", "op": "eq", "value": "No"}


def test_normalize_drops_absent_rules() -> None:
    clean = validation.normalize_fields([{"type": "short_text", "label": "Plain"}])
    assert "visible_if" not in clean[0]
    assert "required_if" not in clean[0]


def test_validate_template_rejects_unknown_operator() -> None:
    fields = validation.normalize_fields(
        [
            {"type": "single_choice", "label": "Card", "options": ["Yes", "No"]},
            {"type": "short_text", "label": "Why", "visible_if": {"field": "card", "op": "wormhole", "value": "No"}},
        ]
    )
    assert "unknown_operator" in _codes(validation.validate_template_fields(fields))


def test_validate_template_accepts_well_formed_rules() -> None:
    fields = validation.normalize_fields(
        [
            {"type": "single_choice", "label": "Card", "options": ["Yes", "No"]},
            {"type": "short_text", "label": "Why", "visible_if": {"field": "card", "op": "eq", "value": "No"}},
        ]
    )
    assert validation.validate_template_fields(fields) == []


def test_submission_skips_hidden_required_field() -> None:
    fields = validation.normalize_fields(
        [
            {"type": "single_choice", "label": "Defect", "options": ["Yes", "No"], "required": True},
            {
                "type": "short_text",
                "label": "Describe",
                "required": True,
                "visible_if": {"field": "defect", "op": "eq", "value": "Yes"},
            },
        ]
    )
    # Defect = No -> describe is hidden -> its absence must not block completion.
    check = validation.validate_submission_answers(fields, {"defect": "No"})
    assert check.is_complete
    assert check.total_required == 1  # only ``defect`` counts while describe is hidden


def test_submission_enforces_visible_required_field() -> None:
    fields = validation.normalize_fields(
        [
            {"type": "single_choice", "label": "Defect", "options": ["Yes", "No"], "required": True},
            {
                "type": "short_text",
                "label": "Describe",
                "required": True,
                "visible_if": {"field": "defect", "op": "eq", "value": "Yes"},
            },
        ]
    )
    # Defect = Yes -> describe is shown and required, and it is missing.
    check = validation.validate_submission_answers(fields, {"defect": "Yes"})
    assert not check.is_complete
    assert "required_missing" in _codes(check.issues)
    assert check.total_required == 2


def test_submission_required_if_switches_a_field_on() -> None:
    fields = validation.normalize_fields(
        [
            {"type": "pass_fail_na", "label": "Result", "required": True},
            {
                "type": "long_text",
                "label": "Corrective action",
                "required_if": {"field": "result", "op": "eq", "value": "fail"},
            },
        ]
    )
    missing = validation.validate_submission_answers(fields, {"result": "fail"})
    assert not missing.is_complete
    assert "required_missing" in _codes(missing.issues)

    ok = validation.validate_submission_answers(fields, {"result": "fail", "corrective_action": "Re-do the weld"})
    assert ok.is_complete

    # When the trigger is not met the field is optional and may be left blank.
    inactive = validation.validate_submission_answers(fields, {"result": "pass"})
    assert inactive.is_complete


def test_submission_ignores_stale_value_on_hidden_field() -> None:
    fields = validation.normalize_fields(
        [
            {"type": "single_choice", "label": "Defect", "options": ["Yes", "No"], "required": True},
            {
                "type": "single_choice",
                "label": "Severity",
                "options": ["Low", "High"],
                "visible_if": {"field": "defect", "op": "eq", "value": "Yes"},
            },
        ]
    )
    # Severity carries an invalid leftover value, but it is hidden -> ignored.
    check = validation.validate_submission_answers(fields, {"defect": "No", "severity": "Bogus"})
    assert check.is_complete
