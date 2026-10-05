# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The course spec models: grammars, authoring stripping and frozen probe args.

Every red case here is a minimal edit of the synthetic fixture course, so a
test fails for the one reason it names and not for a neighbouring one.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.trainer.probe_types import PROBE_TYPE_NAMES
from app.modules.trainer.spec import (
    LEGACY_SEED_KEYS,
    PROBE_ARGS_MODELS,
    CourseSpec,
    GradedBy,
    Stage,
    normalise_course_dict,
    parse_graded_by,
    parse_stage,
    to_decimal,
    to_percent,
    validate_probe,
)

COURSE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "trainer" / "course_fixture_v1.json"


@pytest.fixture(scope="module")
def raw_course() -> dict[str, Any]:
    return json.loads(COURSE_PATH.read_text(encoding="utf-8"), parse_float=Decimal)


@pytest.fixture
def course(raw_course: dict[str, Any]) -> dict[str, Any]:
    data, problems = normalise_course_dict(copy.deepcopy(raw_course))
    assert problems == []
    return data


def _errors(data: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as exc:
        CourseSpec.model_validate(data)
    return str(exc.value)


def _walk_keys(node: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            keys.append(key)
            keys += _walk_keys(value)
    elif isinstance(node, list):
        for value in node:
            keys += _walk_keys(value)
    return keys


# ── Grammars ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("on_enrol", Stage("on_enrol")),
        ("on_unlock(1)", Stage("on_unlock", 1)),
        ("on_unlock(12)", Stage("on_unlock", 12)),
    ],
)
def test_a_stage_parses_on_enrol_and_on_unlock(text: str, expected: Stage) -> None:
    assert parse_stage(text) == expected


@pytest.mark.parametrize(
    "text", ["", "on_unlock(0)", "on_unlock(01)", "on_unlock()", "on_unlock(t2)", "after task 2", "ON_ENROL", None, 3]
)
def test_a_stage_rejects_everything_else(text: object) -> None:
    with pytest.raises(ValueError, match="stage"):
        parse_stage(text)


def test_a_stage_is_visible_from_its_task_on() -> None:
    assert Stage("on_enrol").visible_at(1)
    assert not Stage("on_unlock", 3).visible_at(2)
    assert Stage("on_unlock", 3).visible_at(3)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("panel", GradedBy("panel")),
        ("both", GradedBy("both")),
        ("probe:0", GradedBy("probe", 0)),
        ("probe:7", GradedBy("probe", 7)),
    ],
)
def test_graded_by_parses_its_three_forms(text: str, expected: GradedBy) -> None:
    assert parse_graded_by(text) == expected


@pytest.mark.parametrize("text", ["", "probe", "probe:", "probe:-1", "probe:01", "erp", "Panel", None, 0])
def test_graded_by_rejects_everything_else(text: object) -> None:
    with pytest.raises(ValueError, match="graded_by"):
        parse_graded_by(text)


def test_only_panel_and_both_give_the_learner_a_field() -> None:
    assert parse_graded_by("panel").has_panel_field
    assert parse_graded_by("both").has_panel_field
    assert not parse_graded_by("probe:0").has_panel_field


def test_numbers_are_decimal_and_a_fraction_becomes_percent() -> None:
    assert to_decimal(0.1) == Decimal("0.1")
    assert to_decimal("12.50") == Decimal("12.50")
    assert to_decimal(True) is None
    assert to_decimal("NaN") is None
    assert to_percent(Decimal("0.05"), "fraction") == Decimal("5.00")
    assert to_percent(Decimal("5"), "percent") == Decimal("5")


# ── Authoring material ───────────────────────────────────────────────────────


def test_the_fixture_is_a_valid_spec(course: dict[str, Any]) -> None:
    CourseSpec.model_validate(course)


def test_authoring_and_underscore_keys_are_stripped_at_every_depth(raw_course: dict[str, Any]) -> None:
    raw_keys = _walk_keys(raw_course)
    assert "authoring" in raw_course
    assert any(k.startswith("_") for k in raw_keys), "the fixture must carry _ keys for this test to mean anything"
    data, _ = normalise_course_dict(raw_course)
    stored = CourseSpec.model_validate(data).dump_for_storage()
    assert "authoring" not in stored
    assert [k for k in _walk_keys(stored) if k.startswith("_")] == []
    assert "authoring" in raw_course, "normalising must not mutate its input"


