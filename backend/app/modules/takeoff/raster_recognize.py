# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Offline raster candidate detection for PDF takeoff (issue #194).

This is the raster twin of :mod:`app.modules.takeoff.recognize`. The vector
recognizer reads a page's drawing layer (``PdfPage.drawings()``); on a SCANNED
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

The module is pure (no DB, no FastAPI). ``cv2`` and ``numpy`` are base
dependencies, so this detector runs in every default install; only the OCR
engine sits behind the optional ``cv`` extra. They are imported at module top
on purpose: the *caller* imports this module lazily and catches
``ImportError``, so a broken OpenCV wheel degrades to an empty candidate set
instead of taking the whole takeoff service down at import time. Every risky
OpenCV call is wrapped so a degenerate image yields ``[]`` rather than raising.
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
_MAX_CANDIDATES = 100

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
        # HoughLinesP rows are normally shaped (1, 4); some OpenCV/numpy
        # builds return a flat (4,) row instead, which makes line[0] a
        # scalar. Take the four coordinates regardless of that nesting.
        row = line[0] if hasattr(line[0], "__len__") else line
        x1, y1, x2, y2 = (float(v) for v in row)
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


# ── scanned plan through the vector reader ───────────────────────────────────

# Work on at most this many pixels; a 150 dpi ARCH D sheet is ~19 Mpx.
_SCAN_PX_BUDGET = 6_000_000
# A dark band at most this thick (px) is a pen stroke; thicker is a filled wall.
_STROKE_MAX_PX = 4.0
# A scan never measures as exactly as CAD geometry, whatever the outline looks like.
_SCAN_CONF_FACTOR = 0.9
_SKETCH_MAX_PARTS = 60
# Pen weights differ by at least this factor when a drawing keeps cut walls apart from
# what lies beyond them, which is the usual ratio of two steps in the ISO 128 line series.
_HEAVY_LINE_RATIO = 1.4
# Line drawings leave most of the paper bare. A page with this much ink is a photo, a
# mottled scan or noise, and wall bands found in it would be accidents.
_MAX_INK_SHARE = 0.35


def _ink_map(gray: Any, shape: tuple[int, int]) -> Any:
    """How much of each work pixel is ink, 0 to 1, in the size of the wall mask.

    A pen line thinner than a pixel survives the threshold at full strength, so the
    binary mask cannot tell a dimension line from a wall face. Summed across the line,
    this map still can: JPEG, blur and resizing move ink around without changing how much.
    """
    paper = float(np.percentile(gray, 80))
    black = float(np.percentile(gray, 0.2))
    span = max(32.0, paper - black)
    ink = np.clip((paper - gray.astype(np.float32)) / span, 0.0, 1.0)
    return cv2.resize(ink, (shape[1], shape[0]), interpolation=cv2.INTER_AREA)


def _stroke_weight(ink: Any, band: Any) -> float:
    """Ink across a stroke in pixels: its pen width, median along the stroke."""
    c, lo, hi = round(band.c), int(band.lo), int(band.hi) + 1
    if band.axis == "h":
        patch = ink[max(0, c - 3) : c + 4, lo:hi]
        across = patch.sum(axis=0)
    else:
        patch = ink[lo:hi, max(0, c - 3) : c + 4]
        across = patch.sum(axis=1)
    return float(np.median(across)) if across.size else 0.0


def _heavy_split(weights: list[float], lengths: list[float]) -> float:
    """The pen weight separating heavy strokes from light ones, 0.0 when one pen drew them all.

    Otsu on log weight, each stroke counted by its length: lettering is many short
    strokes and should not get to decide what the pens of a drawing are.
    """
    if len(weights) < 8:
        return 0.0
    w = np.log(np.maximum(np.asarray(weights), 1e-3))
    m = np.asarray(lengths)
    order = np.argsort(w)
    w, m = w[order], m[order]
    cum_m = np.cumsum(m)
    cum_wm = np.cumsum(w * m)
    total_m, total_wm = cum_m[-1], cum_wm[-1]
    left = cum_m[:-1]
    right = total_m - left
    mean_l = cum_wm[:-1] / left
    mean_r = (total_wm - cum_wm[:-1]) / np.maximum(right, 1e-9)
    between = left * right * (mean_r - mean_l) ** 2
    at = int(np.argmax(between))
    if math.exp(mean_r[at] - mean_l[at]) < _HEAVY_LINE_RATIO:
        return 0.0
    return float(math.exp(0.5 * (w[at] + w[at + 1])))


