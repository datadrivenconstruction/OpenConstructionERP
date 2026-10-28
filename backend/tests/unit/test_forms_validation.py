"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the Forms & Checklists validation engine.

The engine (``app.modules.forms.validation``) is pure - stdlib only, no ORM or
app imports - so it is loaded here directly from its file path. That keeps the
test independent of the FastAPI dependency graph (which does not import cleanly
on a bare interpreter) while still exercising the real module, and it runs
identically here and in CI.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_VALIDATION_PATH = Path(__file__).resolve().parents[2] / "app" / "modules" / "forms" / "validation.py"
_spec = importlib.util.spec_from_file_location("forms_validation", _VALIDATION_PATH)
assert _spec and _spec.loader
validation = importlib.util.module_from_spec(_spec)
# Register before exec: dataclasses under ``from __future__ import annotations``
# resolve field types via ``sys.modules[cls.__module__]``, which must exist.
sys.modules["forms_validation"] = validation
_spec.loader.exec_module(validation)


def _codes(issues) -> set[str]:
    return {i.code for i in issues}


# ── normalize_fields ─────────────────────────────────────────────────────────


def test_normalize_derives_keys_from_label() -> None:
    fields = validation.normalize_fields([{"type": "short_text", "label": "Worker Name"}])
    assert fields[0]["key"] == "worker_name"
    assert fields[0]["required"] is False


def test_normalize_dedupes_colliding_keys() -> None:
    fields = validation.normalize_fields(
        [
            {"type": "short_text", "label": "Notes"},
            {"type": "long_text", "label": "Notes"},
        ]
    )
    assert [f["key"] for f in fields] == ["notes", "notes_2"]


def test_normalize_blank_label_falls_back_to_positional_key() -> None:
    fields = validation.normalize_fields([{"type": "short_text", "label": "   "}])
    assert fields[0]["key"] == "field_1"


def test_normalize_forces_layout_field_not_required() -> None:
    fields = validation.normalize_fields([{"type": "section", "label": "Header", "required": True}])
    assert fields[0]["required"] is False


def test_normalize_cleans_options_and_rating_default() -> None:
    fields = validation.normalize_fields(
        [
            {"type": "single_choice", "label": "Pick", "options": [" A ", "A", "B", ""]},
            {"type": "rating", "label": "Score"},
        ]
    )
    assert fields[0]["options"] == ["A", "B"]
    assert fields[1]["max_rating"] == validation.DEFAULT_RATING_SCALE


# ── validate_template_fields ─────────────────────────────────────────────────


def _valid_template() -> list[dict]:
    return validation.normalize_fields(
        [
            {"type": "section", "label": "Details"},
            {"type": "short_text", "label": "Worker name", "required": True},
            {"type": "single_choice", "label": "Card verified", "options": ["Yes", "No"], "required": True},
            {"type": "signature", "label": "Signature", "required": True},
        ]
    )


def test_valid_template_has_no_issues() -> None:
    assert validation.validate_template_fields(_valid_template()) == []


def test_empty_template_reports_no_fields() -> None:
    assert "no_fields" in _codes(validation.validate_template_fields([]))


def test_only_sections_reports_no_fillable_field() -> None:
    fields = validation.normalize_fields([{"type": "section", "label": "A"}, {"type": "section", "label": "B"}])
    assert "no_fillable_field" in _codes(validation.validate_template_fields(fields))


def test_choice_without_options_is_flagged() -> None:
    fields = validation.normalize_fields([{"type": "single_choice", "label": "Pick", "options": ["only"]}])
    assert "choice_needs_options" in _codes(validation.validate_template_fields(fields))


def test_multi_choice_needs_two_options() -> None:
    fields = validation.normalize_fields([{"type": "multi_choice", "label": "Pick", "options": []}])
    assert "choice_needs_options" in _codes(validation.validate_template_fields(fields))


