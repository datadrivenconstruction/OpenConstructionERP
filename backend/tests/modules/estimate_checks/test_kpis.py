# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate check KPI arithmetic, ranges, ratings and the rule set (no database)."""

from __future__ import annotations

import pytest

from app.modules.estimate_checks.kpis import (
    KPI_DEFS,
    assess,
    compute_kpis,
    confidence_for,
    history_row,
    merge_settings,
    percentile,
    rate_against_range,
    rate_count,
)


def _pos(pid, desc, unit, qty, rate, resources=None, **meta):
    return {
        "id": pid,
        "ordinal": pid,
        "description": desc,
        "unit": unit,
        "quantity": str(qty),
        "unit_rate": str(rate),
        "total": str(qty * rate),
        "resources": resources or [],
        "metadata": meta,
    }


def _snapshot():
    # 10 m3 concrete at 100: labour 2 h x 30 = 60, material 30, equipment 0.5 h x 20 = 10 per m3.
    concrete = _pos(
        "p1",
        "Concrete wall",
        "m3",
        10,
        100,
        [
            {"type": "labor", "unit": "h", "quantity": 2, "unit_rate": 30},
            {"type": "material", "unit": "m3", "quantity": 1, "unit_rate": 30, "waste_pct": 4},
            {"type": "equipment", "unit": "h", "quantity": 0.5, "unit_rate": 20},
        ],
    )
    sub = _pos("p2", "Roofing by subcontractor", "m2", 1, 1000, [{"type": "subcontractor", "total": 1000}])
    return {
        "positions": [
            concrete,
            sub,
            _pos("p3", "Formwork", "m2", 5, 0, [{"type": "labor", "unit": "h", "quantity": 0, "unit_rate": 0}]),
            _pos("p4", "Rebar", "t", 0, 900),
            _pos("p5", "Cleaning", "ls", 0, 0),
            _pos("p6", "Concrete wall", "m3", 3, 100),
        ],
        "markups": [
            {"category": "overhead", "percentage": "10", "is_active": True},
            {"category": "profit", "percentage": "5", "is_active": True},
            {"category": "contingency", "percentage": "3", "is_active": True},
            {"category": "tax", "percentage": "19", "is_active": True},
            {"category": "profit", "percentage": "50", "is_active": False},
        ],
    }


def test_percentile_interpolates():
    assert percentile([1, 2, 3, 4, 5], 50) == 3
    assert percentile([10], 90) == 10
    assert percentile([0, 10], 10) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        percentile([], 50)


def test_rate_against_range_three_states():
    assert rate_against_range(10, 5, 15, 0.5) == "normal"
    assert rate_against_range(17, 5, 15, 0.5) == "suspect"
    assert rate_against_range(25, 5, 15, 0.5) == "warning"
    assert rate_against_range(0, 5, 15, 0.5) == "suspect"


def test_rate_count_and_confidence():
    assert rate_count(0, 100, 5) == "normal"
    assert rate_count(2, 100, 5) == "suspect"
    assert rate_count(5, 100, 5) == "warning"
    assert confidence_for(0) == 0.3
    assert confidence_for(5) < confidence_for(30) <= 0.95


def test_shares_and_labour_kpis():
    k = compute_kpis(_snapshot())
    direct = 1000 + 1000 + 0 + 0 + 0 + 300
    assert k["labour_share"].value == pytest.approx(600 * 100 / direct)
    assert k["material_share"].value == pytest.approx(300 * 100 / direct)
    assert k["equipment_share"].value == pytest.approx(100 * 100 / direct)
    assert k["subcontractor_share"].value == pytest.approx(1000 * 100 / direct)
    assert k["avg_crew_rate"].value == pytest.approx(30.0)
    assert k["equipment_to_labour_hours"].value == pytest.approx(5 / 20)
    assert k["avg_waste_pct"].value == pytest.approx(4.0)
    # Main quantity: the unit carrying most cost is m3 (1300) over m2 (1000).
    assert k["labour_cost_per_unit"].unit_label == "m3"
    assert k["labour_cost_per_unit"].value == pytest.approx(600 / 13)


def test_markup_kpis_ignore_tax_and_inactive():
    k = compute_kpis(_snapshot())
    assert k["overhead_pct"].value == 10
    assert k["profit_pct"].value == 5
    assert k["risk_pct"].value == 3
    assert k["total_markup_pct"].value == 18


