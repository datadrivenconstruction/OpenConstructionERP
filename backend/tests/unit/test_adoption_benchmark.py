# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure adoption-vs-non-adoption benchmark engine.

Stdlib + pytest only - mirrors the engine's constraint so it runs on the local
Python 3.11 test runner without app.* or SQLAlchemy on the path. Outcome metrics
are exercised with Decimal (rates) and float (cycle days) literals; the adoption
score and cohort means are asserted as floats to four decimal places.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.value.adoption_benchmark import (
    COHORT_HIGH,
    COHORT_LOW,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_NONE,
    CONFIDENCE_ORDER,
    DEFAULT_ADOPTION_CUT,
    DENSITY_SATURATION,
    DENSITY_WEIGHT,
    HIGHER_IS_BETTER,
    LOWER_IS_BETTER,
    METRIC_AVG_CYCLE_DAYS,
    METRIC_OVERRUN_PCT,
    METRIC_RECOVERY_RATE,
    MIN_N_HIGH,
    MIN_N_LOW,
    MIN_N_MEDIUM,
    OUTCOME_METRICS,
    TRACEABILITY_WEIGHT,
    AdoptionBenchmark,
    CohortComparison,
    ProjectAdoption,
    ProjectScore,
    activity_density,
    adoption_score,
    cohort_for_score,
    compute_adoption_benchmark,
    median_cut,
    traceability_ratio,
)


def _proj(
    project_id: str = "P1",
    activity_count: int = 0,
    change_count: int = 0,
    traceable_change_count: int = 0,
    recovery_rate: Decimal | None = None,
    overrun_pct: Decimal | None = None,
    avg_cycle_days: float | None = None,
) -> ProjectAdoption:
    """Build a ProjectAdoption with sensible defaults for a single test."""
    return ProjectAdoption(
        project_id=project_id,
        activity_count=activity_count,
        change_count=change_count,
        traceable_change_count=traceable_change_count,
        recovery_rate=recovery_rate,
        overrun_pct=overrun_pct,
        avg_cycle_days=avg_cycle_days,
    )


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------


def test_blend_weights_sum_to_one() -> None:
    assert DENSITY_WEIGHT + TRACEABILITY_WEIGHT == 1.0


def test_default_cut_is_midpoint() -> None:
    assert DEFAULT_ADOPTION_CUT == 0.5


def test_confidence_order_weakest_first() -> None:
    assert CONFIDENCE_ORDER[0] == CONFIDENCE_NONE
    assert CONFIDENCE_ORDER[-1] == CONFIDENCE_HIGH
    # Documented threshold ladder.
    assert MIN_N_LOW < MIN_N_MEDIUM < MIN_N_HIGH


def test_outcome_metrics_directions() -> None:
    directions = dict(OUTCOME_METRICS)
    assert directions[METRIC_RECOVERY_RATE] == HIGHER_IS_BETTER
    assert directions[METRIC_OVERRUN_PCT] == LOWER_IS_BETTER
    assert directions[METRIC_AVG_CYCLE_DAYS] == LOWER_IS_BETTER


# ---------------------------------------------------------------------------
# traceability_ratio - divide-by-zero guards + clamp
# ---------------------------------------------------------------------------


def test_traceability_ratio_basic() -> None:
    assert traceability_ratio(3, 4) == 0.75


def test_traceability_ratio_zero_changes_is_zero() -> None:
    # No changes -> ratio 0, never a divide-by-zero. Even a stray traceable
    # count cannot manufacture traceability with no changes.
    assert traceability_ratio(0, 0) == 0.0
    assert traceability_ratio(5, 0) == 0.0


def test_traceability_ratio_negative_changes_is_zero() -> None:
    assert traceability_ratio(1, -3) == 0.0


def test_traceability_ratio_clamped_to_one() -> None:
    # More traceable than total (a miscount) cannot exceed 1.
    assert traceability_ratio(7, 4) == 1.0


def test_traceability_ratio_all_traceable() -> None:
    assert traceability_ratio(10, 10) == 1.0


def test_traceability_ratio_none_traceable() -> None:
    assert traceability_ratio(0, 10) == 0.0


