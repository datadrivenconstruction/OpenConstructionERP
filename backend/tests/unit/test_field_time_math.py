# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure field-time engine.

These exercise :mod:`app.modules.field_time.field_time_math` directly with plain
``Decimal`` / ``dict`` inputs - no database, FastAPI or ORM - so they run on any
interpreter (including the local Python 3.11 runner), exactly like the progress /
EVM / cost-risk engine tests.

They lock in the contract the foreman's field timesheet depends on: the 24 hour
per-worker cap, per-worker hour summing, labour-XOR-plant line completeness, the
daywork -> daywork-sheet mapping, hours x rate cost rollup, and reversal netting
(an approved timesheet plus its reversal nets to zero). Money and hours stay
``Decimal`` throughout.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.field_time import field_time_math as ft

D = Decimal


def _labour(resource_id: str, hours: str, cost_code: str = "01.10", **extra: object) -> dict[str, object]:
    """Build a labour line dict."""
    line: dict[str, object] = {
        "resource_id": resource_id,
        "equipment_id": None,
        "hours": hours,
        "cost_code": cost_code,
    }
    line.update(extra)
    return line


def _plant(equipment_id: str, hours: str, cost_code: str = "01.10", **extra: object) -> dict[str, object]:
    """Build a plant line dict."""
    line: dict[str, object] = {
        "resource_id": None,
        "equipment_id": equipment_id,
        "hours": hours,
        "cost_code": cost_code,
    }
    line.update(extra)
    return line


# ── to_decimal ───────────────────────────────────────────────────────────────


def test_to_decimal_parses_and_defaults() -> None:
    assert ft.to_decimal("8.5") == D("8.5")
    assert ft.to_decimal(3) == D("3")
    assert ft.to_decimal(D("2.25")) == D("2.25")
    assert ft.to_decimal(None) == D("0")
    assert ft.to_decimal("not-a-number") == D("0")
    assert ft.to_decimal(None, default=D("-1")) == D("-1")


def test_to_decimal_rejects_non_finite() -> None:
    assert ft.to_decimal("NaN") == D("0")
    assert ft.to_decimal("Infinity") == D("0")
    assert ft.to_decimal(float("inf")) == D("0")


def test_to_decimal_preserves_negative_for_reversal() -> None:
    assert ft.to_decimal("-8") == D("-8")


# ── line kind + completeness (labour XOR plant) ──────────────────────────────


def test_resolve_line_kind_from_ids() -> None:
    assert ft.resolve_line_kind(_labour("r1", "8")) == ft.KIND_LABOUR
    assert ft.resolve_line_kind(_plant("e1", "8")) == ft.KIND_PLANT


def test_resolve_line_kind_ambiguous_when_both_ids_set() -> None:
    line = {"resource_id": "r1", "equipment_id": "e1", "hours": "8", "cost_code": "x"}
    assert ft.resolve_line_kind(line) == ft.KIND_AMBIGUOUS


def test_resolve_line_kind_unspecified_when_neither() -> None:
    line = {"resource_id": None, "equipment_id": None, "hours": "8", "cost_code": "x"}
    assert ft.resolve_line_kind(line) == ft.KIND_UNSPECIFIED


def test_resolve_line_kind_hint_when_no_ids() -> None:
    assert ft.resolve_line_kind({"kind": "plant", "hours": "1"}) == ft.KIND_PLANT
    assert ft.resolve_line_kind({"kind": "labour", "hours": "1"}) == ft.KIND_LABOUR


def test_line_completeness_passes_for_well_formed_labour() -> None:
    result = ft.line_completeness(_labour("r1", "8", "01.10"))
    assert result.passed is True
    assert result.kind == ft.KIND_LABOUR
    assert result.reasons == ()


def test_line_completeness_flags_both_ids_set() -> None:
    line = {"resource_id": "r1", "equipment_id": "e1", "hours": "8", "cost_code": "x"}
    result = ft.line_completeness(line)
    assert result.passed is False
    assert "labour_xor_plant" in result.reasons


