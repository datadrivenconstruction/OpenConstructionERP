# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure predictive delay / overrun risk engine.

Stdlib + pytest only - mirrors the engine's constraint so it runs on the local
Python 3.11 test runner without app.* or SQLAlchemy on the path. The tests are
table-driven where it helps and lock in the contract the delay-risk feature
depends on: every feature transform is monotonic (worsening any one feature
never lowers the risk), the factor ranking surfaces the true dominant driver,
the documented band boundaries, the documented saturation points, a
hand-computed Brier value, calibration bucketing, and empty input. Everything is
deterministic.
"""

from __future__ import annotations

import pytest

from app.modules.change_intelligence.delay_risk import (
    BAND_ELEVATED,
    BAND_HIGH,
    BAND_LOW,
    DWELL_RATIO_SATURATION,
    ELEVATED_THRESHOLD,
    FACTOR_DWELL,
    FACTOR_HOLDER_RATE,
    FACTOR_LOAD,
    FACTOR_SIZE,
    HIGH_THRESHOLD,
    LOAD_SATURATION_COUNT,
    SIZE_RATIO_SATURATION,
    TOTAL_WEIGHT,
    W_DWELL,
    W_HOLDER_RATE,
    W_LOAD,
    W_SIZE,
    BacktestResult,
    CalibrationBucket,
    DelayRiskInput,
    DelayRiskResult,
    Prediction,
    RiskFactor,
    backtest,
    band_for_risk,
    brier_score,
    calibration_buckets,
    clamp01,
    dwell_pressure,
    load_pressure,
    rank,
    score,
    size_pressure,
)


def _inp(
    change_id: str = "C-1",
    step_mean_dwell_days: float = 0.0,
    step_sla_days: float = 10.0,
    holder_overdue_rate: float = 0.0,
    change_size_ratio: float = 0.0,
    holder_open_change_count: int = 0,
) -> DelayRiskInput:
    """Build a DelayRiskInput with clean, on-time, low-risk defaults."""
    return DelayRiskInput(
        change_id=change_id,
        step_mean_dwell_days=step_mean_dwell_days,
        step_sla_days=step_sla_days,
        holder_overdue_rate=holder_overdue_rate,
        change_size_ratio=change_size_ratio,
        holder_open_change_count=holder_open_change_count,
    )


# --------------------------------------------------------------------------- #
# weighting table
# --------------------------------------------------------------------------- #


def test_weights_sum_to_total_weight() -> None:
    assert W_DWELL + W_HOLDER_RATE + W_SIZE + W_LOAD == TOTAL_WEIGHT


def test_dwell_is_the_dominant_factor() -> None:
    # A change running far past its service target is the strongest overrun
    # signal, so dwell carries the most weight.
    assert W_DWELL > W_HOLDER_RATE
    assert W_DWELL > W_SIZE
    assert W_DWELL > W_LOAD


# --------------------------------------------------------------------------- #
# clamp01
# --------------------------------------------------------------------------- #


def test_clamp01_bounds() -> None:
    assert clamp01(-0.5) == 0.0
    assert clamp01(1.5) == 1.0
    assert clamp01(0.3) == pytest.approx(0.3)


# --------------------------------------------------------------------------- #
# dwell_pressure sub-score
# --------------------------------------------------------------------------- #


def test_dwell_pressure_on_or_under_target_is_zero() -> None:
    assert dwell_pressure(0.0, 10.0) == 0.0
    assert dwell_pressure(5.0, 10.0) == 0.0
    assert dwell_pressure(10.0, 10.0) == 0.0  # exactly at SLA -> still on time
    assert dwell_pressure(-3.0, 10.0) == 0.0  # negative dwell clamped


def test_dwell_pressure_ramps_then_saturates() -> None:
    sla = 10.0
    # Midpoint of the ramp: ratio == (1 + SATURATION) / 2 -> sub-score 0.5.
    mid_ratio = (1.0 + DWELL_RATIO_SATURATION) / 2.0
    assert dwell_pressure(mid_ratio * sla, sla) == pytest.approx(0.5)
    # At the saturation multiple -> 1.0, and beyond stays 1.0.
    assert dwell_pressure(DWELL_RATIO_SATURATION * sla, sla) == pytest.approx(1.0)
    assert dwell_pressure(DWELL_RATIO_SATURATION * sla * 5, sla) == pytest.approx(1.0)


def test_dwell_pressure_non_positive_sla_saturates_on_any_dwell() -> None:
    # No positive target: any positive dwell is over target -> 1.0; zero -> 0.0.
    assert dwell_pressure(0.0, 0.0) == 0.0
    assert dwell_pressure(1.0, 0.0) == 1.0
    assert dwell_pressure(1.0, -5.0) == 1.0


def test_dwell_pressure_is_monotonic_in_dwell() -> None:
    sla = 12.0
    prev = -1.0
    for dwell in (0.0, 6.0, 12.0, 18.0, 24.0, 36.0, 48.0):
        cur = dwell_pressure(dwell, sla)
        assert cur >= prev
        prev = cur


# --------------------------------------------------------------------------- #
# size_pressure sub-score
# --------------------------------------------------------------------------- #


def test_size_pressure_zero_and_negative() -> None:
    assert size_pressure(0.0) == 0.0
    assert size_pressure(-0.1) == 0.0


def test_size_pressure_ramps_then_saturates() -> None:
    assert size_pressure(SIZE_RATIO_SATURATION / 2.0) == pytest.approx(0.5)
    assert size_pressure(SIZE_RATIO_SATURATION) == pytest.approx(1.0)
    assert size_pressure(SIZE_RATIO_SATURATION * 10) == pytest.approx(1.0)


def test_size_pressure_is_monotonic() -> None:
    prev = -1.0
    for ratio in (0.0, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0):
        cur = size_pressure(ratio)
        assert cur >= prev
        prev = cur


# --------------------------------------------------------------------------- #
# load_pressure sub-score
# --------------------------------------------------------------------------- #


def test_load_pressure_zero_and_negative() -> None:
    assert load_pressure(0) == 0.0
    assert load_pressure(-4) == 0.0


def test_load_pressure_ramps_then_saturates() -> None:
    assert load_pressure(int(LOAD_SATURATION_COUNT // 2)) == pytest.approx(0.5)
    assert load_pressure(int(LOAD_SATURATION_COUNT)) == pytest.approx(1.0)
    assert load_pressure(int(LOAD_SATURATION_COUNT) * 3) == pytest.approx(1.0)


def test_load_pressure_is_monotonic() -> None:
    prev = -1.0
    for count in (0, 1, 3, 5, 10, 20, 50):
        cur = load_pressure(count)
        assert cur >= prev
        prev = cur


# --------------------------------------------------------------------------- #
# score - extremes and structure
# --------------------------------------------------------------------------- #


def test_clean_change_scores_zero_and_low() -> None:
    result = score(_inp())
    assert result.risk == 0.0
    assert result.band == BAND_LOW
    # Every factor contributes nothing.
    assert all(f.contribution == 0.0 for f in result.top_factors)


def test_worst_case_change_scores_max_and_high() -> None:
    result = score(
        _inp(
            step_mean_dwell_days=DWELL_RATIO_SATURATION * 10.0,
            step_sla_days=10.0,
            holder_overdue_rate=1.0,
            change_size_ratio=SIZE_RATIO_SATURATION,
            holder_open_change_count=int(LOAD_SATURATION_COUNT),
        )
    )
    assert result.risk == pytest.approx(1.0)
    assert result.band == BAND_HIGH


def test_change_id_carried_through() -> None:
    assert score(_inp(change_id="CO-77")).change_id == "CO-77"


def test_result_has_all_four_factors() -> None:
    result = score(_inp(step_mean_dwell_days=20.0, step_sla_days=10.0, holder_overdue_rate=0.5))
    names = {f.name for f in result.top_factors}
    assert names == {FACTOR_DWELL, FACTOR_HOLDER_RATE, FACTOR_SIZE, FACTOR_LOAD}
    assert len(result.top_factors) == 4


def test_risk_in_unit_interval_for_extreme_inputs() -> None:
    worst = score(
        _inp(
            step_mean_dwell_days=99999.0,
            step_sla_days=1.0,
            holder_overdue_rate=99.0,
            change_size_ratio=99.0,
            holder_open_change_count=99999,
        )
    )
    best = score(
        _inp(
            step_mean_dwell_days=-50.0,
            step_sla_days=10.0,
            holder_overdue_rate=-1.0,
            change_size_ratio=-1.0,
            holder_open_change_count=-99,
        )
    )
    assert 0.0 <= worst.risk <= 1.0
    assert 0.0 <= best.risk <= 1.0
    assert best.risk == 0.0


def test_factor_contributions_sum_to_risk() -> None:
    result = score(
        _inp(
            step_mean_dwell_days=25.0,
            step_sla_days=10.0,
            holder_overdue_rate=0.4,
            change_size_ratio=0.06,
            holder_open_change_count=4,
        )
    )
    assert sum(f.contribution for f in result.top_factors) == pytest.approx(result.risk, abs=1e-6)


def test_score_against_hand_computed_blend() -> None:
    # dwell ratio 2.0 -> (2-1)/(3-1) = 0.5; holder 0.4; size 0.10/0.20 = 0.5;
    # load 5/10 = 0.5. Weighted: 0.5*45 + 0.4*25 + 0.5*15 + 0.5*15 = 47.5;
    # /100 = 0.475.
    result = score(
        _inp(
            step_mean_dwell_days=20.0,
            step_sla_days=10.0,
            holder_overdue_rate=0.4,
            change_size_ratio=0.10,
            holder_open_change_count=5,
        )
    )
    assert result.risk == pytest.approx(0.475)
    assert result.band == BAND_ELEVATED


# --------------------------------------------------------------------------- #
# per-feature monotonicity through the full score
# --------------------------------------------------------------------------- #


def test_more_dwell_never_lowers_risk() -> None:
    prev = -1.0
    for dwell in (0.0, 5.0, 10.0, 15.0, 20.0, 30.0, 40.0):
        cur = score(_inp(step_mean_dwell_days=dwell, step_sla_days=10.0)).risk
        assert cur >= prev
        prev = cur


def test_higher_holder_overdue_rate_never_lowers_risk() -> None:
    prev = -1.0
    for rate in (0.0, 0.1, 0.25, 0.5, 0.75, 1.0):
        cur = score(_inp(holder_overdue_rate=rate)).risk
        assert cur >= prev
        prev = cur


def test_larger_change_never_lowers_risk() -> None:
    prev = -1.0
    for ratio in (0.0, 0.01, 0.05, 0.1, 0.2, 0.5):
        cur = score(_inp(change_size_ratio=ratio)).risk
        assert cur >= prev
        prev = cur


def test_heavier_holder_load_never_lowers_risk() -> None:
    prev = -1.0
    for count in (0, 1, 3, 5, 10, 25):
        cur = score(_inp(holder_open_change_count=count)).risk
        assert cur >= prev
        prev = cur


@pytest.mark.parametrize(
    "worsen",
    [
        dict(step_mean_dwell_days=30.0),
        dict(holder_overdue_rate=0.9),
        dict(change_size_ratio=0.18),
        dict(holder_open_change_count=9),
    ],
)
def test_worsening_any_single_feature_never_lowers_risk(worsen: dict) -> None:
    # Start from a mid-risk baseline so no factor is already saturated, then
    # worsen exactly one feature; the risk must not drop.
    base_kwargs = dict(
        step_mean_dwell_days=12.0,
        step_sla_days=10.0,
        holder_overdue_rate=0.3,
        change_size_ratio=0.04,
        holder_open_change_count=2,
    )
    base = score(_inp(**base_kwargs)).risk
    worse_kwargs = dict(base_kwargs)
    worse_kwargs.update(worsen)
    worse = score(_inp(**worse_kwargs)).risk
    assert worse >= base


# --------------------------------------------------------------------------- #
# factor ranking / dominant driver
# --------------------------------------------------------------------------- #


def test_top_factors_sorted_by_contribution_desc() -> None:
    result = score(
        _inp(
            step_mean_dwell_days=20.0,
            step_sla_days=10.0,
            holder_overdue_rate=0.4,
            change_size_ratio=0.10,
            holder_open_change_count=5,
        )
    )
    contributions = [f.contribution for f in result.top_factors]
    assert contributions == sorted(contributions, reverse=True)


@pytest.mark.parametrize(
    ("kwargs", "expected_top"),
    [
        # Only dwell is bad.
        (dict(step_mean_dwell_days=DWELL_RATIO_SATURATION * 10.0, step_sla_days=10.0), FACTOR_DWELL),
        # On time everywhere else, only the holder runs overdue.
        (dict(holder_overdue_rate=1.0), FACTOR_HOLDER_RATE),
        # On time everywhere else, only the change is huge.
        (dict(change_size_ratio=SIZE_RATIO_SATURATION), FACTOR_SIZE),
        # On time everywhere else, only the holder is overloaded.
        (dict(holder_open_change_count=int(LOAD_SATURATION_COUNT)), FACTOR_LOAD),
    ],
)
def test_each_factor_can_be_the_top_driver(kwargs: dict, expected_top: str) -> None:
    result = score(_inp(**kwargs))
    assert result.top_factors[0].name == expected_top


def test_dominant_driver_is_the_dwell_lever_when_all_equal_subscores() -> None:
    # All four sub-scores equal (1.0); the highest-weighted factor (dwell) must
    # rank first by contribution.
    result = score(
        _inp(
            step_mean_dwell_days=DWELL_RATIO_SATURATION * 10.0,
            step_sla_days=10.0,
            holder_overdue_rate=1.0,
            change_size_ratio=SIZE_RATIO_SATURATION,
            holder_open_change_count=int(LOAD_SATURATION_COUNT),
        )
    )
    assert result.top_factors[0].name == FACTOR_DWELL
    # Weight order is reflected: dwell >= holder_rate, and size/load tie last.
    by_name = {f.name: f.contribution for f in result.top_factors}
    assert by_name[FACTOR_DWELL] >= by_name[FACTOR_HOLDER_RATE]
    assert by_name[FACTOR_HOLDER_RATE] >= by_name[FACTOR_SIZE]
    assert by_name[FACTOR_SIZE] == pytest.approx(by_name[FACTOR_LOAD])


def test_contribution_tie_breaks_to_earlier_factor_order() -> None:
    # Size and load share the same weight; drive both sub-scores to 1.0 and
    # nothing else, so they tie on contribution. Size precedes load in the fixed
    # order, so it must come first among the tied pair.
    result = score(
        _inp(
            change_size_ratio=SIZE_RATIO_SATURATION,
            holder_open_change_count=int(LOAD_SATURATION_COUNT),
        )
    )
    names_in_order = [f.name for f in result.top_factors]
    assert names_in_order.index(FACTOR_SIZE) < names_in_order.index(FACTOR_LOAD)


# --------------------------------------------------------------------------- #
# banding
# --------------------------------------------------------------------------- #


def test_band_thresholds_are_inclusive_lower_bounds() -> None:
    assert band_for_risk(1.0) == BAND_HIGH
    assert band_for_risk(HIGH_THRESHOLD) == BAND_HIGH
    assert band_for_risk(HIGH_THRESHOLD - 0.0001) == BAND_ELEVATED
    assert band_for_risk(ELEVATED_THRESHOLD) == BAND_ELEVATED
    assert band_for_risk(ELEVATED_THRESHOLD - 0.0001) == BAND_LOW
    assert band_for_risk(0.0) == BAND_LOW


def test_result_band_matches_band_for_risk() -> None:
    for kwargs in (
        dict(),
        dict(step_mean_dwell_days=14.0, step_sla_days=10.0, holder_overdue_rate=0.3),
        dict(
            step_mean_dwell_days=40.0,
            step_sla_days=10.0,
            holder_overdue_rate=1.0,
            change_size_ratio=SIZE_RATIO_SATURATION,
            holder_open_change_count=int(LOAD_SATURATION_COUNT),
        ),
    ):
        result = score(_inp(**kwargs))
        assert result.band == band_for_risk(result.risk)


# --------------------------------------------------------------------------- #
# rank
# --------------------------------------------------------------------------- #


def test_rank_sorts_by_risk_descending() -> None:
    inputs = [
        _inp(change_id="a", step_mean_dwell_days=0.0, step_sla_days=10.0),
        _inp(
            change_id="b",
            step_mean_dwell_days=40.0,
            step_sla_days=10.0,
            holder_overdue_rate=1.0,
            change_size_ratio=SIZE_RATIO_SATURATION,
            holder_open_change_count=int(LOAD_SATURATION_COUNT),
        ),
        _inp(change_id="c", step_mean_dwell_days=15.0, step_sla_days=10.0, holder_overdue_rate=0.3),
    ]
    ranked = rank(inputs)
    risks = [r.risk for r in ranked]
    assert risks == sorted(risks, reverse=True)
    assert ranked[0].change_id == "b"


def test_rank_ties_break_by_change_id_ascending() -> None:
    # Three clean changes all score 0.0 -> tie on risk; change_id ascending.
    inputs = [
        _inp(change_id="z"),
        _inp(change_id="a"),
        _inp(change_id="m"),
    ]
    ranked = rank(inputs)
    assert [r.change_id for r in ranked] == ["a", "m", "z"]


def test_rank_is_deterministic() -> None:
    inputs = [
        _inp(change_id=f"c{i}", step_mean_dwell_days=float(i), step_sla_days=10.0, holder_overdue_rate=0.2)
        for i in range(6)
    ]
    a = rank(inputs)
    b = rank(inputs)
    assert [(r.change_id, r.risk) for r in a] == [(r.change_id, r.risk) for r in b]


def test_rank_empty_input() -> None:
    assert rank([]) == []


# --------------------------------------------------------------------------- #
# backtest - Brier score
# --------------------------------------------------------------------------- #


def test_brier_score_hand_computed() -> None:
    # (0.9-1)^2 + (0.2-0)^2 + (0.7-1)^2 + (0.4-0)^2
    #   = 0.01 + 0.04 + 0.09 + 0.16 = 0.30; mean over 4 = 0.075.
    predictions = [
        Prediction(predicted_risk=0.9, actual_delayed=True),
        Prediction(predicted_risk=0.2, actual_delayed=False),
        Prediction(predicted_risk=0.7, actual_delayed=True),
        Prediction(predicted_risk=0.4, actual_delayed=False),
    ]
    assert brier_score(predictions) == pytest.approx(0.075)


def test_brier_score_perfect_is_zero() -> None:
    predictions = [
        Prediction(predicted_risk=1.0, actual_delayed=True),
        Prediction(predicted_risk=0.0, actual_delayed=False),
    ]
    assert brier_score(predictions) == pytest.approx(0.0)


def test_brier_score_worst_is_one() -> None:
    predictions = [
        Prediction(predicted_risk=0.0, actual_delayed=True),
        Prediction(predicted_risk=1.0, actual_delayed=False),
    ]
    assert brier_score(predictions) == pytest.approx(1.0)


def test_brier_score_clamps_out_of_range_predictions() -> None:
    # predicted_risk 1.5 clamps to 1.0 -> (1-1)^2 = 0; -0.5 clamps to 0 -> 0.
    predictions = [
        Prediction(predicted_risk=1.5, actual_delayed=True),
        Prediction(predicted_risk=-0.5, actual_delayed=False),
    ]
    assert brier_score(predictions) == pytest.approx(0.0)


def test_brier_score_empty_is_zero() -> None:
    assert brier_score([]) == 0.0


# --------------------------------------------------------------------------- #
# backtest - calibration buckets
# --------------------------------------------------------------------------- #


def test_calibration_buckets_bin_edges_and_rates() -> None:
    # Two predictions in [0.0, 0.1): one delayed, one not -> observed 0.5.
    # One prediction at exactly 1.0 -> lands in the top bucket [0.9, 1.0].
    predictions = [
        Prediction(predicted_risk=0.02, actual_delayed=True),
        Prediction(predicted_risk=0.07, actual_delayed=False),
        Prediction(predicted_risk=1.0, actual_delayed=True),
    ]
    out = calibration_buckets(predictions, buckets=10)
    assert isinstance(out, tuple)
    # Only the two occupied buckets are returned, low to high.
    assert [round(b.lower, 4) for b in out] == [0.0, 0.9]
    low, high = out
    assert low.n == 2
    assert low.lower == pytest.approx(0.0)
    assert low.upper == pytest.approx(0.1)
    assert low.mean_predicted == pytest.approx((0.02 + 0.07) / 2.0)
    assert low.observed_rate == pytest.approx(0.5)
    # Top bucket upper edge is exactly 1.0 and contains the p==1.0 prediction.
    assert high.n == 1
    assert high.upper == pytest.approx(1.0)
    assert high.observed_rate == pytest.approx(1.0)


def test_calibration_buckets_omit_empty_buckets() -> None:
    predictions = [
        Prediction(predicted_risk=0.05, actual_delayed=False),
        Prediction(predicted_risk=0.95, actual_delayed=True),
    ]
    out = calibration_buckets(predictions, buckets=10)
    # Only two of the ten buckets are occupied.
    assert len(out) == 2


def test_calibration_buckets_custom_bucket_count() -> None:
    predictions = [
        Prediction(predicted_risk=0.1, actual_delayed=False),
        Prediction(predicted_risk=0.9, actual_delayed=True),
    ]
    out = calibration_buckets(predictions, buckets=2)
    assert len(out) == 2
    assert out[0].lower == pytest.approx(0.0)
    assert out[0].upper == pytest.approx(0.5)
    assert out[1].lower == pytest.approx(0.5)
    assert out[1].upper == pytest.approx(1.0)


def test_calibration_buckets_clamps_predictions() -> None:
    # A 1.5 prediction clamps to 1.0 and lands in the top bucket, not overflow.
    predictions = [Prediction(predicted_risk=1.5, actual_delayed=True)]
    out = calibration_buckets(predictions, buckets=10)
    assert len(out) == 1
    assert out[0].upper == pytest.approx(1.0)
    assert out[0].mean_predicted == pytest.approx(1.0)


def test_calibration_buckets_empty_input() -> None:
    assert calibration_buckets([], buckets=10) == ()


def test_calibration_buckets_rejects_non_positive_count() -> None:
    with pytest.raises(ValueError):
        calibration_buckets([Prediction(predicted_risk=0.5, actual_delayed=True)], buckets=0)


# --------------------------------------------------------------------------- #
# backtest - top-level
# --------------------------------------------------------------------------- #


def test_backtest_combines_brier_and_calibration() -> None:
    predictions = [
        Prediction(predicted_risk=0.9, actual_delayed=True),
        Prediction(predicted_risk=0.2, actual_delayed=False),
        Prediction(predicted_risk=0.7, actual_delayed=True),
        Prediction(predicted_risk=0.4, actual_delayed=False),
    ]
    result = backtest(predictions)
    assert isinstance(result, BacktestResult)
    assert result.count == 4
    assert result.brier_score == pytest.approx(0.075)
    # Calibration is reported as buckets and matches the standalone helper.
    assert result.calibration == calibration_buckets(predictions, buckets=10)
    assert all(isinstance(b, CalibrationBucket) for b in result.calibration)


def test_backtest_respects_bucket_keyword() -> None:
    predictions = [
        Prediction(predicted_risk=0.1, actual_delayed=False),
        Prediction(predicted_risk=0.9, actual_delayed=True),
    ]
    result = backtest(predictions, buckets=2)
    assert len(result.calibration) == 2


def test_backtest_empty_input() -> None:
    result = backtest([])
    assert result.count == 0
    assert result.brier_score == 0.0
    assert result.calibration == ()


def test_backtest_well_calibrated_stream_has_low_brier() -> None:
    # A stream where high-risk predictions delay and low-risk ones do not should
    # score a low (good) Brier value.
    predictions = [Prediction(predicted_risk=0.95, actual_delayed=True) for _ in range(10)]
    predictions += [Prediction(predicted_risk=0.05, actual_delayed=False) for _ in range(10)]
    result = backtest(predictions)
    assert result.brier_score < 0.01


# --------------------------------------------------------------------------- #
# determinism / types
# --------------------------------------------------------------------------- #


def test_score_is_deterministic() -> None:
    inp = _inp(
        step_mean_dwell_days=18.0,
        step_sla_days=10.0,
        holder_overdue_rate=0.45,
        change_size_ratio=0.07,
        holder_open_change_count=3,
    )
    assert score(inp) == score(inp)


def test_score_returns_delay_risk_result_with_risk_factors() -> None:
    result = score(_inp(step_mean_dwell_days=20.0, step_sla_days=10.0))
    assert isinstance(result, DelayRiskResult)
    assert all(isinstance(f, RiskFactor) for f in result.top_factors)
