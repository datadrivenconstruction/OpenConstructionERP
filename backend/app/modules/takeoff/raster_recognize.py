# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Offline raster candidate detection for PDF takeoff (issue #194).

This is the raster twin of :mod:`app.modules.takeoff.recognize`. The vector
recognizer reads a page's drawing layer (``page.get_drawings()``); on a SCANNED
plan that layer is empty, so it correctly returns nothing. This module instead
looks at the rendered raster image of the page with OpenCV and proposes the same
candidate shape:

* large light regions sealed by dark walls -> ``area`` candidates (rooms),
* long straight wall edges -> ``distance`` (length) candidates,
* (count detection is intentionally omitted on scans, see below).

The detection runs in IMAGE PIXEL space but every candidate is returned in PDF
POINT space, the same coordinate space the canvas stores measurements in, so the
shapes drop straight onto the viewer with no further transform. The mapping is a
simple per-axis scale from the rendered pixmap size to the page size in points.

Raster detection is inherently less certain than reading clean vector geometry,
so confidences here are deliberately lower than the vector path (rooms ~0.45 to
0.60, walls ~0.40 to 0.50). Every candidate carries an honest ``reason`` ending
in "(verify)" so the user confirms, edits or rejects it (CLAUDE.md rule 7:
AI-augmented, human-confirmed).

Count detection is skipped on purpose: repeated symbols (doors, fixtures) on a
low-contrast scan cluster unreliably and tend to produce noise, and the brief
for this module is to return a handful of good rooms rather than many shaky
boxes. The vector recognizer still handles counts when a drawing layer exists.

The module is pure (no DB, no FastAPI). ``cv2`` and ``numpy`` are imported at
module top on purpose: the *caller* imports this module lazily and catches
``ImportError``, so a default install without the ``cv`` extra never reaches
here. Every risky OpenCV call is wrapped so a degenerate image yields ``[]``
rather than raising.
"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

# ── tuning constants (settled empirically on the real scanned test plan) ─────
#
# All pixel thresholds are expressed relative to the rendered image so the
# module behaves the same whether the caller rendered at 100 or 200 DPI.

# Square structuring element (in px) used to CLOSE small gaps in the wall mask
# so broken/antialiased wall loops seal into continuous boundaries. Big enough
# to bridge scan gaps, small enough not to merge adjacent rooms together.
_WALL_CLOSE_KERNEL_PX = 9
# How many times the close is applied. Two passes seal the test plan's walls
# without over-growing them into neighbouring rooms.
_WALL_CLOSE_ITER = 2

# A room region must cover at least this fraction of the page to be kept. Below
# this it is almost always a text gap, a label box or scan speckle.
_ROOM_MIN_PAGE_FRAC = 0.004
# ... and at most this fraction. Above this it is the whole-floor envelope or a
# merge of several rooms, not a single measurable room.
_ROOM_MAX_PAGE_FRAC = 0.15
# Douglas-Peucker simplification, as a fraction of the contour perimeter. Keeps
# room polygons to a handful of corners instead of a ragged pixel boundary.
_ROOM_APPROX_EPS_FRAC = 0.02
# A simplified room polygon with <= this many corners and a high bbox fill
# ("extent") is treated as a clean rectangle and scored a little higher.
_ROOM_RECT_MAX_VERTS = 6
_ROOM_RECT_MIN_EXTENT = 0.80

# Canny hysteresis thresholds for the wall-edge image fed to Hough.
_CANNY_LO = 50
_CANNY_HI = 150
# A wall segment must be at least this fraction of the page diagonal to count.
# Filters hatching, dimension ticks and short label underlines.
_WALL_MIN_LEN_FRAC = 0.10
# Hough accumulator vote threshold and the largest gap (px) bridged within one
# line. minLineLength is derived from _WALL_MIN_LEN_FRAC at call time.
_HOUGH_VOTES = 80
_HOUGH_MAX_GAP_PX = 10
# Two wall segments are treated as the same line (deduplicated) when their
# endpoints fall in the same coarse grid cell of this size in px.
_WALL_DEDUP_CELL_PX = 14
# Never surface more than this many wall lines (keeps the panel readable).
_MAX_WALLS = 8

# Never return more than this many candidates total (matches recognize.py).
_MAX_CANDIDATES = 40

Point = tuple[float, float]


# ── geometry helpers (pixel space) ───────────────────────────────────────────


def _shoelace_area(pts: list[Point]) -> float:
    """Polygon area (pixel-squared), boundary auto-closed."""
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _seg_length(p1: Point, p2: Point) -> float:
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


# ── pixel -> point mapping ───────────────────────────────────────────────────