def test_line_completeness_flags_neither_id() -> None:
    line = {"resource_id": None, "equipment_id": None, "hours": "8", "cost_code": "x"}
    assert "labour_xor_plant" in ft.line_completeness(line).reasons


def test_line_completeness_flags_zero_and_negative_hours() -> None:
    assert "hours_positive" in ft.line_completeness(_labour("r1", "0")).reasons
    assert "hours_positive" in ft.line_completeness(_labour("r1", "-3")).reasons


def test_line_completeness_flags_missing_cost_code() -> None:
    assert "cost_code_required" in ft.line_completeness(_labour("r1", "8", "")).reasons
    assert "cost_code_required" in ft.line_completeness(_labour("r1", "8", "   ")).reasons


def test_line_completeness_accumulates_multiple_reasons() -> None:
    line = {"resource_id": None, "equipment_id": None, "hours": "0", "cost_code": ""}
    reasons = ft.line_completeness(line).reasons
    assert set(reasons) == {"labour_xor_plant", "hours_positive", "cost_code_required"}


# ── per-worker daily hours + 24h cap ─────────────────────────────────────────


def test_sum_hours_by_worker_merges_multiple_lines() -> None:
    lines = [
        _labour("r1", "8"),
        _labour("r1", "2.5"),
        _labour("r2", "6"),
        _plant("e1", "9"),  # plant excluded from worker totals
    ]
    totals = ft.sum_hours_by_worker(lines)
    assert totals == {"r1": D("10.50"), "r2": D("6.00")}


def test_sum_hours_by_worker_clamps_negative_line_to_zero() -> None:
    # A stray negative on one line must not understate the day below booked work.
    totals = ft.sum_hours_by_worker([_labour("r1", "8"), _labour("r1", "-3")])
    assert totals == {"r1": D("8.00")}


def test_hours_cap_exceedances_flags_over_24() -> None:
    lines = [_labour("r1", "20"), _labour("r1", "6"), _labour("r2", "8")]
    exceed = ft.hours_cap_exceedances(lines)
    assert len(exceed) == 1
    assert exceed[0].worker_key == "r1"
    assert exceed[0].hours == D("26.00")
    assert exceed[0].exceeds is True


def test_hours_cap_exactly_24_is_allowed() -> None:
    assert ft.hours_cap_exceedances([_labour("r1", "24")]) == []


def test_hours_cap_custom_limit() -> None:
    exceed = ft.hours_cap_exceedances([_labour("r1", "13")], max_hours=D("12"))
    assert len(exceed) == 1
    assert exceed[0].max_hours == D("12")


# ── daywork completeness (needs open variation) ──────────────────────────────


def test_daywork_incomplete_when_no_variation() -> None:
    lines = [
        _labour("r1", "8", is_daywork=True, variation_id="vo1"),
        _labour("r2", "8", is_daywork=True, variation_id=""),  # missing
        _labour("r3", "8"),  # not daywork, ignored
    ]
    assert ft.daywork_incomplete_indices(lines) == [1]


def test_daywork_incomplete_when_variation_not_open() -> None:
    lines = [
        _labour("r1", "8", is_daywork=True, variation_id="vo_open"),
        _labour("r2", "8", is_daywork=True, variation_id="vo_closed"),
    ]
    bad = ft.daywork_incomplete_indices(lines, open_variation_ids={"vo_open"})
    assert bad == [1]


def test_daywork_presence_only_when_open_set_is_none() -> None:
    lines = [_labour("r1", "8", is_daywork=True, variation_id="anything")]
    assert ft.daywork_incomplete_indices(lines, open_variation_ids=None) == []


# ── plant needs equipment ────────────────────────────────────────────────────


def test_plant_missing_equipment_flags_plant_hint_without_id() -> None:
    lines = [
        {"kind": "plant", "hours": "6", "cost_code": "02.10"},  # no equipment_id
        _plant("e1", "6"),  # fine
        _labour("r1", "8"),  # labour, ignored
    ]
    assert ft.plant_missing_equipment_indices(lines) == [0]