def test_duplicate_keys_are_flagged() -> None:
    # Craft explicit colliding keys (normalize would otherwise de-dupe them).
    fields = [
        {"key": "dup", "type": "short_text", "label": "One", "required": False},
        {"key": "dup", "type": "short_text", "label": "Two", "required": False},
    ]
    assert "duplicate_key" in _codes(validation.validate_template_fields(fields))


def test_unknown_type_is_flagged() -> None:
    fields = [{"key": "x", "type": "wormhole", "label": "X", "required": False}]
    assert "unknown_type" in _codes(validation.validate_template_fields(fields))


def test_missing_label_is_flagged() -> None:
    fields = [{"key": "x", "type": "short_text", "label": "", "required": False}]
    assert "missing_label" in _codes(validation.validate_template_fields(fields))


def test_rating_scale_out_of_range_is_flagged() -> None:
    fields = validation.normalize_fields([{"type": "rating", "label": "Score", "max_rating": 99}])
    assert "rating_scale" in _codes(validation.validate_template_fields(fields))


# ── validate_submission_answers ──────────────────────────────────────────────


def _submission_fields() -> list[dict]:
    return validation.normalize_fields(
        [
            {"type": "section", "label": "Details"},
            {"type": "short_text", "label": "Worker name", "required": True},
            {"type": "single_choice", "label": "Card", "options": ["Yes", "No"], "required": True},
            {"type": "checkbox", "label": "PPE issued", "required": True},
            {"type": "pass_fail_na", "label": "Site clean", "required": True},
            {"type": "number", "label": "Slump", "required": True, "unit": "mm"},
            {"type": "rating", "label": "Readiness", "max_rating": 5, "required": True},
            {"type": "signature", "label": "Signature", "required": True},
            {"type": "long_text", "label": "Notes"},  # optional
        ]
    )


def _complete_answers() -> dict:
    return {
        "worker_name": "Sam",
        "card": "Yes",
        "ppe_issued": True,
        "site_clean": "pass",
        "slump": "90",
        "readiness": 4,
        "signature": {"name": "Sam"},
    }


def test_complete_submission_passes() -> None:
    check = validation.validate_submission_answers(_submission_fields(), _complete_answers())
    assert check.is_complete
    assert check.total_required == 7
    assert check.answered_required == 7


def test_missing_required_is_reported() -> None:
    answers = _complete_answers()
    del answers["worker_name"]
    check = validation.validate_submission_answers(_submission_fields(), answers)
    assert not check.is_complete
    assert "required_missing" in _codes(check.issues)


def test_unticked_required_checkbox_counts_as_missing() -> None:
    answers = _complete_answers()
    answers["ppe_issued"] = False
    check = validation.validate_submission_answers(_submission_fields(), answers)
    assert not check.is_complete
    assert "required_missing" in _codes(check.issues)


def test_invalid_choice_value_is_reported() -> None:
    answers = _complete_answers()
    answers["card"] = "Maybe"
    check = validation.validate_submission_answers(_submission_fields(), answers)
    assert "invalid_choice" in _codes(check.issues)


def test_non_numeric_number_is_reported() -> None:
    answers = _complete_answers()
    answers["slump"] = "soft"
    check = validation.validate_submission_answers(_submission_fields(), answers)
    assert "not_a_number" in _codes(check.issues)


def test_rating_out_of_scale_is_reported() -> None:
    answers = _complete_answers()
    answers["readiness"] = 9
    check = validation.validate_submission_answers(_submission_fields(), answers)
    assert "invalid_rating" in _codes(check.issues)


def test_bad_pass_fail_value_is_reported() -> None:
    answers = _complete_answers()
    answers["site_clean"] = "maybe"
    check = validation.validate_submission_answers(_submission_fields(), answers)
    assert "invalid_pass_fail" in _codes(check.issues)


def test_required_signature_missing_when_blank() -> None:
    answers = _complete_answers()
    answers["signature"] = {"name": "", "data": ""}
    check = validation.validate_submission_answers(_submission_fields(), answers)
    assert "required_missing" in _codes(check.issues)


def test_optional_field_left_blank_is_fine() -> None:
    # Notes is optional and absent; the rest is complete.
    check = validation.validate_submission_answers(_submission_fields(), _complete_answers())
    assert check.is_complete


