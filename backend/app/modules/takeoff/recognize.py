# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Offline, deterministic candidate detection for PDF takeoff (issue #194).

The online counterpart is the LLM text analyzer (``POST /documents/{id}/analyze/``).
This module is its offline, geometry-driven complement: it reads the vector
drawing layer of a PDF page (PyMuPDF ``page.get_drawings()``) and proposes
candidate measurements:

* rectangles and clean closed loops -> ``area`` candidates,
* long straight strokes -> ``distance`` (length) candidates,
* repeated small closed shapes -> ``count`` candidates.

Nothing is persisted here. Every candidate carries an honest ``confidence``
and a human-readable ``reason`` so the user confirms, edits or rejects it on
the canvas (CLAUDE.md rule 7: AI-augmented, human-confirmed).

The module is pure and DB-free so it unit-tests without a database or a real
PDF. PyMuPDF is imported lazily by the *caller* (it is an optional ``cv``
extra, absent on a default install); this module only consumes the already
extracted primitives, accessing point-like / rect-like objects defensively so
tests can feed plain tuples.
"""

from __future__ import annotations

import math
from typing import Any

# Coordinates from get_drawings() are in PDF points - the same space the
# frontend stores measurement points in, so they drop straight in with no
# transform (see docs/strategy/PDF_TAKEOFF_194_PLAN.md).

# A segment must be at least this many PDF points long to be considered a
# real stroke (filters hatching, leader ticks and rendering noise).
_MIN_SEGMENT_PX = 18.0
# A closed loop must enclose at least this pixel-squared area to count as a
# region worth measuring (filters glyph outlines and tiny symbols).
_MIN_AREA_PX2 = 600.0
# Small closed shapes below this bbox diagonal are treated as countable
# symbols rather than measurable regions.
_SYMBOL_MAX_DIAG_PX = 46.0
# A repeated-symbol cluster needs at least this many near-identical members.
_MIN_CLUSTER = 3
# Never return more than this many candidates (keeps the review panel sane).
_MAX_CANDIDATES = 40

Point = tuple[float, float]


# ── point / rect extraction (defensive: fitz objects OR plain tuples) ───────


def _xy(obj: Any) -> Point | None:
    """Best-effort (x, y) from a fitz.Point, a (x, y) pair or a mapping."""
    try:
        if hasattr(obj, "x") and hasattr(obj, "y"):
            return (float(obj.x), float(obj.y))
        if isinstance(obj, dict):
            return (float(obj["x"]), float(obj["y"]))
        if isinstance(obj, (list, tuple)) and len(obj) >= 2:
            return (float(obj[0]), float(obj[1]))
    except (TypeError, ValueError, KeyError):
        return None
    return None


def _rect_corners(obj: Any) -> list[Point] | None:
    """Four corner points (CW) from a fitz.Rect-like or a 4-number bbox."""
    try:
        if all(hasattr(obj, a) for a in ("x0", "y0", "x1", "y1")):
            x0, y0, x1, y1 = float(obj.x0), float(obj.y0), float(obj.x1), float(obj.y1)
        elif isinstance(obj, (list, tuple)) and len(obj) >= 4:
            x0, y0, x1, y1 = (float(obj[0]), float(obj[1]), float(obj[2]), float(obj[3]))
        else:
            return None
    except (TypeError, ValueError):
        return None
    lo_x, hi_x = sorted((x0, x1))
    lo_y, hi_y = sorted((y0, y1))
    return [(lo_x, lo_y), (hi_x, lo_y), (hi_x, hi_y), (lo_x, hi_y)]


# ── geometry (self-contained twins of the service helpers) ──────────────────


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


def _polyline_length(pts: list[Point]) -> float:
    return sum(_seg_length(pts[i - 1], pts[i]) for i in range(1, len(pts)))


def _bbox(pts: list[Point]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _is_axis_rectangular(pts: list[Point]) -> bool:
    """True when a 4-point loop is (near) an axis-aligned rectangle."""
    if len(pts) != 4:
        return False
    x0, y0, x1, y1 = _bbox(pts)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return False
    # Every vertex must sit close to a bbox corner (within 4% of the diagonal).
    tol = 0.04 * math.hypot(w, h)
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return all(any(_seg_length(p, c) <= tol for c in corners) for p in pts)


def _segments_self_intersect(pts: list[Point]) -> bool:
    """Cheap self-intersection test for a closed polygon (n is small)."""
    n = len(pts)
    if n < 4:
        return False

    def _ccw(a: Point, b: Point, c: Point) -> bool:
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])

    def _cross(a: Point, b: Point, c: Point, d: Point) -> bool:
        return _ccw(a, c, d) != _ccw(b, c, d) and _ccw(a, b, c) != _ccw(a, b, d)

    edges = [(pts[i], pts[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if j == i or (i == 0 and j == n - 1) or j == i + 1:
                continue
            if _cross(*edges[i], *edges[j]):
                return True
    return False


# ── primitive extraction from get_drawings() ────────────────────────────────


class _Primitive:
    """A normalized vector primitive harvested from one drawing path."""

    __slots__ = ("kind", "points")

    def __init__(self, kind: str, points: list[Point]) -> None:
        self.kind = kind  # "rect" | "loop" | "segment"
        self.points = points


def primitives_from_drawings(drawings: list[Any]) -> list[_Primitive]:
    """Normalize PyMuPDF ``page.get_drawings()`` output into primitives.

    Each path becomes zero or more primitives: an explicit ``re`` item is a
    rectangle; a run of connected ``l`` items that returns to its start is a
    closed loop; the remaining long ``l`` items are standalone segments.
    Bezier (``c``) and quad (``qu``) items are flattened to their endpoints
    so curved strokes still contribute a length estimate.
    """
    prims: list[_Primitive] = []
    for path in drawings or []:
        items = path.get("items") if isinstance(path, dict) else getattr(path, "items", None)
        if not items:
            continue
        chain: list[Point] = []
        loose: list[tuple[Point, Point]] = []
        for it in items:
            if not it:
                continue
            op = it[0]
            if op == "re":
                corners = _rect_corners(it[1]) if len(it) > 1 else None
                if corners:
                    prims.append(_Primitive("rect", corners))
            elif op in ("l", "c", "qu"):
                pts = [p for p in (_xy(x) for x in it[1:]) if p is not None]
                if len(pts) >= 2:
                    a, b = pts[0], pts[-1]
                    loose.append((a, b))
                    if not chain:
                        chain.append(a)
                    chain.append(b)
        # A path whose vertices return to the start is a closed loop.
        if len(chain) >= 4 and _seg_length(chain[0], chain[-1]) <= _MIN_SEGMENT_PX:
            prims.append(_Primitive("loop", chain[:-1]))
        else:
            for a, b in loose:
                if _seg_length(a, b) >= _MIN_SEGMENT_PX:
                    prims.append(_Primitive("segment", [a, b]))
    return prims


# ── detectors ───────────────────────────────────────────────────────────────


def _area_value(pts: list[Point], scale: float) -> float | None:
    if scale and scale > 0:
        return _shoelace_area(pts) / (scale * scale)
    return None


def _length_value(pts: list[Point], scale: float) -> float | None:
    if scale and scale > 0:
        return _polyline_length(pts) / scale
    return None


def detect_areas(prims: list[_Primitive], scale: float) -> list[dict[str, Any]]:
    """Rectangles and clean closed loops -> area candidates."""
    out: list[dict[str, Any]] = []
    for prim in prims:
        if prim.kind not in ("rect", "loop"):
            continue
        pts = prim.points
        if len(pts) < 3:
            continue
        area_px = _shoelace_area(pts)
        if area_px < _MIN_AREA_PX2:
            continue
        x0, y0, x1, y1 = _bbox(pts)
        if math.hypot(x1 - x0, y1 - y0) < _SYMBOL_MAX_DIAG_PX:
            continue  # too small - handled by the count detector
        if prim.kind == "rect" or _is_axis_rectangular(pts):
            confidence, reason = 0.85, "Closed rectangle in the drawing's vector layer"
        elif _segments_self_intersect(pts):
            confidence, reason = 0.3, "Closed region (self-intersecting outline, verify)"
        else:
            confidence, reason = 0.62, "Closed polygon region in the vector layer"
        out.append(
            {
                "type": "area",
                "points": [{"x": p[0], "y": p[1]} for p in pts],
                "value": _area_value(pts, scale),
                "dimension": "area",
                "confidence": confidence,
                "reason": reason,
            }
        )
    return out


def detect_lengths(prims: list[_Primitive], scale: float) -> list[dict[str, Any]]:
    """Long straight strokes -> distance (length) candidates.

    Only the longer strokes are surfaced: short segments are almost always
    hatching, dimension ticks or symbol detail, not a wall the user wants to
    measure. The cut is the 70th length percentile (with a hard floor) so a
    busy sheet does not flood the panel with every tick mark.
    """
    segs = [p for p in prims if p.kind == "segment"]
    if not segs:
        return []
    lengths = sorted(_seg_length(p.points[0], p.points[1]) for p in segs)
    cut = max(lengths[int(len(lengths) * 0.7)], _MIN_SEGMENT_PX * 2.5)
    span = lengths[-1] or 1.0
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for prim in segs:
        a, b = prim.points[0], prim.points[1]
        length_px = _seg_length(a, b)
        if length_px < cut:
            continue
        key = (round(a[0] / 6), round(a[1] / 6), round(b[0] / 6), round(b[1] / 6))
        if key in seen:
            continue
        seen.add(key)
        # Longer-than-typical strokes are likelier to be real walls/grid lines.
        confidence = round(min(0.82, 0.55 + 0.27 * (length_px / span)), 2)
        out.append(
            {
                "type": "distance",
                "points": [{"x": a[0], "y": a[1]}, {"x": b[0], "y": b[1]}],
                "value": _length_value([a, b], scale),
                "dimension": "length",
                "confidence": confidence,
                "reason": "Long straight stroke in the vector layer",
            }
        )
    return out


def detect_counts(prims: list[_Primitive]) -> list[dict[str, Any]]:
    """Repeated small closed shapes -> one count candidate per cluster.

    Small closed shapes are clustered by a (width, height, vertex-count)
    signature; any group of at least three near-identical shapes becomes a
    single count candidate whose points are the shape centroids. Tighter
    clusters (more uniform size) score higher.
    """
    buckets: dict[tuple[int, int, int], list[tuple[Point, float]]] = {}
    for prim in prims:
        if prim.kind not in ("rect", "loop"):
            continue
        pts = prim.points
        if len(pts) < 3:
            continue
        x0, y0, x1, y1 = _bbox(pts)
        w, h = x1 - x0, y1 - y0
        diag = math.hypot(w, h)
        if diag == 0 or diag > _SYMBOL_MAX_DIAG_PX:
            continue
        sig = (round(w / 4), round(h / 4), len(pts))
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        buckets.setdefault(sig, []).append(((cx, cy), diag))

    out: list[dict[str, Any]] = []
    for members in buckets.values():
        if len(members) < _MIN_CLUSTER:
            continue
        diags = [d for _, d in members]
        spread = (max(diags) - min(diags)) / (mean := sum(diags) / len(diags) or 1.0)
        confidence = round(max(0.5, min(0.8, 0.8 - spread)), 2)
        out.append(
            {
                "type": "count",
                "points": [{"x": c[0], "y": c[1]} for c, _ in members],
                "value": float(len(members)),
                "count": len(members),
                "dimension": "count",
                "confidence": confidence,
                "reason": f"{len(members)} repeated symbols of a similar size",
            }
        )
    return out


def recognize_candidates(
    drawings: list[Any],
    scale_pixels_per_unit: float | None = None,
    *,
    max_candidates: int = _MAX_CANDIDATES,
) -> list[dict[str, Any]]:
    """Run all detectors over a page's drawings and rank the candidates.

    ``scale_pixels_per_unit`` is used only to fill in a real-world ``value``
    preview; when it is missing or non-positive the geometry is still
    returned (``value`` is ``None``) so the user can calibrate, then accept.
    Candidates are sorted by confidence and capped at ``max_candidates``.
    """
    scale = float(scale_pixels_per_unit or 0.0)
    prims = primitives_from_drawings(drawings)
    candidates = detect_areas(prims, scale) + detect_lengths(prims, scale) + detect_counts(prims)
    candidates.sort(key=lambda c: c.get("confidence", 0.0), reverse=True)
    return candidates[:max_candidates]