# ---------------------------------------------------------------------------
# activity_density - saturating ratio + divide-by-zero guards
# ---------------------------------------------------------------------------


def test_activity_density_zero_changes_is_zero() -> None:
    # No changes -> density 0 regardless of how many actions were logged.
    assert activity_density(0, 0) == 0.0
    assert activity_density(100, 0) == 0.0


def test_activity_density_saturates_at_one() -> None:
    # At and beyond the saturation point (default 5 actions/change) density = 1.
    assert activity_density(5, 1) == 1.0
    assert activity_density(50, 1) == 1.0


def test_activity_density_linear_below_saturation() -> None:
    # 1 action / 1 change = ratio 1; 1 / 5 saturation = 0.2.
    assert activity_density(1, 1) == pytest.approx(0.2)
    # 10 actions / 4 changes = 2.5 per change; 2.5 / 5 = 0.5.
    assert activity_density(10, 4) == pytest.approx(0.5)


def test_activity_density_negative_activity_floored() -> None:
    assert activity_density(-10, 5) == 0.0


def test_activity_density_zero_saturation_guarded() -> None:
    # A misconfigured non-positive saturation must not divide by zero.
    assert activity_density(10, 2, saturation=0.0) == 0.0
    assert activity_density(10, 2, saturation=-1.0) == 0.0


def test_activity_density_custom_saturation() -> None:
    # With saturation 2: 2 actions / 1 change = ratio 2; 2 / 2 = 1.0.
    assert activity_density(2, 1, saturation=2.0) == 1.0
    # 1 action / 1 change = ratio 1; 1 / 2 = 0.5.
    assert activity_density(1, 1, saturation=2.0) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# adoption_score - documented blend + guards
# ---------------------------------------------------------------------------


def test_adoption_score_full_engagement() -> None:
    # Saturated density (>=5/change) AND every change traceable -> 1.0.
    p = _proj(activity_count=50, change_count=10, traceable_change_count=10)
    assert adoption_score(p) == 1.0


def test_adoption_score_zero_everything() -> None:
    # No changes -> both ratios 0 -> score 0 (and no divide-by-zero).
    assert adoption_score(_proj()) == 0.0


def test_adoption_score_is_documented_blend() -> None:
    # density: 10 actions / 5 changes = 2/change; 2/5 saturation = 0.4.
    # traceability: 3 / 5 = 0.6. Equal-weight mean = (0.4 + 0.6) / 2 = 0.5.
    p = _proj(activity_count=10, change_count=5, traceable_change_count=3)
    assert adoption_score(p) == 0.5


def test_adoption_score_density_only() -> None:
    # Saturated density, zero traceability -> 0.5 at equal weights.
    p = _proj(activity_count=100, change_count=5, traceable_change_count=0)
    assert adoption_score(p) == 0.5


def test_adoption_score_traceability_only() -> None:
    # Zero activity (density 0), full traceability -> 0.5 at equal weights.
    p = _proj(activity_count=0, change_count=5, traceable_change_count=5)
    assert adoption_score(p) == 0.5


def test_adoption_score_custom_weights_traceability_heavy() -> None:
    # density 0.4, traceability 0.6, weights 0.25 / 0.75 (normalised by sum=1):
    # 0.4*0.25 + 0.6*0.75 = 0.1 + 0.45 = 0.55.
    p = _proj(activity_count=10, change_count=5, traceable_change_count=3)
    score = adoption_score(p, density_weight=0.25, traceability_weight=0.75)
    assert score == 0.55


def test_adoption_score_weights_normalised_by_sum() -> None:
    # Weights that do not sum to 1 are normalised; 1.0/1.0 == 0.5/0.5 here.
    p = _proj(activity_count=10, change_count=5, traceable_change_count=3)
    assert adoption_score(p, density_weight=1.0, traceability_weight=1.0) == adoption_score(p)


def test_adoption_score_nonpositive_weights_zero() -> None:
    p = _proj(activity_count=50, change_count=10, traceable_change_count=10)
    assert adoption_score(p, density_weight=0.0, traceability_weight=0.0) == 0.0


def test_adoption_score_in_unit_interval() -> None:
    p = _proj(activity_count=3, change_count=7, traceable_change_count=2)
    score = adoption_score(p)
    assert 0.0 <= score <= 1.0