def _make_px_to_pt(
    image_width_px: int,
    image_height_px: int,
    page_width_pt: float,
    page_height_pt: float,
):
    """Return a function mapping an (x, y) image pixel to a PDF point.

    The rendered pixmap and the PDF page describe the same rectangle at two
    resolutions, so the map is a plain per-axis scale: a pixel at fraction f of
    the image width sits at fraction f of the page width.
    """
    sx = (page_width_pt / image_width_px) if image_width_px else 0.0
    sy = (page_height_pt / image_height_px) if image_height_px else 0.0

    def to_pt(x_px: float, y_px: float) -> Point:
        return (x_px * sx, y_px * sy)

    return to_pt


# ── value computation (PDF point geometry / calibration scale) ───────────────


def _area_value(area_pt2: float, scale: float) -> float | None:
    """Area in unit^2 from area in point^2; None without a calibration scale."""
    if scale and scale > 0:
        return area_pt2 / (scale * scale)
    return None


def _length_value(length_pt: float, scale: float) -> float | None:
    """Length in unit from length in points; None without a calibration scale."""
    if scale and scale > 0:
        return length_pt / scale
    return None


# ── image preparation ────────────────────────────────────────────────────────


def _to_gray(image_bgr: Any) -> Any | None:
    """Grayscale view of an HxWx3 BGR array, or None if the input is unusable."""
    try:
        arr = np.asarray(image_bgr)
        if arr.ndim == 3 and arr.shape[2] >= 3:
            return cv2.cvtColor(arr[:, :, :3], cv2.COLOR_BGR2GRAY)
        if arr.ndim == 2:
            return arr.astype(np.uint8, copy=False)
    except (cv2.error, ValueError, TypeError):
        return None
    return None


def _wall_mask(gray: Any) -> Any | None:
    """Binary mask where dark walls are foreground, with small gaps closed.

    Otsu picks the ink/paper split automatically, which is robust across scan
    exposures; ``THRESH_BINARY_INV`` makes the dark walls white (foreground).
    A morphological CLOSE then seals broken wall loops so rooms become fully
    enclosed regions.
    """
    try:
        _, wall = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (_WALL_CLOSE_KERNEL_PX, _WALL_CLOSE_KERNEL_PX))
        return cv2.morphologyEx(wall, cv2.MORPH_CLOSE, kernel, iterations=_WALL_CLOSE_ITER)
    except cv2.error:
        return None


# ── detectors ────────────────────────────────────────────────────────────────


def _detect_rooms(gray: Any, to_pt, scale: float) -> list[dict[str, Any]]:
    """Sealed light regions between walls -> area candidates (rooms).

    The wall mask is inverted to the room (paper) space and split into
    connected components. The whole-page background component spans all four
    borders and is dropped; components outside the size band are dropped as
    text gaps (too small) or floor envelopes / merges (too large). Each kept
    component's outline is simplified to a polygon; near-rectangular rooms
    score a touch higher than ragged ones.
    """
    wall = _wall_mask(gray)
    if wall is None:
        return []
    h, w = wall.shape[:2]
    page_area = float(h * w)
    if page_area <= 0:
        return []
    try:
        room_space = cv2.bitwise_not(wall)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(room_space, 8)
    except cv2.error:
        return []

    order = sorted(range(1, count), key=lambda i: -int(stats[i, cv2.CC_STAT_AREA]))
    out: list[dict[str, Any]] = []
    for idx in order:
        area_px = int(stats[idx, cv2.CC_STAT_AREA])
        frac = area_px / page_area
        if frac < _ROOM_MIN_PAGE_FRAC or frac > _ROOM_MAX_PAGE_FRAC:
            continue
        x = int(stats[idx, cv2.CC_STAT_LEFT])
        y = int(stats[idx, cv2.CC_STAT_TOP])
        bw = int(stats[idx, cv2.CC_STAT_WIDTH])
        bh = int(stats[idx, cv2.CC_STAT_HEIGHT])
        # The outside background spans the full page on all four sides - skip it.
        if x <= 2 and y <= 2 and x + bw >= w - 2 and y + bh >= h - 2:
            continue

        poly_px = _component_polygon(labels, idx)
        if poly_px is None or len(poly_px) < 3:
            continue

        bbox_area = float(bw * bh) or 1.0
        extent = area_px / bbox_area  # how rectangular the region's fill is
        if len(poly_px) <= _ROOM_RECT_MAX_VERTS and extent >= _ROOM_RECT_MIN_EXTENT:
            confidence = 0.60
            reason = "Rectangular room region detected from the scanned drawing (verify)"
        else:
            confidence = 0.45
            reason = "Room region detected from the scanned drawing (verify)"

        pts_pt = [to_pt(px, py) for px, py in poly_px]
        area_pt2 = _shoelace_area(pts_pt)
        out.append(
            {
                "type": "area",
                "points": [{"x": p[0], "y": p[1]} for p in pts_pt],
                "value": _area_value(area_pt2, scale),
                "dimension": "area",
                "count": None,
                "confidence": confidence,
                "reason": reason,
            }
        )
    return out