def test_a_stripped_key_inside_an_opaque_blob_is_gone_too(raw_course: dict[str, Any]) -> None:
    erp_fit = raw_course["tasks"][2]["erp_fit"]
    assert any(k.startswith("_") for k in _walk_keys(erp_fit))
    data, _ = normalise_course_dict(raw_course)
    assert not any(k.startswith("_") for k in _walk_keys(data["tasks"][2]["erp_fit"]))


def test_the_stored_spec_parses_back_to_itself(course: dict[str, Any]) -> None:
    stored = CourseSpec.model_validate(course).dump_for_storage()
    assert CourseSpec.model_validate(stored).dump_for_storage() == stored


@pytest.mark.parametrize("key", ["rewalk", "graded_by_semantics", "opens_dependency", "count_claims", "erp_note"])
def test_an_authoring_key_left_in_a_task_is_an_error(course: dict[str, Any], key: str) -> None:
    course["tasks"][0][key] = "x"
    assert "decision 9" in _errors(course)


def test_vat_note_is_the_one_note_key_that_stays(course: dict[str, Any]) -> None:
    course["seed"]["contract"]["vat_note"] = "Standard rate."
    CourseSpec.model_validate(course)


def test_an_unknown_key_is_an_error(course: dict[str, Any]) -> None:
    course["tasks"][0]["answer_key"][0]["colour"] = "blue"
    assert "colour" in _errors(course)


def test_a_root_that_is_not_an_object_is_a_problem() -> None:
    _, problems = normalise_course_dict([1, 2])
    assert problems


# ── Seed shape ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("legacy", "canonical"), sorted(LEGACY_SEED_KEYS.items()))
def test_a_country_named_seed_block_is_refused_with_its_canonical_name(
    course: dict[str, Any], legacy: str, canonical: str
) -> None:
    course["seed"][legacy] = copy.deepcopy(course["seed"]["progress_readings"][0])
    message = _errors(course)
    assert legacy in message
    assert f"seed.{canonical}[]" in message


# ── Round 3: a replaced key is refused with a message naming its new key ────


def _reading(course: dict[str, Any]) -> dict[str, Any]:
    return course["seed"]["progress_readings"][0]["readings"][0]


def test_a_period_carries_its_dates_and_readings_their_line_code(course: dict[str, Any]) -> None:
    """Decision 21: ``{stage, period_from, period_to, readings: [{line_code, percent_complete}]}``."""
    period = course["seed"]["progress_readings"][0]
    assert {"stage", "period_from", "period_to", "readings"} <= set(period)
    assert {"line_code", "percent_complete"} <= set(_reading(course))
    CourseSpec.model_validate(course)


@pytest.mark.parametrize(
    ("old", "new"),
    [("line", "line_code"), ("percent", "percent_complete")],
)
def test_a_reading_key_of_the_drafts_names_its_replacement(course: dict[str, Any], old: str, new: str) -> None:
    reading = _reading(course)
    reading[old] = reading.pop(new)
    message = _errors(course)
    assert f"'{old}'" in message
    assert f"'{new}'" in message


def test_a_single_period_label_names_the_two_dates(course: dict[str, Any]) -> None:
    period = course["seed"]["progress_readings"][0]
    period["period"] = "2026-10"
    message = _errors(course)
    assert "'period_from'" in message
    assert "'period_to'" in message


@pytest.mark.parametrize(
    ("period_from", "period_to"),
    [("2026-10-31", "2026-10-01"), ("October", "2026-10-31"), ("2026-10-01", None)],
)
def test_a_period_is_two_iso_dates_in_order(course: dict[str, Any], period_from: str, period_to: str | None) -> None:
    period = course["seed"]["progress_readings"][0]
    period["period_from"], period["period_to"] = period_from, period_to
    assert "period" in _errors(course)