def test_adoption_score_quantized_four_places() -> None:
    # 1 action / 3 changes = 0.3333.../5 = 0.0666..; traceability 1/3 = 0.3333..
    # mean ~ 0.2; assert it is rounded to <= 4 decimal places.
    p = _proj(activity_count=1, change_count=3, traceable_change_count=1)
    score = adoption_score(p)
    assert round(score, 4) == score


# ---------------------------------------------------------------------------
# cohort_for_score - inclusive cut
# ---------------------------------------------------------------------------


def test_cohort_for_score_above_cut_is_high() -> None:
    assert cohort_for_score(0.8) == COHORT_HIGH


def test_cohort_for_score_below_cut_is_low() -> None:
    assert cohort_for_score(0.3) == COHORT_LOW


def test_cohort_for_score_exactly_at_cut_is_high() -> None:
    # The cut is inclusive: a project exactly on the boundary is an adopter.
    assert cohort_for_score(0.5) == COHORT_HIGH


def test_cohort_for_score_custom_cut() -> None:
    assert cohort_for_score(0.65, cut=0.7) == COHORT_LOW
    assert cohort_for_score(0.7, cut=0.7) == COHORT_HIGH


# ---------------------------------------------------------------------------
# median_cut
# ---------------------------------------------------------------------------


def test_median_cut_odd() -> None:
    assert median_cut([0.1, 0.9, 0.5]) == 0.5


def test_median_cut_even() -> None:
    # Mean of the two middle values: (0.4 + 0.6) / 2 = 0.5.
    assert median_cut([0.2, 0.4, 0.6, 0.8]) == 0.5


def test_median_cut_empty_falls_back_to_default() -> None:
    assert median_cut([]) == DEFAULT_ADOPTION_CUT


def test_median_cut_single() -> None:
    assert median_cut([0.42]) == 0.42


# ---------------------------------------------------------------------------
# compute_adoption_benchmark - scoring + cohort assignment
# ---------------------------------------------------------------------------


def test_benchmark_empty_input() -> None:
    result = compute_adoption_benchmark([])
    assert isinstance(result, AdoptionBenchmark)
    assert result.project_scores == ()
    # One comparison per metric, all means None, all confidence none.
    assert len(result.comparisons) == len(OUTCOME_METRICS)
    for comp in result.comparisons:
        assert comp.high_mean is None
        assert comp.low_mean is None
        assert comp.delta is None
        assert comp.high_n == 0
        assert comp.low_n == 0
        assert comp.confidence == CONFIDENCE_NONE
    assert result.confidence == CONFIDENCE_NONE
    assert result.high_count == 0
    assert result.low_count == 0


def test_benchmark_scores_and_splits_cohorts() -> None:
    high = _proj("HI", activity_count=50, change_count=10, traceable_change_count=10)  # 1.0
    low = _proj("LO", activity_count=1, change_count=10, traceable_change_count=0)  # ~0.01
    result = compute_adoption_benchmark([low, high])

    by_id = {s.project_id: s for s in result.project_scores}
    assert by_id["HI"].cohort == COHORT_HIGH
    assert by_id["LO"].cohort == COHORT_LOW
    assert result.high_count == 1
    assert result.low_count == 1


def test_benchmark_scores_sorted_by_adoption_desc_then_id() -> None:
    a = _proj("A", activity_count=0, change_count=4, traceable_change_count=2)  # trace .5 -> .25
    b = _proj("B", activity_count=0, change_count=4, traceable_change_count=2)  # identical score
    c = _proj("C", activity_count=50, change_count=10, traceable_change_count=10)  # 1.0
    result = compute_adoption_benchmark([a, c, b])
    order = [s.project_id for s in result.project_scores]
    # C (1.0) leads; A and B tie and break by id.
    assert order == ["C", "A", "B"]


def test_benchmark_one_score_per_project() -> None:
    projects = [_proj(f"P{i}", change_count=2, traceable_change_count=1) for i in range(5)]
    result = compute_adoption_benchmark(projects)
    assert len(result.project_scores) == 5
    assert all(isinstance(s, ProjectScore) for s in result.project_scores)


