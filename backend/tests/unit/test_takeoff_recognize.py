# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Unit tests for the offline vector recognition detectors (issue #194).

These exercise :mod:`app.modules.takeoff.recognize` directly with synthetic
``get_drawings()``-shaped input (plain tuples), so no PDF, PyMuPDF or database
is needed. They lock in the contract the canvas relies on: rectangles become
area candidates, long strokes become length candidates, repeated small shapes
become a single count candidate, and nothing fabricates a value without a
calibration scale.
"""

from __future__ import annotations

from app.modules.takeoff import recognize


def _rect_path(x0: float, y0: float, x1: float, y1: float) -> dict:
    """A get_drawings()-shaped path holding a single rectangle item."""
    return {"items": [("re", (x0, y0, x1, y1))]}


def _line_path(x0: float, y0: float, x1: float, y1: float) -> dict:
    return {"items": [("l", (x0, y0), (x1, y1))]}


def test_rectangle_becomes_area_candidate() -> None:
    # 100x100 px rectangle, scale of 50 px per unit -> 2x2 = 4 unit^2.
    candidates = recognize.recognize_candidates([_rect_path(0, 0, 100, 100)], 50.0)
    areas = [c for c in candidates if c["type"] == "area"]
    assert len(areas) == 1
    cand = areas[0]
    assert cand["confidence"] >= 0.8  # clean rectangle -> high confidence
    assert cand["value"] == 4.0
    assert len(cand["points"]) == 4


def test_area_value_is_none_without_scale() -> None:
    candidates = recognize.recognize_candidates([_rect_path(0, 0, 100, 100)], 0.0)
    areas = [c for c in candidates if c["type"] == "area"]
    assert areas and areas[0]["value"] is None  # honest: no value until calibrated


def test_long_strokes_become_distance_candidates() -> None:
    drawings = [
        _line_path(0, 0, 50, 0),
        _line_path(0, 10, 60, 10),
        _line_path(0, 20, 70, 20),
        _line_path(0, 30, 200, 30),
        _line_path(0, 40, 220, 40),
    ]
    candidates = recognize.recognize_candidates(drawings, 10.0)
    dists = [c for c in candidates if c["type"] == "distance"]
    # Only the two clearly-longest strokes clear the 70th-percentile cut.
    assert len(dists) == 2
    assert all(c["value"] is not None and c["value"] >= 20.0 for c in dists)


def test_repeated_small_shapes_become_one_count() -> None:
    # Four identical 20x20 symbols scattered across the page.
    drawings = [
        _rect_path(0, 0, 20, 20),
        _rect_path(100, 0, 120, 20),
        _rect_path(0, 100, 20, 120),
        _rect_path(100, 100, 120, 120),
    ]
    candidates = recognize.recognize_candidates(drawings, 10.0)
    counts = [c for c in candidates if c["type"] == "count"]
    assert len(counts) == 1
    assert counts[0]["count"] == 4
    assert counts[0]["value"] == 4.0
    # Small symbols must NOT also be returned as area candidates.
    assert not [c for c in candidates if c["type"] == "area"]


def test_closed_polyline_loop_is_an_area() -> None:
    # A square drawn as four connected line segments (not a 're' item).
    loop = {
        "items": [
            ("l", (0, 0), (120, 0)),
            ("l", (120, 0), (120, 120)),
            ("l", (120, 120), (0, 120)),
            ("l", (0, 120), (0, 0)),
        ]
    }
    candidates = recognize.recognize_candidates([loop], 60.0)
    areas = [c for c in candidates if c["type"] == "area"]
    assert len(areas) == 1
    assert areas[0]["value"] == 4.0  # 2x2 units
    assert areas[0]["confidence"] >= 0.8  # axis-aligned rectangle


def test_empty_drawings_returns_nothing() -> None:
    assert recognize.recognize_candidates([], 50.0) == []


def test_candidates_are_sorted_by_confidence() -> None:
    drawings = [_rect_path(0, 0, 100, 100), _line_path(0, 200, 300, 200)]
    candidates = recognize.recognize_candidates(drawings, 10.0)
    confidences = [c["confidence"] for c in candidates]
    assert confidences == sorted(confidences, reverse=True)