def test_data_quality_kpis_name_the_positions():
    k = compute_kpis(_snapshot())
    assert k["zero_rate"].position_ids == ["p3"]
    assert k["zero_quantity"].position_ids == ["p4"]
    assert k["unpriced"].position_ids == ["p5"]
    assert sorted(k["duplicates"].position_ids) == ["p1", "p6"]
    assert k["single_quote_items"].position_ids == ["p2"]


def test_single_quote_counts_quotes():
    snap = {"positions": [_pos("s", "Sub", "ls", 1, 10, [{"type": "subcontractor", "total": 10}], quotes=[1, 2])]}
    assert compute_kpis(snap)["single_quote_items"].value == 0


def test_rate_far_from_database():
    p = _pos("x", "Brick", "m2", 1, 200)
    p["db_rate"] = 100
    q = _pos("y", "Block", "m2", 1, 110)
    q["db_rate"] = 100
    k = compute_kpis({"positions": [p, q]}, db_tolerance_pct=30)
    assert k["rate_far_from_database"].position_ids == ["x"]


def test_empty_estimate_is_not_measurable():
    k = compute_kpis({"positions": [], "markups": []})
    assert k["labour_share"].value is None
    assert k["overhead_pct"].value is None
    assert k["zero_rate"].value == 0


def test_assess_uses_history_when_enough_comparables():
    s = merge_settings(None)
    kv = compute_kpis(_snapshot())["overhead_pct"]
    history = [{"overhead_pct": v} for v in (8, 9, 10, 11, 12, 9, 10)]
    r = assess(kv, history, s, 6)
    assert r["status"] == "normal"
    assert r["compared"] == 7
    assert r["reason"] == "within_history"
    assert 0.3 < r["confidence"] < 0.95


def test_assess_falls_back_to_default_band_with_low_confidence():
    s = merge_settings(None)
    kv = compute_kpis(_snapshot())["profit_pct"]
    r = assess(kv, [{"profit_pct": 4}], s, 6)
    assert (r["low"], r["high"]) == (3.0, 10.0)
    assert r["confidence"] == 0.3
    assert r["reason"] == "within_default"


def test_assess_custom_thresholds_win():
    s = merge_settings({"kpis": {"overhead_pct": {"low": 1, "high": 4}}})
    r = assess(compute_kpis(_snapshot())["overhead_pct"], [], s, 6)
    assert r["status"] == "warning"
    assert r["reason"] == "outside_custom"


def test_assess_cost_per_unit_only_compares_same_unit():
    s = merge_settings({"min_comparables": 2})
    kv = compute_kpis(_snapshot())["labour_cost_per_unit"]
    hist = [{"labour_cost_per_unit": 46, "_units": {"labour_cost_per_unit": "m3"}}] * 2
    hist += [{"labour_cost_per_unit": 1, "_units": {"labour_cost_per_unit": "m2"}}] * 5
    r = assess(kv, hist, s, 6)
    assert r["compared"] == 2


def test_merge_settings_drops_unknown_kpis_and_keeps_defaults():
    s = merge_settings({"kpis": {"nope": {"enabled": False}, "duplicates": {"enabled": False}}})
    assert "nope" not in s["kpis"]
    assert s["kpis"]["duplicates"]["enabled"] is False
    assert len(s["kpis"]) == len(KPI_DEFS)


def test_history_row_carries_unit():
    row = history_row(_snapshot())
    assert row["_units"]["labour_cost_per_unit"] == "m3"
    assert row["overhead_pct"] == 10


async def test_rule_set_runs_through_validation_engine():
    from app.modules.estimate_checks.validators import RULE_IDS, evaluate

    kpis = compute_kpis(_snapshot())
    n = int(kpis.pop("_meta").value)
    settings = merge_settings({"kpis": {"duplicates": {"enabled": False}}})
    out = await evaluate({"kpis": kpis, "positions": n}, {"history": [], "settings": settings})
    ids = {r["kpi_id"] for r in out}
    assert "duplicates" not in ids
    assert len(ids) == len(RULE_IDS) - 1
    assert {r["status"] for r in out} <= {"normal", "suspect", "warning", "no_data"}