def _dark_mask(gray: Any) -> tuple[Any, float]:
    """Binary ink mask of a scan, downscaled to the pixel budget; returns (mask, factor)."""
    blur = cv2.medianBlur(gray, 3)
    _thr, dark = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    h, w = dark.shape
    f = min(1.0, math.sqrt(_SCAN_PX_BUDGET / max(1, h * w)))
    if f < 1.0:
        # pool rather than average so a one-pixel pen line survives the shrink
        dark = cv2.resize(dark, (max(1, int(w * f)), max(1, int(h * f))), interpolation=cv2.INTER_AREA)
        dark = np.where(dark > 60, 255, 0).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    speck = stats[:, cv2.CC_STAT_AREA] < 6
    speck[0] = False
    if speck.any():
        dark[speck[lab]] = 0
    del lab
    return dark, f


def _skew_deg(dark: Any) -> float:
    """Drawing angle of the ink in degrees, from its long straight strokes."""
    from app.modules.takeoff import vector_plan as vp

    small = dark
    if dark.shape[0] * dark.shape[1] > 1_500_000:
        g = math.sqrt(1_500_000 / (dark.shape[0] * dark.shape[1]))
        small = cv2.resize(dark, None, fx=g, fy=g, interpolation=cv2.INTER_AREA)
        small = np.where(small > 60, 255, 0).astype(np.uint8)
    lines = cv2.HoughLinesP(small, 1, math.pi / 720, threshold=40, minLineLength=30, maxLineGap=2)
    if lines is None:
        return 0.0
    segs = [vp.Seg((float(x1), float(y1)), (float(x2), float(y2)), 1.0, 0) for x1, y1, x2, y2 in lines.reshape(-1, 4)]
    return _refine_skew(dark, math.degrees(vp.dominant_angle(segs, [])))


def _refine_skew(dark: Any, ang: float) -> float:
    """Sharpen a skew estimate to a few hundredths of a degree.

    A long pen line drifting by a pixel breaks into steps; the angle at which the
    ink's row and column profiles are sharpest is the one that keeps it whole.
    """
    ys, xs = np.nonzero(dark)
    if xs.size < 100:
        return ang
    step = max(1, xs.size // 300_000)
    xs, ys = xs[::step].astype(np.float64), ys[::step].astype(np.float64)
    best, best_score = ang, -1.0
    for a in ang + np.arange(-0.5, 0.501, 0.025):
        t = math.radians(a)
        c, sn = math.cos(t), math.sin(t)
        rows = np.rint(ys * c - xs * sn).astype(np.int64)
        cols = np.rint(xs * c + ys * sn).astype(np.int64)
        score = float(np.square(np.bincount(rows - rows.min())).sum() + np.square(np.bincount(cols - cols.min())).sum())
        if score > best_score:
            best, best_score = float(a), score
    return best


def scan_parts(
    gray: Any, page_width_pt: float, page_height_pt: float, budget: Any = None
) -> tuple[list[Any], list[Any], int]:
    """Heavy pen strokes and filled wall bands of a scanned page in page points, and all ink parts found.

    The count says how busy the sheet is; a page too inky to be a line drawing counts as
    busier than any sketch and yields no parts.
    """
    from app.modules.takeoff import floorplan as fp
    from app.modules.takeoff import vector_plan as vp

    dark, f = _dark_mask(gray)
    h, w = dark.shape
    if np.count_nonzero(dark) > _MAX_INK_SHARE * h * w:
        return [], [], _SKETCH_MAX_PARTS + 1
    if budget is not None:
        budget.check()
    ang = _skew_deg(dark)
    if budget is not None:
        budget.check()
    inv = None
    if abs(ang) >= 0.2:
        # straighten so the walls run along the pixel axes
        rot = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), ang, 1.0)
        cos, sin = abs(rot[0, 0]), abs(rot[0, 1])
        nw, nh = int(h * sin + w * cos) + 2, int(h * cos + w * sin) + 2
        rot[0, 2] += nw / 2.0 - w / 2.0
        rot[1, 2] += nh / 2.0 - h / 2.0
        dark = cv2.warpAffine(dark, rot, (nw, nh), flags=cv2.INTER_NEAREST)
        inv = cv2.invertAffineTransform(rot)
    sx, sy = page_width_pt / w, page_height_pt / h

    def to_pt(x: float, y: float) -> tuple[float, float]:
        if inv is not None:
            x, y = inv[0, 0] * x + inv[0, 1] * y + inv[0, 2], inv[1, 0] * x + inv[1, 1] * y + inv[1, 2]
        return (x * sx, y * sy)

    ink = _ink_map(gray, (h, w))
    if inv is not None:
        ink = cv2.warpAffine(ink, rot, (nw, nh), flags=cv2.INTER_LINEAR)
    segs: list[Any] = []
    fills: list[Any] = []
    strokes: list[tuple[Any, float]] = []
    for b in fp.axis_bands(dark, min_len_px=8):
        if b.hi - b.lo < 3:
            continue
        if b.t <= _STROKE_MAX_PX:
            strokes.append((b, _stroke_weight(ink, b)))
        else:
            # junction bulges widen a band's extent, not its mean thickness
            lo, hi, c0, c1 = b.lo, b.hi, b.c - b.t / 2, b.c + b.t / 2
            box = (
                [(lo, c0), (hi, c0), (hi, c1), (lo, c1)] if b.axis == "h" else [(c0, lo), (c0, hi), (c1, hi), (c1, lo)]
            )
            fills.append(vp.Fill([to_pt(*p) for p in box], 0.0, len(fills)))
    split = _heavy_split([wt for _b, wt in strokes], [b.hi - b.lo for b, _wt in strokes])
    for b, wt in strokes:
        if wt < split:
            continue  # dimensions, furniture, door swings: what lies beyond the cut, in a lighter pen
        a, c = ((b.lo, b.c), (b.hi, b.c)) if b.axis == "h" else ((b.c, b.lo), (b.c, b.hi))
        segs.append(vp.Seg(to_pt(*a), to_pt(*c), wt * sx, len(segs)))
    return segs, fills, len(strokes) + len(fills)


