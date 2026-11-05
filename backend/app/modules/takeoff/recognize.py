# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Offline, deterministic candidate detection for PDF takeoff (issue #194).

The online counterpart is the LLM text analyzer (``POST /documents/{id}/analyze/``).
This module is its offline, geometry-driven complement: it reads the vector
drawing layer of a PDF page (``PdfPage.drawings()`` in :mod:`app.core.pdf_reader`) and proposes
candidate measurements:

* rectangles and clean closed loops -> ``area`` candidates,
* long straight strokes -> ``distance`` (length) candidates,
* repeated small closed shapes -> ``count`` candidates.

Nothing is persisted here. Every candidate carries an honest ``confidence``
and a human-readable ``reason`` so the user confirms, edits or rejects it on
the canvas (CLAUDE.md rule 7: AI-augmented, human-confirmed).

The module is pure and DB-free so it unit-tests without a database or a real
PDF. The PDF reader is a base dependency and is imported lazily by the *caller*; this
module only consumes the already extracted primitives, accessing point-like /
rect-like objects defensively so tests can feed plain tuples.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

logger = logging.getLogger(__name__)

# Coordinates from drawings() are in PDF points - the same space the
# frontend stores measurement points in, so they drop straight in with no
# transform (see internal design note PDF_TAKEOFF_194_PLAN).

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
# Every proposal is a row someone has to confirm or reject before the quantities can
# go to a bill, so a sheet may not bury its reviewer: a floor of 30 rooms has about
# twice as many wall runs and a few symbol counts. Past this, rooms go first and the
# weakest walls are held back; the response says how many.
_MAX_CANDIDATES = 100
# Below this a proposal costs the reviewer more than it can save.
_MIN_CONFIDENCE = 0.35
# A drawing without a wall structure is read by the simple shape detectors only
# when it is this small and says this little: closed loops on a full sheet or on a
# page of text are table cells, title blocks and legends, not rooms.
_SKETCH_MAX_PATHS = 60
_SKETCH_MAX_WORDS = 60
# A page that takes longer than this comes back with what was read by then.
_TIME_BUDGET_S = 30.0
# Scans are rendered for reading at this resolution, or less on large sheets: an A0
# at 150 dpi would hold 100 MB for no better a wall mask.
_RENDER_DPI = 150.0
_RENDER_MAX_PX = 16_000_000

_AREA_TAG_RE = re.compile(r"^(\d{1,6}(?:[.,]\d{1,3})?)\s*(m²|m2|м²|м2|qm|sf|sq\.?\s*ft\.?|ft²|sqm)?$", re.IGNORECASE)
_AREA_UNIT_RE = re.compile(r"^(m²|m2|м²|м2|qm|sqm|sf|sq\.?\s*ft\.?|ft²)\.?$", re.IGNORECASE)
_SQFT_M2 = 0.09290304

Point = tuple[float, float]


# ── point / rect extraction (defensive: named tuples OR plain tuples) ───────


def _xy(obj: Any) -> Point | None:
    """Best-effort (x, y) from a Point, a (x, y) pair or a mapping."""
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
    """Four corner points (CW) from a Rect-like or a 4-number bbox."""
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


# ── primitive extraction from drawings() ────────────────────────────────────


class _Primitive:
    """A normalized vector primitive harvested from one drawing path."""

    __slots__ = ("kind", "points")

    def __init__(self, kind: str, points: list[Point]) -> None:
        self.kind = kind  # "rect" | "loop" | "segment"
        self.points = points


