# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure AI accuracy scoreboard engine."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.modules.ai_agents.accuracy import (
    AccuracyScore,
    CalibrationBin,
    Prediction,
    brier_score,
    calibration_bins,
    clamp01,
    expected_calibration_error,
    score_agent,
    score_by_agent,
)


def make(confidence: float, outcome: bool, agent: str = "agent-a") -> Prediction:
    """Build a Prediction with a fixed agent name for brevity in tests."""
    return Prediction(agent_name=agent, confidence=confidence, outcome=outcome)


class TestClamp01:
    def test_within_range_is_unchanged(self) -> None:
        assert clamp01(0.0) == 0.0
        assert clamp01(0.5) == 0.5
        assert clamp01(1.0) == 1.0

    def test_below_zero_clamps_to_zero(self) -> None:
        assert clamp01(-0.1) == 0.0
        assert clamp01(-5.0) == 0.0

    def test_above_one_clamps_to_one(self) -> None:
        assert clamp01(1.1) == 1.0
        assert clamp01(42.0) == 1.0

    def test_returns_float(self) -> None:
        result = clamp01(1)
        assert isinstance(result, float)
        assert result == 1.0


class TestBrierScore:
    def test_empty_is_zero(self) -> None:
        assert brier_score([]) == 0.0

    def test_all_correct_and_confident_near_zero(self) -> None:
        predictions = [make(1.0, True) for _ in range(5)]
        assert brier_score(predictions) == pytest.approx(0.0)

    def test_all_wrong_but_confident_near_one(self) -> None:
        # Confidently asserts correctness (1.0) but every outcome was wrong.
        predictions = [make(1.0, False) for _ in range(5)]
        assert brier_score(predictions) == pytest.approx(1.0)

    def test_half_confidence_is_quarter(self) -> None:
        # (0.5 - target) ** 2 == 0.25 regardless of the outcome.
        assert brier_score([make(0.5, True)]) == pytest.approx(0.25)
        assert brier_score([make(0.5, False)]) == pytest.approx(0.25)

    def test_mean_over_mixed_predictions(self) -> None:
        # Correct at 0.8 -> 0.04; wrong at 0.2 -> 0.04; mean 0.04.
        predictions = [make(0.8, True), make(0.2, False)]
        assert brier_score(predictions) == pytest.approx(0.04)

    def test_out_of_range_confidence_is_clamped(self) -> None:
        # 1.5 clamps to 1.0 against a True outcome -> 0.0 contribution.
        assert brier_score([make(1.5, True)]) == pytest.approx(0.0)
        # -0.5 clamps to 0.0 against a False outcome -> 0.0 contribution.
        assert brier_score([make(-0.5, False)]) == pytest.approx(0.0)
        # -0.5 clamps to 0.0 against a True outcome -> 1.0 contribution.
        assert brier_score([make(-0.5, True)]) == pytest.approx(1.0)