def test_recorded_at_is_the_seeders_not_the_files(course: dict[str, Any]) -> None:
    """Decision 20: the seeder stamps it inside the period."""
    _reading(course)["recorded_at"] = "2026-10-30T12:00:00Z"
    message = _errors(course)
    assert "recorded_at" in message
    assert "decision 20" in message


@pytest.mark.parametrize(("old", "new"), [("header_total_typed", "total"), ("header_ledger_key", "total_ledger_key")])
def test_a_bid_header_total_is_called_total(course: dict[str, Any], old: str, new: str) -> None:
    """Decision 27."""
    bid = course["seed"]["bid_package"]["bids"][0]
    bid[old] = bid.pop(new)
    message = _errors(course)
    assert f"'{old}'" in message
    assert f"'{new}'" in message


def test_a_display_unit_is_a_short_free_string(course: dict[str, Any]) -> None:
    """Decision 23."""
    answer = course["tasks"][0]["answer_key"][1]
    answer["display_unit"] = "GBP"
    CourseSpec.model_validate(course)
    answer["display_unit"] = "x" * 17
    assert "display_unit" in _errors(course)


@pytest.mark.parametrize("unit", ["EUR", "days", "ratio"])
def test_a_display_unit_written_as_unit_names_display_unit(course: dict[str, Any], unit: str) -> None:
    course["tasks"][0]["answer_key"][1]["unit"] = unit
    message = _errors(course)
    assert "'display_unit'" in message
    assert "decision 23" in message


def test_scale_is_dropped_and_points_at_authoring(course: dict[str, Any]) -> None:
    """Decision 25."""
    course["tasks"][0]["readback"][0]["scale"] = 100
    message = _errors(course)
    assert "'scale'" in message
    assert "authoring" in message


def test_navigation_is_dropped_and_points_at_authoring(course: dict[str, Any]) -> None:
    course["seed"]["navigation"] = {"t1": "/boq"}
    message = _errors(course)
    assert "'navigation'" in message
    assert "authoring" in message


def test_a_flat_sov_classification_is_refused(course: dict[str, Any]) -> None:
    line = course["seed"]["contract"]["schedule_of_values"][0]
    line["classification"] = line.pop("metadata")["classification"]
    assert "decision 18" in _errors(course)


def test_a_sov_line_needs_a_unit(course: dict[str, Any]) -> None:
    del course["seed"]["contract"]["schedule_of_values"][0]["unit"]
    assert "unit" in _errors(course)


def test_a_position_carries_its_classification_as_a_map(course: dict[str, Any]) -> None:
    position = course["seed"]["boq"]["positions"][0]
    assert position["classification"] == {"nrm": "1.1"}
    position["classification"] = "1.1"
    assert "classification" in _errors(course)


def test_the_project_names_its_rule_sets_as_a_list(course: dict[str, Any]) -> None:
    course["seed"]["project"]["validation_rule_sets"] = "nrm"
    assert "validation_rule_sets" in _errors(course)


def test_the_vat_rate_is_a_plain_number(course: dict[str, Any]) -> None:
    course["seed"]["contract"]["vat_rate_percent"] = {"value": 20, "unit": "percent"}
    assert "vat_rate_percent" in _errors(course)


def test_a_seed_ref_other_than_the_fixed_one_is_refused(course: dict[str, Any]) -> None:
    course["seed"]["bid_package"]["ref"] = "package.roof"
    assert "bid_package.main" in _errors(course)


def test_legal_review_is_pending_or_reviewed(course: dict[str, Any]) -> None:
    course["legal_review"] = "maybe"
    assert "legal_review" in _errors(course)


def test_graded_by_is_required_and_grammar_checked(course: dict[str, Any]) -> None:
    course["tasks"][0]["answer_key"][0]["graded_by"] = "erp"
    assert "graded_by" in _errors(course)


# ── Frozen probe args (decision 16) ──────────────────────────────────────────


def test_there_is_one_args_model_per_probe_type() -> None:
    assert set(PROBE_ARGS_MODELS) == PROBE_TYPE_NAMES