def test_benchmark_one_comparison_per_metric_in_order() -> None:
    result = compute_adoption_benchmark([_proj(change_count=1)])
    assert [c.metric for c in result.comparisons] == [m for m, _ in OUTCOME_METRICS]
    assert all(isinstance(c, CohortComparison) for c in result.comparisons)


# ---------------------------------------------------------------------------
# cohort comparison - means ignore None, delta signs, favours_high
# ---------------------------------------------------------------------------


def _two_cohort_portfolio() -> list[ProjectAdoption]:
    """Two clear adopters and two clear non-adopters with outcome metrics.

    Adopters recover more (0.9 vs 0.4), overrun less (0.05 vs 0.20) and close
    changes faster (10 vs 30 days) - the report's headline contrast.
    """
    adopters = [
        _proj(
            "A1",
            activity_count=50,
            change_count=10,
            traceable_change_count=10,
            recovery_rate=Decimal("0.90"),
            overrun_pct=Decimal("0.05"),
            avg_cycle_days=10.0,
        ),
        _proj(
            "A2",
            activity_count=60,
            change_count=12,
            traceable_change_count=12,
            recovery_rate=Decimal("0.90"),
            overrun_pct=Decimal("0.05"),
            avg_cycle_days=10.0,
        ),
    ]
    laggards = [
        _proj(
            "L1",
            activity_count=1,
            change_count=10,
            traceable_change_count=0,
            recovery_rate=Decimal("0.40"),
            overrun_pct=Decimal("0.20"),
            avg_cycle_days=30.0,
        ),
        _proj(
            "L2",
            activity_count=1,
            change_count=12,
            traceable_change_count=0,
            recovery_rate=Decimal("0.40"),
            overrun_pct=Decimal("0.20"),
            avg_cycle_days=30.0,
        ),
    ]
    return adopters + laggards


def _comp(result: AdoptionBenchmark, metric: str) -> CohortComparison:
    return next(c for c in result.comparisons if c.metric == metric)


def test_comparison_means_and_counts() -> None:
    result = compute_adoption_benchmark(_two_cohort_portfolio())
    rec = _comp(result, METRIC_RECOVERY_RATE)
    assert rec.high_mean == 0.9
    assert rec.low_mean == 0.4
    assert rec.high_n == 2
    assert rec.low_n == 2


def test_comparison_delta_is_high_minus_low() -> None:
    result = compute_adoption_benchmark(_two_cohort_portfolio())
    rec = _comp(result, METRIC_RECOVERY_RATE)
    # 0.9 - 0.4 = 0.5.
    assert rec.delta == pytest.approx(0.5)


def test_comparison_higher_is_better_favours_high_on_positive_delta() -> None:
    result = compute_adoption_benchmark(_two_cohort_portfolio())
    rec = _comp(result, METRIC_RECOVERY_RATE)
    assert rec.higher_is_better is True
    # Adopters recovered more -> positive delta favours high.
    assert rec.favours_high is True


def test_comparison_lower_is_better_favours_high_on_negative_delta() -> None:
    result = compute_adoption_benchmark(_two_cohort_portfolio())
    overrun = _comp(result, METRIC_OVERRUN_PCT)
    assert overrun.higher_is_better is False
    # Adopters overran LESS: delta = 0.05 - 0.20 = -0.15 (negative), and for a
    # lower-is-better metric a negative delta favours the adopters.
    assert overrun.delta == pytest.approx(-0.15)
    assert overrun.favours_high is True

    cycle = _comp(result, METRIC_AVG_CYCLE_DAYS)
    assert cycle.delta == pytest.approx(-20.0)
    assert cycle.favours_high is True