def test_multi_choice_required_empty_then_valid() -> None:
    fields = validation.normalize_fields(
        [{"type": "multi_choice", "label": "Hazards", "options": ["Dust", "Noise"], "required": True}]
    )
    empty = validation.validate_submission_answers(fields, {"hazards": []})
    assert "required_missing" in _codes(empty.issues)

    bad = validation.validate_submission_answers(fields, {"hazards": ["Dust", "Fog"]})
    assert "invalid_choice" in _codes(bad.issues)

    good = validation.validate_submission_answers(fields, {"hazards": ["Dust", "Noise"]})
    assert good.is_complete


def test_number_accepts_comma_decimal() -> None:
    fields = validation.normalize_fields([{"type": "number", "label": "Temp", "required": True}])
    check = validation.validate_submission_answers(fields, {"temp": "22,5"})
    assert check.is_complete


# ── per-field capture config ─────────────────────────────────────────────────


def test_number_min_greater_than_max_is_flagged() -> None:
    fields = validation.normalize_fields([{"type": "number", "label": "Slump", "min": 10, "max": 5}])
    assert "min_gt_max" in _codes(validation.validate_template_fields(fields))


def test_bad_pattern_is_flagged() -> None:
    fields = validation.normalize_fields([{"type": "short_text", "label": "Code", "pattern": "("}])
    assert "bad_pattern" in _codes(validation.validate_template_fields(fields))


def test_choice_default_must_be_an_option() -> None:
    fields = validation.normalize_fields(
        [{"type": "single_choice", "label": "Pick", "options": ["A", "B"], "default": "Z"}]
    )
    assert "default_not_option" in _codes(validation.validate_template_fields(fields))


def test_number_below_min_is_reported() -> None:
    fields = validation.normalize_fields(
        [{"type": "number", "label": "Slump", "required": True, "min": 10, "max": 200}]
    )
    check = validation.validate_submission_answers(fields, {"slump": "5"})
    assert "below_min" in _codes(check.issues)


def test_number_above_max_is_reported() -> None:
    fields = validation.normalize_fields(
        [{"type": "number", "label": "Slump", "required": True, "min": 10, "max": 200}]
    )
    check = validation.validate_submission_answers(fields, {"slump": "500"})
    assert "above_max" in _codes(check.issues)


def test_number_within_bounds_passes() -> None:
    fields = validation.normalize_fields(
        [{"type": "number", "label": "Slump", "required": True, "min": 10, "max": 200}]
    )
    assert validation.validate_submission_answers(fields, {"slump": "90"}).is_complete


def test_text_min_length_is_reported() -> None:
    fields = validation.normalize_fields([{"type": "short_text", "label": "Ref", "required": True, "min_length": 5}])
    check = validation.validate_submission_answers(fields, {"ref": "ab"})
    assert "too_short" in _codes(check.issues)


def test_text_pattern_mismatch_is_reported() -> None:
    # A simple 4-digit code pattern.
    fields = validation.normalize_fields(
        [{"type": "short_text", "label": "PIN", "required": True, "pattern": r"\d{4}"}]
    )
    bad = validation.validate_submission_answers(fields, {"pin": "12"})
    assert "pattern_mismatch" in _codes(bad.issues)
    good = validation.validate_submission_answers(fields, {"pin": "1234"})
    assert good.is_complete


def test_formula_field_is_not_required_and_not_user_validated() -> None:
    # A formula field carries no user answer, so a submission with only the
    # entered inputs (no 'area' answer) is still complete.
    fields = validation.normalize_fields(
        [
            {"type": "number", "label": "Length", "key": "length", "required": True},
            {"type": "number", "label": "Width", "key": "width", "required": True},
            {"type": "formula", "label": "Area", "key": "area", "formula": "length * width", "required": True},
        ]
    )
    check = validation.validate_submission_answers(fields, {"length": "4", "width": "3"})
    assert check.is_complete
    assert check.total_required == 2  # only the two number fields count
