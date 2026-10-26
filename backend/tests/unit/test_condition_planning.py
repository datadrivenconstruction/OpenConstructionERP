"""Condition scales and maintenance planning maths (no database)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.condition import planning, scales


@pytest.fixture
def default_scale() -> dict:
    scale = next(s for s in scales.builtin_scales() if s["key"] == scales.DEFAULT_SCALE_KEY)
    return scale


def test_default_scale_has_six_levels_best_first(default_scale):
    assert [lv["level"] for lv in default_scale["levels"]] == [1, 2, 3, 4, 5, 6]
    assert default_scale["levels"][0]["action"] is None
    assert default_scale["levels"][-1]["action"]["type"] == "replace"
    assert default_scale["action_threshold"] == 4
    assert default_scale["source"] == scales.SOURCE_BUILTIN


def test_validate_scale_reports_every_problem():
    with pytest.raises(scales.ScaleError) as exc:
        scales.validate_scale(
            {
                "key": "",
                "levels": [
                    {"level": 1, "label": "A"},
                    {"level": 3, "label": ""},
                    {"level": 3, "label": "C", "action": {"type": "paint"}},
                ],
                "action_threshold": 9,
            }
        )
    problems = " | ".join(exc.value.problems)
    assert "key is required" in problems
    assert "level 2 must carry level=2" in problems
    assert "level 2 needs a label" in problems
    assert "action type" in problems
    assert "action_threshold" in problems


def test_validate_scale_accepts_a_three_level_scale_and_defaults_threshold():
    clean = scales.validate_scale(
        {"key": "abc", "levels": [{"level": 1, "label": "ok"}, {"level": 2, "label": "x"}, {"level": 3, "label": "y"}]}
    )
    assert clean["action_threshold"] == 3
    assert len(clean["levels"]) == 3


@pytest.mark.parametrize(
    ("severity", "extent", "intensity", "expected"),
    [(1, 5, 1, 1), (4, 80, 4, 6), (2, 20, 2, 3), (3, None, None, 4)],
)
def test_suggest_rating_spreads_over_the_scale(severity, extent, intensity, expected):
    rating, confidence = planning.suggest_rating(6, severity=severity, extent_pct=extent, intensity=intensity)
    assert rating == expected
    assert 0 < confidence < 1


def test_suggest_rating_needs_severity():
    assert planning.suggest_rating(6, severity=None, extent_pct=50) == (None, 0.0)


def test_suggest_rating_respects_short_scales():
    rating, _ = planning.suggest_rating(3, severity=4, extent_pct=90, intensity=4)
    assert rating == 3


def test_extent_classes():
    assert [planning.extent_class(v) for v in (0, 9.9, 10, 45, 60, 100)] == [1, 1, 2, 3, 4, 4]
    assert planning.extent_class(None) is None


def test_derive_repair_sizes_quantity_by_extent(default_scale):
    actions = planning.derive_actions(
        {"rating": 5, "severity": 3, "extent_pct": 25, "quantity": "200", "unit": "m2", "unit_cost": "80"},
        default_scale,
        base_year=2027,
    )
    assert len(actions) == 1
    a = actions[0]
    assert a["action_type"] == "repair"
    assert a["first_year"] == 2028
    assert Decimal(a["quantity"]) == Decimal("50")
    assert a["interval_years"] is None
    assert a["confidence"] == pytest.approx(0.9)


def test_derive_high_intensity_brings_work_forward(default_scale):
    a = planning.derive_actions({"rating": 5, "intensity": 4}, default_scale, base_year=2027)[0]
    assert a["first_year"] == 2027
    low = planning.derive_actions({"rating": 4, "intensity": 1}, default_scale, base_year=2027)[0]
    assert low["first_year"] == 2030


def test_derive_maintenance_is_recurring_and_excellent_needs_nothing(default_scale):
    a = planning.derive_actions({"rating": 3}, default_scale, base_year=2027)[0]
    assert a["action_type"] == "maintain" and a["interval_years"] == 3
    assert planning.derive_actions({"rating": 1}, default_scale, base_year=2027) == []
    assert planning.derive_actions({"rating": 9}, default_scale, base_year=2027) == []


def test_annual_rate_from_index_points():
    rate = planning.annual_rate_from_points({"2024-01": "100", "2025-01": "104", "2024-07": "102"})
    assert rate == Decimal("0.04")
    assert planning.annual_rate_from_points({"2024-01": "100"}) is None
    assert planning.annual_rate_from_points({"2024-01": "100", "bad": "x"}) is None


def test_build_plan_buckets_inflates_and_discounts():
    plan = planning.build_plan(
        [
            {
                "id": "a",
                "asset_ref": "AHU-1",
                "first_year": 2027,
                "interval_years": None,
                "quantity": "2",
                "unit_cost": "500",
            },
            {
                "id": "b",
                "element_name": "Roof",
                "first_year": 2027,
                "interval_years": 2,
                "quantity": None,
                "unit_cost": "100",
            },
            {
                "id": "c",
                "element_name": "Doors",
                "first_year": 2026,
                "interval_years": None,
                "quantity": "1",
                "unit_cost": None,
            },
        ],
        start_year=2027,
        horizon_years=4,
        inflation_rate="0.10",
        discount_rate="0",
    )
    years = {y["year"]: y for y in plan["years"]}
    assert list(years) == [2027, 2028, 2029, 2030]
    assert years[2027]["cost"] == "1100.00"
    assert years[2029]["cost"] == "100.00"
    assert years[2029]["cost_inflated"] == "121.00"
    # Overdue unpriced one-off lands in the first year and is counted as unpriced.
    assert any(i["id"] == "c" for i in years[2027]["items"])
    assert plan["totals"]["unpriced_actions"] == 1
    assert plan["totals"]["cost"] == "1200.00"
    assert plan["totals"]["cost_inflated"] == "1221.00"
    assert plan["totals"]["present_value"] == "1221.00"
    assert plan["by_asset"]["AHU-1"] == "1000.00"


def test_build_plan_present_value_uses_discounting():
    plan = planning.build_plan(
        [{"id": "a", "first_year": 2031, "quantity": "1", "unit_cost": "1000"}],
        start_year=2027,
        horizon_years=10,
        discount_rate="0.05",
    )
    assert Decimal(plan["totals"]["present_value"]) == pytest.approx(Decimal("822.70"), abs=Decimal("0.01"))