def _plan_candidates(
    gray: Any, page_width_pt: float, page_height_pt: float, scale: float, budget: Any = None
) -> tuple[list[dict[str, Any]], int]:
    """Rooms and walls of a scanned plan read like a vector page, and how many ink parts it has."""
    from app.modules.takeoff import recognize, vector_plan

    segs, fills, n_parts = scan_parts(gray, page_width_pt, page_height_pt, budget)
    if not segs and not fills:
        return [], n_parts
    plan = vector_plan.read_parts(segs, fills, [], scale or None, budget=budget)
    if not plan.found_structure or not vector_plan.looks_like_rooms(plan):
        return [], n_parts
    plan.counts = []  # pen strokes of a scan do not carry symbol identity
    out = recognize.plan_candidates(plan, scale)
    for cand in out:
        cand["confidence"] = round(cand["confidence"] * _SCAN_CONF_FACTOR, 3)
        cand.setdefault("count", None)
        cand["reason"] = cand["reason"].replace("vector layer", "scanned image")
    return out, n_parts


def recognize_raster(
    image_bgr: Any,
    page_width_pt: float,
    page_height_pt: float,
    scale_pixels_per_unit: float | None,
    *,
    max_candidates: int = _MAX_CANDIDATES,
    budget: Any = None,
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
        budget: Optional :class:`~app.modules.takeoff.vector_plan.Budget`; running
            out of it raises ``TimeBudgetExceeded`` to the caller.

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

    try:
        candidates, n_parts = _plan_candidates(gray, page_width_pt, page_height_pt, scale, budget)
    except (cv2.error, ValueError, MemoryError):
        candidates, n_parts = [], 0
    # A sparse sketch (a few outlined boxes) is read by the outline detectors; on a
    # busy sheet with no wall structure (notes, details, a schedule) every closed
    # loop they find would be noise.
    if n_parts <= _SKETCH_MAX_PARTS:
        candidates = _detect_rooms(gray, to_pt, scale) + _detect_walls(gray, to_pt, scale)
    candidates.sort(key=lambda c: c.get("confidence", 0.0), reverse=True)
    return candidates[:max_candidates]