# ── cost-code resolution ─────────────────────────────────────────────────────


def test_cost_code_unresolved_against_project_codes() -> None:
    lines = [
        _labour("r1", "8", "01.10"),  # resolves via cost_code
        _labour("r2", "8", "99.99"),  # unknown code
        {"resource_id": "r3", "hours": "8", "cost_code": "", "wbs": "W-1"},  # resolves via wbs
    ]
    bad = ft.cost_code_unresolved_indices(
        lines,
        valid_cost_codes={"01.10", "01.20"},
        valid_wbs={"W-1"},
    )
    assert bad == [1]


def test_cost_code_resolution_skipped_when_no_resolver() -> None:
    lines = [_labour("r1", "8", "whatever")]
    assert ft.cost_code_unresolved_indices(lines, valid_cost_codes=None, valid_wbs=None) == []


def test_cost_code_resolution_ignores_lines_without_any_code() -> None:
    # A line with neither cost_code nor wbs is left to completeness, not flagged here.
    lines = [{"resource_id": "r1", "hours": "8", "cost_code": "", "wbs": ""}]
    assert ft.cost_code_unresolved_indices(lines, valid_cost_codes={"01.10"}, valid_wbs=set()) == []


# ── daywork sheet line mapping ───────────────────────────────────────────────


def test_daywork_line_drafts_maps_labour_and_plant() -> None:
    lines = [
        _labour("r1", "8", "01.10", is_daywork=True, variation_id="vo1", note="Extra digging", id="L1"),
        _plant("e1", "4", "01.10", is_daywork=True, variation_id="vo1", note="Excavator", id="L2"),
        _labour("r2", "8", is_daywork=False),  # not daywork -> excluded
    ]
    drafts = ft.daywork_line_drafts(
        lines,
        labour_rates={"r1": D("45")},
        plant_rates={"e1": D("120")},
    )
    assert len(drafts) == 2
    labour_draft, plant_draft = drafts
    assert labour_draft.line_type == "labor"
    assert labour_draft.quantity == D("8.00")
    assert labour_draft.unit == "h"
    assert labour_draft.unit_rate == D("45.0000")
    assert labour_draft.worker_name == "r1"
    assert labour_draft.variation_id == "vo1"
    assert plant_draft.line_type == "equipment"
    assert plant_draft.unit_rate == D("120.0000")
    assert plant_draft.equipment_code == "e1"


def test_daywork_line_drafts_zero_rate_when_unpriced() -> None:
    lines = [_labour("r1", "8", is_daywork=True, variation_id="vo1")]
    drafts = ft.daywork_line_drafts(lines, labour_rates={}, plant_rates={})
    assert drafts[0].unit_rate == D("0.0000")


# ── cost rollup ──────────────────────────────────────────────────────────────


def test_rollup_splits_labour_and_plant_cost() -> None:
    lines = [
        _labour("r1", "8", "01.10"),
        _labour("r2", "4", "01.10"),
        _plant("e1", "6", "01.10"),
    ]
    roll = ft.rollup(
        lines,
        labour_rates={"r1": D("50"), "r2": D("40")},
        plant_rates={"e1": D("100")},
    )
    assert roll.labour_hours == D("12.00")
    assert roll.plant_hours == D("6.00")
    assert roll.labour_cost == D("560.00")  # 8*50 + 4*40
    assert roll.plant_cost == D("600.00")  # 6*100
    assert roll.total_hours == D("18.00")
    assert roll.total_cost == D("1160.00")


def test_rollup_zero_cost_when_rate_unknown_but_hours_counted() -> None:
    roll = ft.rollup([_labour("r1", "8", "01.10")], labour_rates={}, plant_rates={})
    assert roll.labour_hours == D("8.00")
    assert roll.labour_cost == D("0.00")


def test_line_cost_quantizes_money() -> None:
    assert ft.line_cost("8", "12.5") == D("100.00")
    assert ft.line_cost(D("1.333"), D("3")) == D("4.00")


