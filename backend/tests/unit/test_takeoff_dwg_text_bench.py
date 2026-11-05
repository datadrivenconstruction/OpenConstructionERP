"""Measured accuracy of the DWG takeoff and the document text analyzer.

Fast slices of ``tests/bench/takeoff_vision``; thresholds sit under the measured
values so a regression fails here.
"""

from __future__ import annotations

import pytest

from app.modules.takeoff.text_analyze import check_items, source_numbers

BOQ = """Bill of quantities rev 3, issued 12.05.2026, drawing 17
01 Floor screed 50 mm 140.00 m2
02 Internal doors type D1 12 pcs
03 Brick wall 240 mm 86,5 m2
04 Paint to walls  x 86.5
Total floor area 1.250,50 m2
"""


def _item(description: str, quantity: float, unit: str, confidence: float = 0.9) -> dict[str, object]:
    return {"description": description, "quantity": quantity, "unit": unit, "confidence": confidence}


def _one(item: dict[str, object], text: str = BOQ):
    return check_items([item], text)[0]


def test_dwg_entities_measure_like_the_drawing() -> None:
    """Bulged polylines, rings closed by a repeated vertex, hatch loops and holes, splines."""
    from tests.bench.takeoff_vision.dwg_cases import run

    rows = run()
    assert len(rows) == 6
    worst = max(rows, key=lambda r: r["err_pct"])
    assert worst["err_pct"] < 0.05, worst


def test_text_analyzer_belt_caps_invented_quantities() -> None:
    from tests.bench.takeoff_vision.analyze_cases import evaluate

    m = evaluate(list(range(30)))
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
    assert any(abs(v - value) < 1e-9 for v, *_span in source_numbers(text))


def test_a_number_on_an_unrelated_line_backs_nothing() -> None:
    row = _one(_item("Excavation invented", 140.0, "m2"))
    assert not row.grounded
    assert row.confidence < 0.62
    assert "quantity_not_in_source" in row.flags


def test_a_number_from_a_date_or_drawing_backs_nothing() -> None:
    assert not _one(_item("Brick wall", 12.05, "m2")).grounded
    assert not _one(_item("Doors", 17, "pcs")).grounded


def test_a_number_with_another_unit_backs_nothing() -> None:
    assert not _one(_item("Floor screed 50 mm", 140.0, "m3")).grounded


def test_a_number_on_the_items_line_is_grounded_at_the_models_score() -> None:
    row = _one(_item("Floor screed 50 mm", 140.0, "sqm", 0.7))
    assert row.grounded
    assert row.confidence == 0.7
    assert _one(_item("Paint to walls", 86.5, "m2", 0.8)).grounded  # no unit printed
    assert _one(_item("Internal door D1", 12, "pcs", 0.8)).grounded  # singular of "doors"


def test_a_table_row_split_into_one_line_per_cell_is_grounded() -> None:
    assert _one(_item("Floor screed", 140.0, "m2"), "Floor screed 50 mm\n140.00 m2\nBrick wall\n86.50 m2").grounded
    assert not _one(_item("Excavation", 86.5, "m2"), "Floor screed 50 mm\n140.00 m2\nBrick wall\n86.50 m2").grounded


def test_the_same_line_twice_is_kept_and_flagged() -> None:
    door = _item("Internal doors type D1", 12, "pcs", 0.8)
    rows = check_items([door, dict(door)], BOQ)
    assert [r.quantity for r in rows] == [12, 12]
    assert rows[1].flags.count("repeated_line") == 1