class TestCalibrationBins:
    def test_empty_returns_empty(self) -> None:
        assert calibration_bins([]) == []

    def test_invalid_bin_count_raises(self) -> None:
        with pytest.raises(ValueError, match="n_bins"):
            calibration_bins([make(0.5, True)], n_bins=0)

    def test_only_non_empty_bins_returned(self) -> None:
        # All confidences land in the same bucket -> exactly one bin.
        predictions = [make(0.05, True), make(0.05, False)]
        bins = calibration_bins(predictions, n_bins=10)
        assert len(bins) == 1
        assert bins[0].count == 2

    def test_bin_counts_and_rates(self) -> None:
        # Two in [0.0, 0.1) both wrong; two in [0.9, 1.0] both right.
        predictions = [
            make(0.05, False),
            make(0.05, False),
            make(0.95, True),
            make(0.95, True),
        ]
        bins = calibration_bins(predictions, n_bins=10)
        assert len(bins) == 2
        low, high = bins
        assert low.count == 2
        assert low.observed_rate == pytest.approx(0.0)
        assert low.mean_confidence == pytest.approx(0.05)
        assert high.count == 2
        assert high.observed_rate == pytest.approx(1.0)
        assert high.mean_confidence == pytest.approx(0.95)

    def test_bins_are_ordered_low_to_high(self) -> None:
        predictions = [make(0.95, True), make(0.05, False), make(0.55, True)]
        bins = calibration_bins(predictions, n_bins=10)
        lowers = [b.lower for b in bins]
        assert lowers == sorted(lowers)

    def test_confidence_exactly_one_lands_in_top_bin(self) -> None:
        bins = calibration_bins([make(1.0, True)], n_bins=10)
        assert len(bins) == 1
        only = bins[0]
        assert only.lower == pytest.approx(0.9)
        assert only.upper == pytest.approx(1.0)
        assert only.count == 1

    def test_confidence_exactly_zero_lands_in_bottom_bin(self) -> None:
        bins = calibration_bins([make(0.0, False)], n_bins=10)
        assert len(bins) == 1
        only = bins[0]
        assert only.lower == pytest.approx(0.0)
        assert only.upper == pytest.approx(0.1)
        assert only.count == 1

    def test_out_of_range_confidence_clamped_into_edge_bins(self) -> None:
        # 1.5 -> 1.0 top bin; -0.5 -> 0.0 bottom bin.
        bins = calibration_bins([make(1.5, True), make(-0.5, False)], n_bins=10)
        assert len(bins) == 2
        assert bins[0].lower == pytest.approx(0.0)
        assert bins[1].upper == pytest.approx(1.0)

    def test_single_bin_spans_full_range(self) -> None:
        bins = calibration_bins([make(0.3, True), make(0.7, False)], n_bins=1)
        assert len(bins) == 1
        only = bins[0]
        assert only.lower == pytest.approx(0.0)
        assert only.upper == pytest.approx(1.0)
        assert only.count == 2
        assert only.observed_rate == pytest.approx(0.5)


class TestExpectedCalibrationError:
    def test_empty_is_zero(self) -> None:
        assert expected_calibration_error([]) == 0.0

    def test_perfectly_calibrated_is_zero(self) -> None:
        # In the [0.0, 0.1) bin (mean conf 0.0) every outcome is wrong, and
        # in the [0.9, 1.0] bin (mean conf 1.0) every outcome is right: the
        # observed rate matches the confidence in each bin, so ECE is 0.
        predictions = [
            make(0.0, False),
            make(0.0, False),
            make(1.0, True),
            make(1.0, True),
        ]
        assert expected_calibration_error(predictions, n_bins=10) == pytest.approx(0.0)

    def test_perfectly_calibrated_half_bin(self) -> None:
        # All in one bin with mean confidence 0.5 and a 50 percent hit rate.
        predictions = [make(0.5, True), make(0.5, False)]
        assert expected_calibration_error(predictions, n_bins=1) == pytest.approx(0.0)

    def test_maximally_miscalibrated_is_one(self) -> None:
        # Confidence 1.0 but never correct: gap of 1.0 in a single bin.
        predictions = [make(1.0, False) for _ in range(4)]
        assert expected_calibration_error(predictions, n_bins=10) == pytest.approx(1.0)

    def test_weighted_average_across_bins(self) -> None:
        # Bin A: three predictions at 0.0, all wrong -> gap 0.0, weight 3/4.
        # Bin B: one prediction at 1.0, wrong -> gap 1.0, weight 1/4.
        # ECE = 0.75 * 0.0 + 0.25 * 1.0 = 0.25.
        predictions = [
            make(0.0, False),
            make(0.0, False),
            make(0.0, False),
            make(1.0, False),
        ]
        assert expected_calibration_error(predictions, n_bins=10) == pytest.approx(0.25)