# ── reversal netting ─────────────────────────────────────────────────────────


def test_net_hours_original_plus_reversal_is_zero() -> None:
    contributions = [
        ft.TimesheetContribution(hours=D("16"), is_reversal=False),
        ft.TimesheetContribution(hours=D("16"), is_reversal=True),
    ]
    assert ft.net_hours(contributions) == D("0.00")


def test_net_hours_partial_reversal() -> None:
    contributions = [
        ft.TimesheetContribution(hours=D("16"), is_reversal=False),
        ft.TimesheetContribution(hours=D("4"), is_reversal=True),
    ]
    assert ft.net_hours(contributions) == D("12.00")


def test_reverse_lines_mirrors_original() -> None:
    original = [
        _labour("r1", "8", "01.10", is_daywork=True, variation_id="vo1", note="dig", wbs="W-1"),
        _plant("e1", "4", "02.20"),
    ]
    mirrored = ft.reverse_lines(original)
    assert len(mirrored) == 2
    assert mirrored[0]["resource_id"] == "r1"
    assert mirrored[0]["hours"] == D("8.00")
    assert mirrored[0]["is_daywork"] is True
    assert mirrored[0]["variation_id"] == "vo1"
    assert mirrored[0]["wbs"] == "W-1"
    assert mirrored[1]["equipment_id"] == "e1"
    assert mirrored[1]["resource_id"] is None


# ── cost-code suggestions (human-confirmed) ──────────────────────────────────


def test_suggest_cost_codes_ranks_by_similarity() -> None:
    candidates = [
        {"code": "03.30", "label": "Concrete formwork to walls"},
        {"code": "02.10", "label": "Excavation to reduce levels"},
        {"code": "05.10", "label": "Structural steel erection"},
    ]
    out = ft.suggest_cost_codes("excavation reduce level", candidates, limit=2)
    assert len(out) == 2
    assert out[0].code == "02.10"
    assert 0.0 <= out[0].confidence <= 1.0
    # Sorted descending by confidence.
    assert out[0].confidence >= out[1].confidence


def test_suggest_cost_codes_empty_text_returns_nothing() -> None:
    assert ft.suggest_cost_codes("", [{"code": "01.10", "label": "x"}]) == []


def test_suggest_cost_codes_respects_min_confidence() -> None:
    candidates = [{"code": "99.99", "label": "totally unrelated masonry"}]
    out = ft.suggest_cost_codes("zzz qqq", candidates, min_confidence=0.9)
    assert out == []


# ── aggregate check_timesheet ────────────────────────────────────────────────


def test_check_timesheet_aggregates_all_findings() -> None:
    lines = [
        _labour("r1", "20", "01.10"),
        _labour("r1", "6", "01.10"),  # r1 total 26 > 24
        _labour("r2", "8", "bad-code"),  # unresolved
        {"resource_id": None, "equipment_id": None, "hours": "8", "cost_code": "01.10"},  # incomplete
        _labour("r3", "8", "01.10", is_daywork=True, variation_id=""),  # daywork missing variation
    ]
    checks = ft.check_timesheet(
        lines,
        valid_cost_codes={"01.10"},
        valid_wbs=set(),
    )
    assert checks.has_blocking_errors is True
    assert checks.incomplete_line_indices == [3]
    assert [w.worker_key for w in checks.hours_cap_exceedances] == ["r1"]
    assert checks.unresolved_cost_code_indices == [2]
    assert checks.daywork_incomplete_indices == [4]


def test_check_timesheet_clean_sheet_has_no_blocking_errors() -> None:
    lines = [_labour("r1", "8", "01.10"), _plant("e1", "6", "01.10")]
    checks = ft.check_timesheet(lines, valid_cost_codes={"01.10"}, valid_wbs=set())
    assert checks.has_blocking_errors is False
    assert checks.incomplete_line_indices == []
    assert checks.hours_cap_exceedances == []


if __name__ == "__main__":  # pragma: no cover - manual smoke run
    raise SystemExit(pytest.main([__file__, "-q"]))
