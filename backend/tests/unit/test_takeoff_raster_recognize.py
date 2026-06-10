# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Unit tests for the offline raster recognition detectors (issue #194).

These exercise :mod:`app.modules.takeoff.raster_recognize` with a small
synthetic image of black-outlined white rectangles on a white page, so no real
scanned PDF is needed. cv2/numpy are an optional ``cv`` extra, so the module is
imported behind ``importorskip`` and the test is skipped cleanly when they are
absent. They lock in the contract the canvas relies on: rooms become area
candidates in PDF POINT space, the pixel -> point mapping is a plain per-axis
scale, and nothing fabricates a value without a calibration scale.
"""

from __future__ import annotations

import math

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from app.modules.takeoff import raster_recognize  # noqa: E402

# Synthetic page: 600x400 px image, 300x200 pt PDF page -> exactly 2 px / pt on
# both axes, which makes the expected point coordinates easy to assert. The
# three rooms are each ~5% of the page so all sit inside the keep band.
_IMG_W, _IMG_H = 600, 400
_PAGE_W, _PAGE_H = 300.0, 200.0
_PX_PER_PT = 2.0

# (x0, y0, x1, y1) outer rectangles, drawn with a 3 px black wall.
_ROOM_BOXES = [(60, 60, 200, 180), (260, 60, 400, 180), (60, 240, 200, 360)]


def _synthetic_rooms() -> np.ndarray:
    """White page with three clear black-outlined white rectangles (rooms)."""
    img = np.full((_IMG_H, _IMG_W, 3), 255, dtype=np.uint8)
    for x0, y0, x1, y1 in _ROOM_BOXES:
        cv2.rectangle(img, (x0, y0), (x1, y1), (0, 0, 0), 3)
    return img


def test_pixel_to_point_mapping_is_per_axis_scale() -> None:
    to_pt = raster_recognize._make_px_to_pt(_IMG_W, _IMG_H, _PAGE_W, _PAGE_H)
    assert to_pt(0, 0) == (0.0, 0.0)
    # A pixel at the image's far corner maps to the page's far corner.
    assert to_pt(_IMG_W, _IMG_H) == (_PAGE_W, _PAGE_H)
    # Halfway across in pixels is halfway across in points.
    assert to_pt(_IMG_W / 2, _IMG_H / 2) == (_PAGE_W / 2, _PAGE_H / 2)


def test_rooms_become_area_candidates_in_point_space() -> None:
    cands = raster_recognize.recognize_raster(_synthetic_rooms(), _PAGE_W, _PAGE_H, 0.0)
    areas = [c for c in cands if c["type"] == "area"]
    # Three drawn rooms, and the page outline must NOT be returned as a room.
    assert len(areas) == 3
    for cand in areas:
        assert cand["dimension"] == "area"
        assert cand["value"] is None  # no scale was given
        assert len(cand["points"]) >= 3
        # Every point sits inside the page rectangle, in point (not pixel) space.
        for p in cand["points"]:
            assert 0.0 <= p["x"] <= _PAGE_W
            assert 0.0 <= p["y"] <= _PAGE_H


def test_room_value_uses_calibration_scale() -> None:
    # scale_pixels_per_unit is POINTS per unit. With 2 px/pt, each ~140x120 px
    # box has a ~130x110 px interior -> ~65x55 pt. At 10 pt/unit that is roughly
    # 6.5 x 5.5 ~= 36 unit^2 per room (a little less after wall erosion).
    cands = raster_recognize.recognize_raster(_synthetic_rooms(), _PAGE_W, _PAGE_H, 10.0)
    areas = [c for c in cands if c["type"] == "area"]
    assert areas
    assert all(c["value"] is not None and c["value"] > 0 for c in areas)
    # All three rooms are the same size, so every value lands in a tight band.
    assert all(25.0 <= c["value"] <= 50.0 for c in areas)


def test_area_value_matches_polygon_geometry() -> None:
    cands = raster_recognize.recognize_raster(_synthetic_rooms(), _PAGE_W, _PAGE_H, 4.0)
    cand = next(c for c in cands if c["type"] == "area")
    pts = [(p["x"], p["y"]) for p in cand["points"]]
    # Recompute area independently: shoelace in points, divided by scale^2.
    n = len(pts)
    s = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    expected = abs(s) / 2.0 / (4.0 * 4.0)
    assert math.isclose(cand["value"], expected, rel_tol=1e-6)


def test_blank_page_returns_nothing() -> None:
    blank = np.full((_IMG_H, _IMG_W, 3), 255, dtype=np.uint8)
    assert raster_recognize.recognize_raster(blank, _PAGE_W, _PAGE_H, 0.0) == []


def test_degenerate_inputs_do_not_raise() -> None:
    img = _synthetic_rooms()
    # Zero / negative page size and an empty image must return [] not raise.
    assert raster_recognize.recognize_raster(img, 0.0, _PAGE_H, 0.0) == []
    assert raster_recognize.recognize_raster(img, _PAGE_W, 0.0, 0.0) == []
    assert raster_recognize.recognize_raster(np.zeros((0, 0, 3), np.uint8), _PAGE_W, _PAGE_H, 0.0) == []


def test_candidates_are_sorted_by_confidence() -> None:
    cands = raster_recognize.recognize_raster(_synthetic_rooms(), _PAGE_W, _PAGE_H, 10.0)
    confidences = [c["confidence"] for c in cands]
    assert confidences == sorted(confidences, reverse=True)
    # Raster confidences stay below the vector path's clean-geometry scores.
    assert all(c <= 0.60 for c in confidences)


def test_candidate_shape_matches_vector_contract() -> None:
    cands = raster_recognize.recognize_raster(_synthetic_rooms(), _PAGE_W, _PAGE_H, 0.0)
    assert cands
    required = {"type", "points", "value", "dimension", "count", "confidence", "reason"}
    for cand in cands:
        assert required <= set(cand)
        assert cand["type"] in {"area", "distance", "count"}
        assert isinstance(cand["reason"], str) and cand["reason"]
