"""Unit tests pinning the Part-9 BOQ remediation contract.

Covers the pure-function fixes (no DB session required):

* B-005 — ``apply_to='subtotal'`` bases the markup on
  direct_cost + Σ(preceding markups), identical to ``cumulative``.
* B-001 / B-012 — aggregate monetary values quantise to cents with
  commercial ROUND_HALF_UP (not banker's, not raw full precision).
* D-TKC-003 — ``group_cad_elements_dynamic`` grand totals accumulate from
  RAW per-group sums so many tiny quantities do not vanish.
* D-TKC-004 — ``group_cad_elements_dynamic`` resolves DDC column-name
  variants (``Volume (m3)`` / ``volume_m3``) instead of silent 0.0.

DB-bound paths (B-003 recalculate-rates crash, B-004 path parity, B-010
nested-section rollup) are exercised by the BOQ integration suite.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.boq.cad_import import (
    _norm_col,
    _resolve_column_value,
    group_cad_elements_dynamic,
)
from app.modules.boq.models import BOQMarkup
from app.modules.boq.service import _calculate_markup_amounts, _round_currency

# ── B-005: subtotal == cumulative base ──────────────────────────────────


def _mk(name: str, pct: str, apply_to: str, order: int) -> BOQMarkup:
    return BOQMarkup(
        boq_id=None,
        name=name,
        markup_type="percentage",
        category="overhead" if apply_to != "subtotal" else "tax",
        percentage=pct,
        fixed_amount="0",
        apply_to=apply_to,
        sort_order=order,
        is_active=True,
        metadata_={},
    )


def test_b005_subtotal_includes_preceding_markups() -> None:
    """OH 10% on direct_cost, then Tax 10% apply_to='subtotal'.

    DC = 1000 → OH = 100 → Tax base must be 1000+100 = 1100 → Tax = 110
    (the v1.9.0 bug computed Tax = 100 because 'subtotal' fell through to
    the direct_cost branch).
    """
    dc = Decimal("1000")
    markups = [
        _mk("Overhead", "10", "direct_cost", 0),
        _mk("Tax on subtotal", "10", "subtotal", 1),
    ]
    results = _calculate_markup_amounts(dc, markups)
    amounts = {m.name: amt for m, amt in results}
    assert amounts["Overhead"] == Decimal("100")
    assert amounts["Tax on subtotal"] == Decimal("110")
    net = dc + sum(a for _, a in results)
    assert net == Decimal("1210")


def test_b005_subtotal_matches_cumulative() -> None:
    """'subtotal' and 'cumulative' produce identical amounts."""
    dc = Decimal("1000")
    sub = _calculate_markup_amounts(
        dc,
        [_mk("A", "10", "direct_cost", 0), _mk("B", "10", "subtotal", 1)],
    )
    cum = _calculate_markup_amounts(
        dc,
        [_mk("A", "10", "direct_cost", 0), _mk("B", "10", "cumulative", 1)],
    )
    assert [a for _, a in sub] == [a for _, a in cum]


# ── B-001 / B-012: commercial cents rounding ────────────────────────────


def test_b001_round_currency_half_up_not_bankers() -> None:
    # .625 → half-up → .63 (banker's would give .62)
    assert _round_currency(Decimal("1234808.625")) == 1234808.63
    # .005 → half-up → .01 (banker's would give .00)
    assert _round_currency(Decimal("0.005")) == 0.01
    # fractional-cent residue snapped to 2dp
    assert _round_currency(Decimal("1320.886791")) == 1320.89
    assert _round_currency(Decimal("999.999999999")) == 1000.00


def test_b001_round_currency_non_finite_collapses_to_zero() -> None:
    assert _round_currency(Decimal("NaN")) == 0.0
    assert _round_currency(float("inf")) == 0.0
    assert _round_currency(None) == 0.0


# ── D-TKC-004: tolerant column resolution ───────────────────────────────


def test_dtkc004_norm_col_variants_collapse() -> None:
    assert _norm_col("volume") == "volume"
    assert _norm_col("Volume (m3)") == "volume"
    assert _norm_col("volume_m3") == "volume"
    assert _norm_col("Area [m2]") == "area"
    assert _norm_col("area_m2") == "area"
    assert _norm_col("Length (m)") == "length"
    # Conservative: bare-letter suffixes must NOT mis-merge
    assert _norm_col("team") != _norm_col("tea")
    assert _norm_col("type name") == "typename"


def test_dtkc004_resolve_column_value_alias() -> None:
    el = {"category": "Walls", "Volume (m3)": 9}
    assert _resolve_column_value(el, "volume") == 9.0
    # exact key still wins fast-path
    assert _resolve_column_value({"volume": 4}, "volume") == 4.0
    # genuinely absent → 0.0
    assert _resolve_column_value({"category": "X"}, "volume") == 0.0


def test_dtkc004_dynamic_grouping_finds_aliased_columns() -> None:
    elements = [
        {"category": "Walls", "Volume (m3)": 9},
        {"category": "Walls", "Volume (m3)": 6},
    ]
    out = group_cad_elements_dynamic(elements, ["category"], ["volume"])
    assert out["grand_totals"]["volume"] == 15.0
    assert out["groups"][0]["sums"]["volume"] == 15.0


# ── D-TKC-003: grand total from RAW sums (no per-group rounding loss) ────


def test_dtkc003_tiny_quantities_do_not_vanish() -> None:
    """300 elements of 0.00004999 m³ each — true total ≈ 0.014997.

    The v1.9.0 bug rounded each one-element group to 0.0 first, then
    summed zeros → grand total 0.0 (100% loss). The fix accumulates raw
    group sums; final display rounding to 4dp gives 0.015, NOT 0.0.
    """
    elements = [{"category": f"Ci-{i}", "volume": 0.00004999} for i in range(300)]
    out = group_cad_elements_dynamic(elements, ["category"], ["volume"])
    assert out["grand_totals"]["volume"] > 0.0
    # 300 * 0.00004999 = 0.014997 → round(_, 4) == 0.015
    assert out["grand_totals"]["volume"] == 0.015


def test_dtkc003_grand_total_reconciles_when_grouped() -> None:
    elements = [
        {"cat": "A", "volume": 1.11115},
        {"cat": "A", "volume": 2.22225},
        {"cat": "B", "volume": 3.33335},
    ]
    out = group_cad_elements_dynamic(elements, ["cat"], ["volume"])
    raw = round(1.11115 + 2.22225 + 3.33335, 4)
    assert out["grand_totals"]["volume"] == raw
