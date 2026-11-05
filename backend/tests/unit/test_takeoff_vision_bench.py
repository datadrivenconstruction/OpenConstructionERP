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


def test_dwg_entities_measure_like_the_drawing() -> None:
    """Bulged polylines, rings closed by a repeated vertex, hatch holes, splines."""
    from tests.bench.takeoff_vision.dwg_cases import run

    rows = run()
    assert len(rows) == 6
    worst = max(rows, key=lambda r: r["err_pct"])
    assert worst["err_pct"] < 0.05, worst


def test_text_analyzer_belt_caps_invented_quantities() -> None:
    from tests.bench.takeoff_vision.analyze_cases import evaluate as evaluate_text

    m = evaluate_text(list(range(30)))
    assert m["invented_caught"] >= 0.95
    assert m["true_kept_confident"] >= 0.98
    assert m["second_floor_rows_kept"] == 1.0
    assert m["scores_raised"] == 0
    assert m["extra_unit_spellings"] == 0


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("1,234.56 m2", 1234.56),
        ("1.234,56 m2", 1234.56),
        ("1 234,56 m2", 1234.56),
        ("12,5 m", 12.5),
        ("1,250 t", 1250.0),
    ],
)
def test_text_analyzer_reads_number_styles(text: str, value: float) -> None:
    from app.modules.takeoff.text_analyze import source_numbers

    assert any(abs(v - value) < 1e-9 for v, *_span in source_numbers(text))


def test_text_analyzer_needs_the_numbers_line_to_describe_the_item() -> None:
    from app.modules.takeoff.text_analyze import check_items

    text = "01 Floor screed 50 mm 140.00 m2\n02 Brick wall\n86.50 m2\n"
    rows = check_items(
        [
            {"description": "Excavation invented", "quantity": 140.0, "unit": "m2", "confidence": 0.9},
            {"description": "Brick wall", "quantity": 86.5, "unit": "m2", "confidence": 0.8},
        ],
        text,
    )
    assert [r.grounded for r in rows] == [False, True]
    assert rows[0].confidence < 0.62


def test_text_analyzer_ignores_a_number_from_a_date() -> None:
    from app.modules.takeoff.text_analyze import check_items

    text = "Issued 12.05.2026, drawing 17\n01 Floor screed 50 mm 140.00 m2"
    rows = check_items(
        [
            {"description": "Floor screed 50 mm", "quantity": 140.0, "unit": "sqm", "confidence": 0.7},
            {"description": "Brick wall", "quantity": 12.05, "unit": "m2", "confidence": 0.9},
            {"description": "Doors", "quantity": 17, "unit": "pcs", "confidence": 0.9},
        ],
        text,
    )
    assert [r.grounded for r in rows] == [True, False, False]
    assert rows[0].confidence == 0.7  # found in the text, still not above the model
    assert all(r.confidence < 0.62 for r in rows[1:])