class TestScoreAgent:
    def test_empty_input_zeroed(self) -> None:
        score = score_agent("agent-a", [])
        assert isinstance(score, AccuracyScore)
        assert score.agent_name == "agent-a"
        assert score.count == 0
        assert score.brier_score == 0.0
        assert score.mean_confidence == 0.0
        assert score.observed_rate == 0.0
        assert score.calibration_error == 0.0
        assert score.bins == []

    def test_confident_and_correct_is_strong(self) -> None:
        predictions = [make(1.0, True) for _ in range(10)]
        score = score_agent("agent-a", predictions)
        assert score.count == 10
        assert score.brier_score == pytest.approx(0.0)
        assert score.mean_confidence == pytest.approx(1.0)
        assert score.observed_rate == pytest.approx(1.0)
        assert score.calibration_error == pytest.approx(0.0)
        assert len(score.bins) == 1

    def test_observed_rate_counts_true_fraction(self) -> None:
        predictions = [
            make(0.6, True),
            make(0.6, True),
            make(0.6, True),
            make(0.6, False),
        ]
        score = score_agent("agent-a", predictions)
        assert score.observed_rate == pytest.approx(0.75)
        assert score.mean_confidence == pytest.approx(0.6)

    def test_mean_confidence_uses_clamped_values(self) -> None:
        # Raw values 1.5 and -0.5 clamp to 1.0 and 0.0 -> mean 0.5.
        predictions = [make(1.5, True), make(-0.5, False)]
        score = score_agent("agent-a", predictions)
        assert score.mean_confidence == pytest.approx(0.5)

    def test_bin_count_total_matches_prediction_count(self) -> None:
        predictions = [
            make(0.05, True),
            make(0.35, False),
            make(0.65, True),
            make(0.95, True),
        ]
        score = score_agent("agent-a", predictions)
        assert sum(b.count for b in score.bins) == score.count


class TestScoreByAgent:
    def test_empty_input_is_empty_mapping(self) -> None:
        assert score_by_agent([]) == {}

    def test_groups_two_agents(self) -> None:
        predictions = [
            make(1.0, True, agent="agent-a"),
            make(1.0, True, agent="agent-a"),
            make(0.0, True, agent="agent-b"),
            make(0.0, True, agent="agent-b"),
        ]
        scores = score_by_agent(predictions)
        assert set(scores) == {"agent-a", "agent-b"}

        good = scores["agent-a"]
        assert good.count == 2
        assert good.agent_name == "agent-a"
        assert good.brier_score == pytest.approx(0.0)
        assert good.observed_rate == pytest.approx(1.0)

        # agent-b was correct yet declared zero confidence: a high Brier score
        # and a large calibration gap.
        bad = scores["agent-b"]
        assert bad.count == 2
        assert bad.brier_score == pytest.approx(1.0)
        assert bad.observed_rate == pytest.approx(1.0)
        assert bad.calibration_error == pytest.approx(1.0)

    def test_each_value_is_scored_for_its_own_agent(self) -> None:
        predictions = [
            make(0.5, True, agent="x"),
            make(0.5, False, agent="y"),
        ]
        scores = score_by_agent(predictions)
        assert scores["x"].agent_name == "x"
        assert scores["y"].agent_name == "y"
        assert scores["x"].count == 1
        assert scores["y"].count == 1

    def test_grouping_is_deterministic_by_first_appearance(self) -> None:
        predictions = [
            make(0.5, True, agent="zeta"),
            make(0.5, True, agent="alpha"),
            make(0.5, True, agent="zeta"),
        ]
        scores = score_by_agent(predictions)
        assert list(scores.keys()) == ["zeta", "alpha"]

    def test_partitioning_preserves_all_predictions(self) -> None:
        predictions = [
            make(0.2, True, agent="a"),
            make(0.4, False, agent="b"),
            make(0.6, True, agent="a"),
            make(0.8, False, agent="c"),
            make(0.9, True, agent="b"),
        ]
        scores = score_by_agent(predictions)
        assert sum(s.count for s in scores.values()) == len(predictions)


class TestDataclassContracts:
    def test_prediction_default_timestamp_is_none(self) -> None:
        prediction = Prediction(agent_name="a", confidence=0.5, outcome=True)
        assert prediction.predicted_at is None

    def test_prediction_is_frozen(self) -> None:
        prediction = make(0.5, True)
        with pytest.raises(FrozenInstanceError):
            prediction.confidence = 0.6  # type: ignore[misc]

    def test_calibration_bin_is_frozen(self) -> None:
        bucket = CalibrationBin(
            lower=0.0,
            upper=0.1,
            count=1,
            mean_confidence=0.05,
            observed_rate=1.0,
        )
        with pytest.raises(FrozenInstanceError):
            bucket.count = 2  # type: ignore[misc]

    def test_accuracy_score_is_frozen(self) -> None:
        score = score_agent("agent-a", [make(0.5, True)])
        with pytest.raises(FrozenInstanceError):
            score.count = 99  # type: ignore[misc]
