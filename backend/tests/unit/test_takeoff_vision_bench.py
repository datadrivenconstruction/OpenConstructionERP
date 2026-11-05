"""Fast slice of the plan-read accuracy benchmark (``tests/bench/takeoff_vision``).

Six generated plans (vector and scanned sheets, train and holdout seeds), each
read by a realistic and an adversarial mock model, go through the same
``check_plan_read`` call the service makes. The thresholds sit a little under
the measured values so a regression in the belt fails here, not in review.
Full runs: ``python -m tests.bench.takeoff_vision.run_bench --split holdout``.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.bench.takeoff_vision.plans import FAST_SEEDS
from tests.bench.takeoff_vision.run_bench import evaluate


@pytest.fixture(scope="module")
def results() -> dict[str, Any]:
    return {"current": evaluate(FAST_SEEDS, "current"), "baseline": evaluate(FAST_SEEDS, "baseline")}


def test_vector_sheets_measure_rooms_exactly(results: dict[str, Any]) -> None:
    m = results["current"]["realistic_vector_pdf"]
    assert m["area_err_median_pct"] <= 0.5
    # A ring the drawing leaves open stays as the model drew it, flagged, when its snap moves the area over 4%.
    assert m["area_within_2pct"] >= 0.8
    assert m["scale_within_1pct"] == 1.0
    assert m["room_precision"] >= 0.82


def test_confidence_is_calibrated(results: dict[str, Any]) -> None:
    m = results["current"]["realistic_vector_pdf"]
    assert m["confident_precision"] >= 0.95
    assert m["confident_share"] >= 0.7
    # Almost all of this is under-confidence: a room without a label stays at or below the model's score.
    assert m["ece"] <= 0.16


def test_belt_keeps_adversarial_items_out_of_the_confident_set(results: dict[str, Any]) -> None:
    m = results["current"]["adversarial"]
    assert m["belt_catch_rate"] >= 0.95, m["belt_missed"]
    assert m["confident_precision"] >= 0.9


def test_belt_beats_the_unrefined_answer(results: dict[str, Any]) -> None:
    cur, base = results["current"]["realistic"], results["baseline"]["realistic"]
    assert cur["area_within_2pct"] > base["area_within_2pct"] + 0.4
    assert cur["ece"] < base["ece"]
    assert cur["room_recall"] >= base["room_recall"] - 0.05