def primitives_from_drawings(drawings: list[Any]) -> list[_Primitive]:
    """Normalize ``PdfPage.drawings()`` output into primitives.

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


def _rank_and_cap(candidates: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], int]:
    """The strongest proposals, rooms before counts before walls, and how many were held back."""
    kept = [c for c in candidates if c.get("confidence", 0.0) >= _MIN_CONFIDENCE]
    order = {"area": 0, "count": 1}
    kept.sort(key=lambda c: (order.get(c.get("dimension"), 2), -c.get("confidence", 0.0)))
    chosen = kept[:limit]
    chosen.sort(key=lambda c: c.get("confidence", 0.0), reverse=True)
    return chosen, len(kept) - len(chosen)


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
    candidates, _note = _read_vector_page(drawings, float(scale_pixels_per_unit or 0.0), None, [], None, None)
    return _rank_and_cap(candidates, max_candidates)[0]


def _read_vector_page(
    drawings: list[Any],
    scale: float,
    page_size: tuple[float, float] | None,
    words: list[Any],
    budget: Any,
    verdict: Any,
) -> tuple[list[dict[str, Any]], str | None]:
    """Candidates of a page with line art, and a note when they are limited or absent."""
    from app.modules.takeoff import sheet_type  # noqa: PLC0415

    if verdict is not None and verdict.from_title_block:
        if verdict.kind in sheet_type.NOT_A_PLAN:
            return [], "not_a_floor_plan"
        if verdict.kind == sheet_type.STRUCTURAL:
            # Columns and footings are worth counting; its outlines are not rooms.
            return detect_counts(primitives_from_drawings(drawings)), "not_a_floor_plan"
    note: str | None = None
    plan = None
    try:
        from app.modules.takeoff import vector_plan  # noqa: PLC0415 - numpy/OpenCV only when a page is read

        try:
            plan = vector_plan.read_plan(drawings, scale or None, page_size=page_size, budget=budget)
        except vector_plan.TimeBudgetExceeded:
            return [], "time_budget"
    except Exception:  # a malformed path must not cost the user the simple detectors
        logger.exception("takeoff.recognize: floor-plan reader failed, using the shape detectors")
    if plan is not None and plan.out_of_time:
        note = "time_budget"
    is_rooms = plan is not None and plan.found_structure and vector_plan.looks_like_rooms(plan)
    if is_rooms:
        return plan_candidates(plan, scale, words), note
    prims = primitives_from_drawings(drawings)
    if len(drawings or []) <= _SKETCH_MAX_PATHS and len(words) <= _SKETCH_MAX_WORDS:
        return detect_areas(prims, scale) + detect_lengths(prims, scale) + detect_counts(prims), note
    # Rooms did not come out, whatever the sheet is: what repeats on it can still be counted.
    if plan is not None and plan.found_structure:
        note = note or "not_a_floor_plan"
    return detect_counts(prims), note


def recognize_pdf_page(
    pdf: bytes,
    page: int,
    scale_pixels_per_unit: float | None = None,
    *,
    budget_s: float | None = _TIME_BUDGET_S,
    max_candidates: int = _MAX_CANDIDATES,
) -> dict[str, Any]:
    """Read one page of a PDF: the single path the service and the benchmark share.

    Blocking and CPU-bound, so the service runs it in a worker thread. Returns
    ``{candidates, source, notes, truncated}``. ``notes`` is ``None`` or one of
    ``no_features``, ``raster_no_features``, ``not_a_floor_plan``, ``time_budget``,
    ``raster_cv_unavailable``; a sheet that is not a floor plan and a sheet that ran
    out of time are both clear results rather than errors.
    """
    from app.core import pdf_reader  # noqa: PLC0415
    from app.modules.takeoff import sheet_type, vector_plan  # noqa: PLC0415

    budget = vector_plan.Budget(budget_s)
    scale = float(scale_pixels_per_unit or 0.0)
    samples = None
    with pdf_reader.open_pdf(pdf) as doc:
        pg = doc[page - 1]
        drawings = pg.drawings(with_clip=True)
        width, height = float(pg.rect.width), float(pg.rect.height)
        words = pg.words() if drawings else []
        rotation = pg.rotation
        if not drawings:
            dpi = min(_RENDER_DPI, 72.0 * (_RENDER_MAX_PX / max(1.0, width * height)) ** 0.5)
            try:
                pix = pg.render(dpi=dpi)
                samples = (pix.samples, pix.height, pix.width, pix.n)
            except Exception:
                logger.exception("takeoff.recognize: page render failed")
                return {"candidates": [], "source": "vector_recognize", "notes": "no_vector_layer", "truncated": 0}
    if samples is None:
        # Line art and words come in the frame of the unrotated page, the size as viewed.
        frame = (height, width) if rotation in (90, 270) else (width, height)
        verdict = sheet_type.classify(_as_viewed(words, rotation, frame), width, height)
        candidates, note = _read_vector_page(drawings, scale, frame, words, budget, verdict)
        kept, held_back = _rank_and_cap(candidates, max_candidates)
        return {
            "candidates": kept,
            "source": "vector_recognize",
            "notes": note if note or kept else "no_features",
            "truncated": held_back,
        }
    return _read_scan_page(samples, width, height, scale, budget, max_candidates)


def _as_viewed(words: list[Any], rotation: int, frame: tuple[float, float]) -> list[Any]:
    """Word boxes as the sheet is viewed: title blocks are found by where a reader sees them."""
    if rotation == 90:
        return [(frame[1] - w[3], w[0], frame[1] - w[1], w[2], w[4]) for w in words]
    if rotation == 180:
        return [(frame[0] - w[2], frame[1] - w[3], frame[0] - w[0], frame[1] - w[1], w[4]) for w in words]
    if rotation == 270:
        return [(w[1], frame[0] - w[2], w[3], frame[0] - w[0], w[4]) for w in words]
    return words


def _read_scan_page(
    samples: tuple[bytes, int, int, int],
    width: float,
    height: float,
    scale: float,
    budget: Any,
    max_candidates: int,
) -> dict[str, Any]:
    try:
        import numpy as np  # noqa: PLC0415

        from app.modules.takeoff import raster_recognize, vector_plan  # noqa: PLC0415
    except ImportError:
        return {"candidates": [], "source": "raster_recognize", "notes": "raster_cv_unavailable", "truncated": 0}
    data, rows, cols, channels = samples
    arr = np.frombuffer(data, dtype=np.uint8).reshape(rows, cols, channels)
    image = np.ascontiguousarray(arr[:, :, 2::-1]) if channels >= 3 else arr.reshape(rows, cols)
    try:
        candidates = raster_recognize.recognize_raster(image, width, height, scale, budget=budget)
    except vector_plan.TimeBudgetExceeded:
        return {"candidates": [], "source": "raster_recognize", "notes": "time_budget", "truncated": 0}
    except Exception:
        logger.exception("takeoff.recognize: raster detection failed")
        return {"candidates": [], "source": "vector_recognize", "notes": "no_vector_layer", "truncated": 0}
    kept, held_back = _rank_and_cap(candidates, max_candidates)
    return {
        "candidates": kept,
        "source": "raster_recognize",
        "notes": None if kept else "raster_no_features",
        "truncated": held_back,
    }


def _inside_poly(x: float, y: float, poly: list[Point]) -> bool:
    hit = False
    x1, y1 = poly[-1]
    for x2, y2 in poly:
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
        x1, y1 = x2, y2
    return hit


def _printed_area_m2(words: list[Any], i: int) -> float | None:
    """The area a room tag prints at word ``i`` ("33.41 m²", "120 SF"), in square metres."""
    tok = str(words[i][4])
    m = _AREA_TAG_RE.match(tok)
    if not m:
        return None
    unit = m.group(2)
    if not unit and i + 1 < len(words) and _AREA_UNIT_RE.match(str(words[i + 1][4])):
        unit = str(words[i + 1][4])
    if not unit:
        return None
    value = float(m.group(1).replace(",", "."))
    return value * _SQFT_M2 if unit.lower().startswith(("sf", "sq.", "sq ", "ft", "sqf")) else value


def _room_labels(pts: list[Point], words: list[Any]) -> tuple[bool, float | None]:
    """Whether a name is printed inside a room, and the area its tag prints if it has one."""
    x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
    x1, y1 = max(p[0] for p in pts), max(p[1] for p in pts)
    named = False
    printed: float | None = None
    for i, w in enumerate(words):
        cx, cy = 0.5 * (w[0] + w[2]), 0.5 * (w[1] + w[3])
        if not (x0 <= cx <= x1 and y0 <= cy <= y1) or not _inside_poly(cx, cy, pts):
            continue
        tok = str(w[4])
        if sum(c.isalpha() for c in tok) >= 3 and all(c.isalpha() or c in ".-'/" for c in tok):
            named = True
        area = _printed_area_m2(words, i)
        if area is not None and printed is None:
            printed = area
    return named, printed


def _room_confidence(
    room: dict[str, Any], area_m2: float | None, named: bool, printed: float | None, name_weight: float
) -> tuple[float, list[str]]:
    """How likely this outline is a real room, from what can be checked about it.

    Nothing here depends on how exactly the outline snapped to CAD lines, which garbage
    does as readily as a room: the walls have to close it, the shape has to be one a room
    has, the size has to be one a room has, and if the sheet names its rooms this one has
    to be named. A printed area that agrees with the outline settles it either way.
    """
    why: list[str] = []
    score = 0.2 + 0.15 * room["closure"]
    rect = float(room["rectangularity"])
    aspect = float(room["aspect"])
    shape = rect * min(1.0, 6.0 / max(aspect, 1.0)) * (0.8 if room["vertices"] > 12 else 1.0)
    score += 0.12 * shape
    score += 0.06 if room["neighbours"] else 0.0
    if area_m2 is None:
        score += 0.06
    else:
        score += 0.12 * min(1.0, area_m2 / 2.0, 200.0 / max(area_m2, 1e-6))
    score += 0.03 * room["snapped"]
    if named:
        score += name_weight
        why.append("named on the sheet")
    if printed is not None and area_m2 is not None:
        if abs(printed - area_m2) <= 0.1 * printed:
            score += 0.2
            why.append("printed area agrees")
        else:
            score -= 0.25
            why.append("printed area differs")
    return max(0.2, min(0.97, score)), why


def plan_candidates(plan: Any, scale: float, words: list[Any] | None = None) -> list[dict[str, Any]]:
    """Candidates from a :class:`~app.modules.takeoff.vector_plan.PlanResult`."""
    out: list[dict[str, Any]] = []
    words = words or []
    labels = [_room_labels(room["points"], words) for room in plan.rooms]
    share = sum(1 for named, _p in labels if named) / len(labels) if labels else 0.0
    # With no text to read a name is no evidence either way; on a sheet that names its
    # rooms an outline without a name has to earn its place by the rest.
    name_weight = 0.2 + 0.15 * share if words else 0.0
    base = 0.0 if words else 0.1
    for room, (named, printed) in zip(plan.rooms, labels, strict=True):
        pts = room["points"]
        value = _area_value(pts, scale)
        conf, why = _room_confidence(room, value, named, printed, name_weight)
        out.append(
            {
                "type": "area",
                "points": [{"x": p[0], "y": p[1]} for p in pts],
                "value": value,
                "dimension": "area",
                "confidence": round(min(0.97, conf + base), 2),
                "reason": "; ".join(["Room enclosed by walls in the vector layer", *why]),
            }
        )
    for wall in plan.walls:
        a, b = wall["points"]
        conf = 0.5 + 0.3 * wall["support"] + 0.05 * wall["joined"]
        out.append(
            {
                "type": "distance",
                "points": [{"x": a[0], "y": a[1]}, {"x": b[0], "y": b[1]}],
                "value": _length_value([a, b], scale),
                "dimension": "length",
                "confidence": round(max(0.3, min(0.9, conf)), 2),
                "reason": "Wall centreline, junction to junction",
            }
        )
    for group in plan.counts:
        n = group["count"]
        out.append(
            {
                "type": "count",
                "points": [{"x": p[0], "y": p[1]} for p in group["points"]],
                "value": float(n),
                "count": n,
                "dimension": "count",
                "confidence": group["confidence"],
                "reason": f"{n} identical symbols inside the rooms",
            }
        )
    return out


# ── seeded similar-symbol search ("count by example") ────────────────────────
#
# The user clicks one symbol on the page; we find every near-identical symbol
# and return their centroids so the user confirms them as a single count
# measurement (CLAUDE.md rule 7: nothing is persisted here). This reuses the
# exact (width, height, vertex-count) signature the cluster detector buckets
# by, but seeds the signature from the clicked symbol instead of auto-grouping.

# A click is taken to "land on" a symbol when it is within this many PDF points
# of the symbol's centroid, or within the symbol's own size, whichever is more
# forgiving (so a click anywhere on a small symbol still selects it).
_SEED_PICK_TOL_PX = 24.0
# Two hits whose centroids are closer than this are the same symbol (NMS dedup).
_HIT_NMS_PX = 6.0
# Cap the hits returned from a single seed so the review panel stays sane.
_MAX_SIMILAR = 200


def _symbol_primitives(
    prims: list[_Primitive],
) -> list[tuple[_Primitive, Point, float, float, float]]:
    """Small closed shapes as ``(prim, centroid, w, h, diag)``.

    Only countable-symbol-sized closed shapes are returned (the same size gate
    the count detector applies); larger regions are walls/rooms, not symbols.
    """
    out: list[tuple[_Primitive, Point, float, float, float]] = []
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
        out.append((prim, ((x0 + x1) / 2.0, (y0 + y1) / 2.0), w, h, diag))
    return out


def find_similar_symbols(
    drawings: list[Any],
    seed_x: float,
    seed_y: float,
    *,
    max_hits: int = _MAX_SIMILAR,
) -> dict[str, Any]:
    """Find every symbol matching the one under ``(seed_x, seed_y)`` on a page.

    The seed is the small closed shape whose centroid is nearest the click; its
    ``(round(w / 4), round(h / 4))`` signature and vertex count select the
    matches (within +/-25% of the seed's size). Hits are de-duplicated by
    centroid proximity and scored by how closely they match the seed's size.

    Pure and DB-free: ``drawings`` is the already-extracted
    ``PdfPage.drawings()`` output. Returns ``{"hits", "seed_found", "note"}``
    where ``note`` is ``"no_vector_layer"`` (page has no drawing layer, e.g. a
    scan), ``"no_symbol_at_point"`` (nothing small enough under the click) or
    ``None``. Each hit is ``{x, y, bbox_x0..y1, confidence, is_seed}`` in PDF
    points - the same space the canvas stores measurements in.
    """
    prims = primitives_from_drawings(drawings)
    symbols = _symbol_primitives(prims)
    if not symbols:
        return {
            "hits": [],
            "seed_found": False,
            "note": "no_symbol_at_point" if prims else "no_vector_layer",
        }

    # Locate the seed: the symbol nearest the click within a size-aware radius.
    best: tuple[float, tuple[_Primitive, Point, float, float, float]] | None = None
    for entry in symbols:
        cx, cy = entry[1]
        diag = entry[4]
        dist = math.hypot(cx - seed_x, cy - seed_y)
        if dist <= max(_SEED_PICK_TOL_PX, diag) and (best is None or dist < best[0]):
            best = (dist, entry)
    if best is None:
        return {"hits": [], "seed_found": False, "note": "no_symbol_at_point"}

    seed_entry = best[1]
    s_cx, s_cy = seed_entry[1]
    s_w, s_h, s_diag = seed_entry[2], seed_entry[3], seed_entry[4]
    seed_sig = (round(s_w / 4), round(s_h / 4))
    seed_verts = len(seed_entry[0].points)

    scored: list[tuple[Point, tuple[float, float, float, float], float]] = []
    for entry in symbols:
        prim, (cx, cy), w, h, diag = entry
        if s_diag > 0 and (diag < s_diag * 0.75 or diag > s_diag * 1.25):
            continue
        sig = (round(w / 4), round(h / 4))
        if abs(sig[0] - seed_sig[0]) > 1 or abs(sig[1] - seed_sig[1]) > 1:
            continue
        if abs(len(prim.points) - seed_verts) > 2:
            continue
        spread = abs(diag - s_diag) / (s_diag or 1.0)
        confidence = round(max(0.5, min(0.92, 0.92 - spread * 0.4)), 2)
        scored.append(((cx, cy), _bbox(prim.points), confidence))

    # Non-maximum suppression: drop a hit that overlaps a higher-scored one.
    scored.sort(key=lambda s: s[2], reverse=True)
    kept: list[tuple[Point, tuple[float, float, float, float], float]] = []
    for centroid, bbox, confidence in scored:
        if any(math.hypot(centroid[0] - k[0][0], centroid[1] - k[0][1]) <= _HIT_NMS_PX for k in kept):
            continue
        kept.append((centroid, bbox, confidence))
        if len(kept) >= max_hits:
            break

    hits = [
        {
            "x": centroid[0],
            "y": centroid[1],
            "bbox_x0": bbox[0],
            "bbox_y0": bbox[1],
            "bbox_x1": bbox[2],
            "bbox_y1": bbox[3],
            "confidence": confidence,
            "is_seed": math.hypot(centroid[0] - s_cx, centroid[1] - s_cy) <= _HIT_NMS_PX,
        }
        for centroid, bbox, confidence in kept
    ]
    return {"hits": hits, "seed_found": any(h["is_seed"] for h in hits), "note": None}