def test_comparison_mean_ignores_none_values() -> None:
    # One adopter has no recovery_rate; its None must be excluded from BOTH the
    # mean and the contributing count, not treated as zero.
    adopters = [
        _proj("A1", activity_count=50, change_count=10, traceable_change_count=10, recovery_rate=Decimal("0.80")),
        _proj("A2", activity_count=50, change_count=10, traceable_change_count=10, recovery_rate=None),
    ]
    laggards = [
        _proj("L1", activity_count=1, change_count=10, traceable_change_count=0, recovery_rate=Decimal("0.40")),
        _proj("L2", activity_count=1, change_count=10, traceable_change_count=0, recovery_rate=Decimal("0.40")),
    ]
    result = compute_adoption_benchmark(adopters + laggards)
    rec = _comp(result, METRIC_RECOVERY_RATE)
    # High mean is 0.80 over ONE contributor, not (0.80+0)/2.
    assert rec.high_mean == 0.8
    assert rec.high_n == 1
    assert rec.low_n == 2


def test_comparison_all_none_metric_yields_none_mean() -> None:
    # avg_cycle_days is None everywhere -> both means None, delta None, no conf.
    result = compute_adoption_benchmark(
        [
            _proj("A1", activity_count=50, change_count=10, traceable_change_count=10),
            _proj("L1", activity_count=1, change_count=10, traceable_change_count=0),
        ]
    )
    cycle = _comp(result, METRIC_AVG_CYCLE_DAYS)
    assert cycle.high_mean is None
    assert cycle.low_mean is None
    assert cycle.delta is None
    assert cycle.high_n == 0
    assert cycle.low_n == 0
    assert cycle.confidence == CONFIDENCE_NONE


def test_comparison_equal_means_delta_zero_favours_neither() -> None:
    # Both cohorts at the same recovery rate -> delta 0, favours_high None.
    adopters = [
        _proj(f"A{i}", activity_count=50, change_count=10, traceable_change_count=10, recovery_rate=Decimal("0.50"))
        for i in range(2)
    ]
    laggards = [
        _proj(f"L{i}", activity_count=1, change_count=10, traceable_change_count=0, recovery_rate=Decimal("0.50"))
        for i in range(2)
    ]
    result = compute_adoption_benchmark(adopters + laggards)
    rec = _comp(result, METRIC_RECOVERY_RATE)
    assert rec.delta == 0.0
    assert rec.favours_high is None


# ---------------------------------------------------------------------------
# confidence - thresholds, empty cohort -> none, overall = weakest
# ---------------------------------------------------------------------------


def _cohorted(n_high: int, n_low: int, *, with_metric: bool = True) -> list[ProjectAdoption]:
    """n_high adopters and n_low laggards, all carrying a recovery_rate."""
    rate_hi = Decimal("0.90") if with_metric else None
    rate_lo = Decimal("0.40") if with_metric else None
    high = [
        _proj(f"H{i}", activity_count=50, change_count=10, traceable_change_count=10, recovery_rate=rate_hi)
        for i in range(n_high)
    ]
    low = [
        _proj(f"L{i}", activity_count=1, change_count=10, traceable_change_count=0, recovery_rate=rate_lo)
        for i in range(n_low)
    ]
    return high + low


def test_confidence_none_when_a_cohort_is_empty() -> None:
    # All adopters, no laggards -> low_n 0 -> none, however many adopters.
    result = compute_adoption_benchmark(_cohorted(8, 0))
    rec = _comp(result, METRIC_RECOVERY_RATE)
    assert rec.low_n == 0
    assert rec.confidence == CONFIDENCE_NONE


def test_confidence_none_below_min_n() -> None:
    # One vs one is an anecdote: min_n 1 < MIN_N_LOW -> none.
    result = compute_adoption_benchmark(_cohorted(1, 1))
    rec = _comp(result, METRIC_RECOVERY_RATE)
    assert rec.confidence == CONFIDENCE_NONE


def test_confidence_low_at_threshold() -> None:
    # min_n == MIN_N_LOW (2) but below MIN_N_MEDIUM -> low.
    result = compute_adoption_benchmark(_cohorted(MIN_N_LOW, MIN_N_LOW))
    rec = _comp(result, METRIC_RECOVERY_RATE)
    assert rec.confidence == CONFIDENCE_LOW


def test_confidence_medium_at_threshold() -> None:
    result = compute_adoption_benchmark(_cohorted(MIN_N_MEDIUM, MIN_N_MEDIUM))
    rec = _comp(result, METRIC_RECOVERY_RATE)
    assert rec.confidence == CONFIDENCE_MEDIUM


