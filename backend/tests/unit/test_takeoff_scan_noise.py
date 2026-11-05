"""A scan with nothing on it, or with too much, is read as what it is."""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from app.modules.takeoff import raster_recognize as rr  # noqa: E402


def _noise(h: int = 1200, w: int = 1700) -> object:
    rng = np.random.default_rng(5)
    return (rng.random((h, w)) * 255).astype(np.uint8)


def test_random_noise_yields_nothing() -> None:
    assert rr.recognize_raster(np.dstack([_noise()] * 3), 1190.0, 842.0, 0.0) == []


def test_a_page_too_inky_for_a_drawing_counts_as_busy() -> None:
    _segs, _fills, n_parts = rr.scan_parts(np.zeros((400, 600), np.uint8) + _noise(400, 600) // 4, 800.0, 600.0)
    assert n_parts > rr._SKETCH_MAX_PARTS


def test_pen_weights_split_when_two_pens_drew_the_sheet() -> None:
    weights = [0.5] * 40 + [1.6] * 20
    lengths = [100.0] * 60
    assert 0.5 < rr._heavy_split(weights, lengths) < 1.6


def test_one_pen_has_no_split() -> None:
    assert rr._heavy_split([1.0, 1.05, 1.1, 0.95] * 10, [100.0] * 40) == 0.0


def test_lettering_does_not_decide_the_pens() -> None:
    # Many short strokes of a third weight weigh nothing against the long ones.
    weights = [0.5] * 20 + [1.6] * 20 + [0.15] * 400
    lengths = [300.0] * 40 + [2.0] * 400
    assert rr._heavy_split(weights, lengths) > 0.5


def test_ink_across_a_line_survives_the_shrink() -> None:
    gray = np.full((400, 400), 240, np.uint8)
    gray[200:201, 20:380] = 0  # one pixel of full ink
    gray[100:104, 20:380] = 0  # four pixels of it
    ink = rr._ink_map(gray, (200, 200))

    class Band:
        axis = "h"
        lo, hi = 20, 180

        def __init__(self, c: int) -> None:
            self.c = c

    thin, thick = rr._stroke_weight(ink, Band(100)), rr._stroke_weight(ink, Band(51))
    assert thick == pytest.approx(4 * thin, rel=0.25)