VALID_PROBES: dict[str, dict[str, Any]] = {
    "boq.cost_breakdown": {"boq_ref": "boq.main", "field": "markup_amount", "markup_name": "Profit"},
    "boq.position": {"boq_ref": "boq.main", "ordinal": "01.002", "field": "unit_rate"},
    "boq.section_total": {"boq_ref": "boq.main", "section_ordinal": "01"},
    "boq.markup": {"boq_ref": "boq.main", "name": "Profit", "field": "percentage"},
    "bid.submission": {"package_ref": "bid_package.main", "bidder_name": "A", "field": "total_amount"},
    "bid.leveling": {"package_ref": "bid_package.main", "bidder_name": "A", "field": "rank"},
    "bid.award": {"package_ref": "bid_package.main", "field": "awarded_bidder_name"},
    "contract.field": {"contract_ref": "contract.main", "field": "einvoice_vat_rate"},
    "claim.field": {"contract_ref": "contract.main", "claim_selector": "latest", "field": "net_due"},
    "claim.line": {
        "contract_ref": "contract.main",
        "claim_selector": 1,
        "line_code": "C01",
        "field": "retention_to_date",
    },
    "claim.lien_waiver": {"contract_ref": "contract.main", "claim_selector": 2, "field": "waiver_type"},
    "finance.receivable": {"contract_ref": "contract.main", "claim_selector": "latest", "field": "tax_amount"},
    "variation.request": {"variation_ref": "latest", "field": "agreed_cost_impact"},
    "variation.order": {"contract_ref": "contract.main", "variation_ref": 1, "field": "final_cost_impact"},
    "panel.answer": {"answer_name": "direct_cost"},
    "panel.option": {"question": "trace"},
}


def test_every_probe_type_has_a_valid_example() -> None:
    assert set(VALID_PROBES) == PROBE_TYPE_NAMES


@pytest.mark.parametrize("kind", sorted(VALID_PROBES))
def test_the_frozen_args_of_each_probe_type_validate(kind: str) -> None:
    probe = validate_probe({"type": kind, "args": VALID_PROBES[kind], "expect": 1, "gate": True})
    assert probe.gate is True


@pytest.mark.parametrize("kind", sorted(VALID_PROBES))
def test_an_extra_arg_is_refused_for_each_probe_type(kind: str) -> None:
    with pytest.raises(ValidationError):
        validate_probe({"type": kind, "args": {**VALID_PROBES[kind], "ref": "x"}})


@pytest.mark.parametrize("kind", sorted(VALID_PROBES))
def test_each_probe_type_refuses_missing_args(kind: str) -> None:
    with pytest.raises(ValidationError):
        validate_probe({"type": kind, "args": {}})


@pytest.mark.parametrize(
    ("kind", "args"),
    [
        ("boq.cost_breakdown", {"boq_ref": "boq.main", "field": "markup_amount"}),
        ("boq.cost_breakdown", {"boq_ref": "boq.main", "field": "grand_total", "markup_name": "Profit"}),
        ("boq.position", {"boq_ref": "main", "ordinal": "01", "field": "total"}),
        ("bid.award", {"package_ref": "package.main", "field": "awarded_amount"}),
        ("finance.receivable", {"claim_selector": "latest", "field": "tax_amount"}),
        ("claim.field", {"contract_ref": "contract.main", "claim_selector": 0, "field": "net_due"}),
        ("claim.field", {"contract_ref": "contract.main", "claim_selector": "first", "field": "net_due"}),
        ("variation.request", {"variation_ref": "latest", "match": "VR-01", "field": "status"}),
        ("variation.order", {"variation_ref": "latest", "field": "status"}),
        ("contract.field", {"contract_ref": "contract.main", "field": "value"}),
    ],
)
def test_the_args_the_course_drafts_used_are_refused(kind: str, args: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        validate_probe({"type": kind, "args": args})


def test_gate_defaults_to_false_and_lives_on_the_probe(course: dict[str, Any]) -> None:
    assert validate_probe({"type": "panel.option", "args": {"question": "trace"}}).gate is False
    readback = course["tasks"][2]["readback"][2]
    assert readback["probe"]["gate"] is True
    readback["gate"] = readback["probe"].pop("gate")
    assert "'probe.gate'" in _errors(course)


def test_a_probe_type_off_the_closed_list_is_refused() -> None:
    with pytest.raises(ValidationError):
        validate_probe({"type": "boq.anything", "args": {}})