def _component_polygon(labels: Any, idx: int) -> list[Point] | None:
    """Simplified outer-contour polygon (in px) for one labelled component."""
    try:
        mask = (labels == idx).astype(np.uint8) * 255
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        contour = max(contours, key=cv2.contourArea)
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, _ROOM_APPROX_EPS_FRAC * peri, True)
        return [(float(p[0][0]), float(p[0][1])) for p in approx]
    except cv2.error:
        return None


def _detect_walls(gray: Any, to_pt, scale: float) -> list[dict[str, Any]]:
    """Long straight wall edges -> distance (length) candidates.

    Canny extracts wall edges and the probabilistic Hough transform fits line
    segments to them. Only segments longer than a fraction of the page diagonal
    are kept (short ones are hatching or annotation), near-duplicate segments
    are collapsed by endpoint grid, and the longest few are surfaced so the
    panel is not flooded.
    """
    h, w = gray.shape[:2]
    diag_px = math.hypot(w, h)
    min_len_px = max(1.0, _WALL_MIN_LEN_FRAC * diag_px)
    try:
        edges = cv2.Canny(gray, _CANNY_LO, _CANNY_HI)
        lines = cv2.HoughLinesP(
            edges,
            1,
            math.pi / 180,
            threshold=_HOUGH_VOTES,
            minLineLength=int(min_len_px),
            maxLineGap=_HOUGH_MAX_GAP_PX,
        )
    except cv2.error:
        return []
    if lines is None:
        return []

    segments: list[tuple[float, Point, Point]] = []
    for line in lines:
        x1, y1, x2, y2 = (float(v) for v in line[0])
        a, b = (x1, y1), (x2, y2)
        length_px = _seg_length(a, b)
        if length_px >= min_len_px:
            segments.append((length_px, a, b))
    segments.sort(key=lambda s: -s[0])

    span = segments[0][0] if segments else 1.0
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int, int]] = set()
    cell = _WALL_DEDUP_CELL_PX
    for length_px, a, b in segments:
        # Order-independent key so A->B and B->A collapse to one wall.
        ka = (round(a[0] / cell), round(a[1] / cell))
        kb = (round(b[0] / cell), round(b[1] / cell))
        key = (*min(ka, kb), *max(ka, kb))
        if key in seen:
            continue
        seen.add(key)
        a_pt, b_pt = to_pt(*a), to_pt(*b)
        # Longer edges relative to the longest are likelier to be real walls.
        confidence = round(min(0.50, 0.40 + 0.10 * (length_px / span)), 2)
        out.append(
            {
                "type": "distance",
                "points": [{"x": a_pt[0], "y": a_pt[1]}, {"x": b_pt[0], "y": b_pt[1]}],
                "value": _length_value(_seg_length(a_pt, b_pt), scale),
                "dimension": "length",
                "count": None,
                "confidence": confidence,
                "reason": "Wall line detected from the scan (verify)",
            }
        )
        if len(out) >= _MAX_WALLS:
            break
    return out


# ── public entry point ───────────────────────────────────────────────────────


def recognize_raster(
    image_bgr: Any,
    page_width_pt: float,
    page_height_pt: float,
    scale_pixels_per_unit: float | None,
    *,
    max_candidates: int = _MAX_CANDIDATES,
) -> list[dict[str, Any]]:
    """Detect rooms and walls in a rendered scanned page and rank candidates.

    Args:
        image_bgr: The rendered page as an ``HxWx3`` BGR ``np.ndarray`` (OpenCV
            convention). A single-channel grayscale array is also accepted.
        page_width_pt: PDF page width in points (used for the px -> pt map).
        page_height_pt: PDF page height in points.
        scale_pixels_per_unit: Viewer calibration in PDF points per real-world
            unit. When ``0`` / ``None`` every ``value`` is returned as ``None``
            (geometry only) so the user can calibrate, then accept.
        max_candidates: Hard cap on returned candidates.

    Returns:
        Candidate dicts in PDF point space, identical in shape to the vector
        recognizer's output, sorted by ``confidence`` descending and capped at
        ``max_candidates``. Returns ``[]`` on any unusable input rather than
        raising.
    """
    gray = _to_gray(image_bgr)
    if gray is None or gray.size == 0:
        return []
    h, w = gray.shape[:2]
    if h == 0 or w == 0 or page_width_pt <= 0 or page_height_pt <= 0:
        return []

    scale = float(scale_pixels_per_unit or 0.0)
    to_pt = _make_px_to_pt(w, h, page_width_pt, page_height_pt)

    candidates = _detect_rooms(gray, to_pt, scale) + _detect_walls(gray, to_pt, scale)
    candidates.sort(key=lambda c: c.get("confidence", 0.0), reverse=True)
    return candidates[:max_candidates]
