# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure unit tests for the rate-sanity benchmark bands.

No DB, no HTTP, no AI key, no Qdrant. These pin the deterministic band-factor
table and the median/outlier helpers that the multi-pass mapping's third pass
(rate sanity) uses to flag implausible candidate rates without ever inventing or
dropping a real catalogue rate.

Covered:
    * The default band factor is the founder-locked 8x.
    * Every override key is a real ``(trade, unit)`` pair that the curated work
      packages actually emit, and a real taxonomy trade. The table cannot drift.
    * The median helper handles the empty-catalogue and single-candidate edges.
    * Non-positive rates are ignored so they never drag the anchor to zero.
    * The outlier test flags both high-side and low-side outliers and is inert
      when there is nothing to anchor against.

Run:
    cd backend
    python -m pytest tests/unit/ai_estimator/test_benchmarks.py -q
"""

from __future__ import annotations

from app.modules.ai_estimator.benchmarks import (
    BAND_FACTOR_OVERRIDES,
    DEFAULT_BAND_FACTOR,
    band_factor_for,
    candidate_median,
    evaluate_band,
    is_outlier,
)
from app.modules.ai_estimator.project_types import PROJECT_TYPES
from app.modules.ai_estimator.taxonomy import TRADE_ORDER

# ── Curated (trade, unit) pairs the work packages actually emit ───────────────


def _real_trade_unit_pairs() -> set[tuple[str, str]]:
    """Every ``(trade, unit)`` pair a curated work package emits."""
    pairs: set[tuple[str, str]] = set()
    for pt in PROJECT_TYPES.values():
        for pkg in pt.packages:
            pairs.add((pkg.trade, pkg.unit))
    return pairs


# ── Default band factor ───────────────────────────────────────────────────────


def test_default_band_factor_is_eight() -> None:
    """The founder-locked default (design section 10, decision 2) is 8x."""
    assert DEFAULT_BAND_FACTOR == 8.0


def test_band_factor_for_unknown_pair_falls_back_to_default() -> None:
    """A pair with no override gets the global default."""
    assert band_factor_for("finishes", "m2") == DEFAULT_BAND_FACTOR
    # An entirely unknown pair still falls back cleanly (never raises).
    assert band_factor_for("nonsense", "furlong") == DEFAULT_BAND_FACTOR


def test_band_factor_for_uses_override_when_present() -> None:
    """An override key returns its widened/tightened factor, not the default."""
    assert band_factor_for("other", "lsum") == 12.0
    assert band_factor_for("demolition", "m2") == 6.0


# ── Override-table integrity (the table cannot drift) ─────────────────────────


def test_every_override_key_is_a_real_trade_unit_pair() -> None:
    """Each override key must be a (trade, unit) the curated packages emit."""
    real_pairs = _real_trade_unit_pairs()
    for trade, unit in BAND_FACTOR_OVERRIDES:
        assert (trade, unit) in real_pairs, (
            f"benchmark override ({trade!r}, {unit!r}) is not a real curated work-package (trade, unit) pair"
        )


def test_every_override_trade_is_a_known_taxonomy_trade() -> None:
    """Each override trade is a real taxonomy bucket (no typos)."""
    for trade, _unit in BAND_FACTOR_OVERRIDES:
        assert trade in TRADE_ORDER, f"override trade {trade!r} not in taxonomy"


def test_all_band_factors_are_at_least_one() -> None:
    """A factor below 1.0 would flag the median itself; never allowed."""
    assert DEFAULT_BAND_FACTOR >= 1.0
    for factor in BAND_FACTOR_OVERRIDES.values():
        assert factor >= 1.0


# ── candidate_median edges ────────────────────────────────────────────────────


def test_candidate_median_empty_catalogue_returns_none() -> None:
    """Empty catalogue / no candidates: nothing to anchor against."""
    assert candidate_median([]) is None


def test_candidate_median_single_candidate_returns_that_rate() -> None:
    """A single candidate is its own median; it can never be an outlier."""
    assert candidate_median([42.0]) == 42.0


def test_candidate_median_multiple_candidates() -> None:
    """The median of an odd set is the middle value."""
    assert candidate_median([10.0, 20.0, 30.0]) == 20.0


def test_candidate_median_even_set_averages_middle_two() -> None:
    """An even set averages the two central values (statistics.median)."""
    assert candidate_median([10.0, 20.0, 30.0, 40.0]) == 25.0


def test_candidate_median_ignores_non_positive_rates() -> None:
    """Zero / negative rates are dropped so they never sink the anchor."""
    # The two zeros are ignored; median of [10, 20] is 15.
    assert candidate_median([0.0, 10.0, 20.0, -5.0]) == 15.0


def test_candidate_median_all_non_positive_returns_none() -> None:
    """When nothing usable remains there is no anchor."""
    assert candidate_median([0.0, -1.0, 0.0]) is None


# ── is_outlier ────────────────────────────────────────────────────────────────


def test_is_outlier_flags_high_side() -> None:
    """A rate above median * factor is an outlier."""
    assert is_outlier(rate=100.0, median_rate=10.0, band_factor=8.0) is True


def test_is_outlier_flags_low_side() -> None:
    """A rate below median / factor is an outlier."""
    assert is_outlier(rate=1.0, median_rate=10.0, band_factor=8.0) is True


def test_is_outlier_within_band_is_not_flagged() -> None:
    """A rate inside the band is fine, including at the boundary."""
    assert is_outlier(rate=70.0, median_rate=10.0, band_factor=8.0) is False
    # Exactly on the high edge (10 * 8 = 80) is not strictly greater -> kept.
    assert is_outlier(rate=80.0, median_rate=10.0, band_factor=8.0) is False


def test_is_outlier_inert_without_median() -> None:
    """No median -> nothing can be flagged (single-candidate / empty case)."""
    assert is_outlier(rate=1000.0, median_rate=None, band_factor=8.0) is False


def test_is_outlier_inert_on_non_positive_inputs() -> None:
    """Non-positive rate / median / factor never flags (degrade gracefully)."""
    assert is_outlier(rate=0.0, median_rate=10.0, band_factor=8.0) is False
    assert is_outlier(rate=10.0, median_rate=0.0, band_factor=8.0) is False
    assert is_outlier(rate=10.0, median_rate=10.0, band_factor=0.0) is False


def test_single_candidate_is_never_its_own_outlier() -> None:
    """The single-candidate edge end to end: median == rate, not an outlier."""
    rates = [55.0]
    med = candidate_median(rates)
    assert med == 55.0
    assert is_outlier(rate=55.0, median_rate=med, band_factor=band_factor_for("finishes", "m2")) is False


# ── evaluate_band (trace convenience wrapper) ─────────────────────────────────


def test_evaluate_band_returns_bounds_and_factor() -> None:
    """The band bounds are median / factor and median * factor."""
    low, high, factor = evaluate_band("finishes", "m2", [10.0, 20.0, 30.0])
    assert factor == 8.0
    assert low == 20.0 / 8.0
    assert high == 20.0 * 8.0


def test_evaluate_band_empty_set_has_no_bounds() -> None:
    """Empty catalogue: no median, so the bounds are None but the factor stands."""
    low, high, factor = evaluate_band("finishes", "m2", [])
    assert low is None
    assert high is None
    assert factor == 8.0


def test_evaluate_band_honours_override() -> None:
    """A wider-spread trade carries its override factor into the bounds."""
    low, high, factor = evaluate_band("other", "lsum", [100.0])
    assert factor == 12.0
    assert low == 100.0 / 12.0
    assert high == 100.0 * 12.0