def test_confidence_high_at_threshold() -> None:
    result = compute_adoption_benchmark(_cohorted(MIN_N_HIGH, MIN_N_HIGH))
    rec = _comp(result, METRIC_RECOVERY_RATE)
    assert rec.confidence == CONFIDENCE_HIGH


def test_confidence_driven_by_smaller_cohort() -> None:
    # Many adopters but only MIN_N_LOW laggards -> capped at low by the smaller.
    result = compute_adoption_benchmark(_cohorted(MIN_N_HIGH, MIN_N_LOW))
    rec = _comp(result, METRIC_RECOVERY_RATE)
    assert rec.confidence == CONFIDENCE_LOW


def test_overall_confidence_is_weakest_comparison() -> None:
    # recovery_rate present on everyone (would be at least low) but cycle days
    # present on nobody -> that comparison is none -> overall none.
    result = compute_adoption_benchmark(_cohorted(MIN_N_HIGH, MIN_N_HIGH))
    # recovery has data on both big cohorts...
    assert _comp(result, METRIC_RECOVERY_RATE).confidence == CONFIDENCE_HIGH
    # ...but overrun_pct and avg_cycle_days are None everywhere -> none...
    assert _comp(result, METRIC_AVG_CYCLE_DAYS).confidence == CONFIDENCE_NONE
    # ...so the overall is the weakest, none.
    assert result.confidence == CONFIDENCE_NONE


def test_overall_confidence_high_when_all_metrics_present() -> None:
    # Every project carries all three metrics, big balanced cohorts -> high.
    high = [
        _proj(
            f"H{i}",
            activity_count=50,
            change_count=10,
            traceable_change_count=10,
            recovery_rate=Decimal("0.90"),
            overrun_pct=Decimal("0.05"),
            avg_cycle_days=10.0,
        )
        for i in range(MIN_N_HIGH)
    ]
    low = [
        _proj(
            f"L{i}",
            activity_count=1,
            change_count=10,
            traceable_change_count=0,
            recovery_rate=Decimal("0.40"),
            overrun_pct=Decimal("0.20"),
            avg_cycle_days=30.0,
        )
        for i in range(MIN_N_HIGH)
    ]
    result = compute_adoption_benchmark(high + low)
    assert all(c.confidence == CONFIDENCE_HIGH for c in result.comparisons)
    assert result.confidence == CONFIDENCE_HIGH


# ---------------------------------------------------------------------------
# determinism + median-cut wiring
# ---------------------------------------------------------------------------


def test_benchmark_is_deterministic() -> None:
    portfolio = _two_cohort_portfolio()
    a = compute_adoption_benchmark(portfolio)
    b = compute_adoption_benchmark(list(reversed(portfolio)))
    assert a == b


def test_benchmark_with_median_cut_splits_clustered_portfolio() -> None:
    # Three projects all below the fixed 0.5 cut would land entirely in LOW; a
    # median cut splits them so a comparison becomes possible.
    projects = [
        _proj("A", activity_count=0, change_count=10, traceable_change_count=1, recovery_rate=Decimal("0.30")),  # .05
        _proj("B", activity_count=0, change_count=10, traceable_change_count=4, recovery_rate=Decimal("0.50")),  # .20
        _proj("C", activity_count=0, change_count=10, traceable_change_count=7, recovery_rate=Decimal("0.70")),  # .35
    ]
    scores = [adoption_score(p) for p in projects]
    # Confirm the premise: all three are under the default fixed cut.
    assert all(s < DEFAULT_ADOPTION_CUT for s in scores)

    fixed = compute_adoption_benchmark(projects)
    assert fixed.high_count == 0  # everyone LOW under the fixed cut

    cut = median_cut(scores)
    med = compute_adoption_benchmark(projects, cut=cut)
    # The median split puts at least the top scorer in HIGH.
    assert med.high_count >= 1
    assert med.low_count >= 1


def test_benchmark_custom_saturation_changes_scores() -> None:
    # A gentler saturation makes the same activity count look like more adoption.
    p = _proj("P", activity_count=2, change_count=10, traceable_change_count=0)
    default = adoption_score(p)
    gentler = adoption_score(p, saturation=DENSITY_SATURATION / 5.0)
    assert gentler > default
