# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Floor-plan reading of a PDF page's vector layer: rooms, walls and symbols.

A CAD sheet draws a wall as two parallel face lines (sometimes with a fill or
hatching between them) or as a filled band. This module finds those walls,
paints them into a wall mask in a frame aligned with the drawing, and lets
:mod:`app.modules.takeoff.floorplan` read rooms and wall runs from it. Room
outlines are then snapped back onto the exact vector face lines, so a room
drawn in CAD measures to the CAD geometry rather than to the raster.

Steps:

1. Parse ``PdfPage.drawings()`` into straight strokes, curves and fills.
   Dashed strokes (grid axes, hidden lines) and light strokes are not walls;
   hatching, even runs of many parallels, goes before anything is measured on it.
2. Find the dominant drawing angle and work in a frame rotated by it.
3. Pair parallel strokes: the length-weighted distances between nearest
   overlapping parallel strokes peak at the wall thicknesses of the sheet; a
   pair at one of those distances is a wall band.
4. Paint bands and dark fills (light fills erase, in paint order), drop small
   isolated blobs (columns, arrowheads), bridge door and window gaps, and read
   rooms and wall runs.
5. Symbols: the strokes, curves and small fills that are not walls are grouped
   into connected instances inside the building; instances with the same
   rotation-invariant shape signature form a count.

Pure: no I/O, no database. Coordinates in and out are PDF points, top-left
origin, the same space ``drawings()`` uses.
"""

from __future__ import annotations

import bisect
import heapq
import math
import time
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from app.modules.takeoff import floorplan as fp

Point = tuple[float, float]

_PX_BUDGET = 2_500_000  # wall-mask pixels; keeps the peak near 60 MB on any sheet
_MAX_PX_PER_PT = 3.0
_AXIS_TOL_DEG = 1.0
# Widest ordinary opening in a wall: a double door or a strip window. Without a
# scale it follows the wall thickness, taking a 0.25 m wall.
_MAX_OPENING_M = 3.0
_MAX_OPENING_WALLS = 12.0
_MIN_PASSAGE_M = 0.2
# A stroke faces few others across a wall. Beyond this many it is in a pattern or
# lettering, and the nearest of them are all a wall could be.
_MAX_PARTNERS = 64
# Single-line drawings: strokes shorter than this do not enclose anything a person stands in.
_LINE_WALL_MIN_M = 0.6
_LINE_WALL_MIN_PT = 14.0
_LINE_WALL_MIN_STROKES = 60
# What a floor plan's rooms do and a page of windows or table cells does not.
_MIN_COVERAGE = 0.3
_MIN_JOINED = 0.5
_MAX_CROSSINGS = 0.5


class TimeBudgetExceeded(Exception):
    """A page took longer to read than the caller allowed."""


class Budget:
    """A wall-clock allowance for reading one page; ``None`` seconds never runs out."""

    def __init__(self, seconds: float | None = None) -> None:
        self.deadline = time.perf_counter() + seconds if seconds else math.inf

    def check(self) -> None:
        if time.perf_counter() > self.deadline:
            raise TimeBudgetExceeded


@dataclass
class Seg:
    a: Point
    b: Point
    lw: float
    seq: int


@dataclass
class Fill:
    pts: list[Point]
    lum: float
    seq: int


@dataclass
class Curve:
    pts: list[Point]  # flattened
    seq: int


@dataclass
class PlanResult:
    """Rooms, walls and symbol groups found on one page (page points)."""

    rooms: list[dict[str, Any]] = field(default_factory=list)
    walls: list[dict[str, Any]] = field(default_factory=list)
    counts: list[dict[str, Any]] = field(default_factory=list)
    wall_modes_pt: list[float] = field(default_factory=list)
    found_structure: bool = False
    out_of_time: bool = False  # rooms and walls may be there, later stages were skipped


# ── parsing ──────────────────────────────────────────────────────────────────


def _xy(obj: Any) -> Point | None:
    try:
        if hasattr(obj, "x") and hasattr(obj, "y"):
            return (float(obj.x), float(obj.y))
        if isinstance(obj, (list, tuple)) and len(obj) >= 2:
            return (float(obj[0]), float(obj[1]))
    except (TypeError, ValueError):
        return None
    return None


def _lum(color: Any) -> float:
    if not color:
        return 0.0
    try:
        c = [float(v) for v in color]
    except (TypeError, ValueError):
        return 0.0
    if len(c) == 1:
        return c[0]
    if len(c) == 3:
        return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
    if len(c) == 4:  # CMYK
        k = c[3]
        return 0.299 * (1 - c[0]) * (1 - k) + 0.587 * (1 - c[1]) * (1 - k) + 0.114 * (1 - c[2]) * (1 - k)
    return 0.0


def _dashed(dashes: Any) -> bool:
    if not dashes:
        return False
    if isinstance(dashes, str):
        inner = dashes[dashes.find("[") + 1 : dashes.find("]")] if "[" in dashes else ""
        return any(ch.isdigit() and ch != "0" for ch in inner)
    if isinstance(dashes, (list, tuple)):
        first = dashes[0] if dashes else None
        return bool(first) if isinstance(first, (list, tuple)) else any(bool(v) for v in dashes)
    return False


def _bezier(p0: Point, p1: Point, p2: Point, p3: Point, n: int = 8) -> list[Point]:
    out = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        a, b, c, d = mt * mt * mt, 3 * mt * mt * t, 3 * mt * t * t, t * t * t
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def _in_poly(p: Point, poly: list[Point]) -> bool:
    x, y = p
    hit = False
    x1, y1 = poly[-1]
    for x2, y2 in poly:
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
        x1, y1 = x2, y2
    return hit


def _clip_line(a: Point, b: Point, poly: list[Point]) -> list[tuple[Point, Point]]:
    """The stretches of a straight stroke that lie inside a clip polygon."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    cuts = [0.0, 1.0]
    x1, y1 = poly[-1]
    for x2, y2 in poly:
        ex, ey = x2 - x1, y2 - y1
        den = dx * ey - dy * ex
        if abs(den) > 1e-12:
            t = ((x1 - a[0]) * ey - (y1 - a[1]) * ex) / den
            u = ((x1 - a[0]) * dy - (y1 - a[1]) * dx) / den
            if 0.0 < t < 1.0 and -1e-9 <= u <= 1.0 + 1e-9:
                cuts.append(t)
        x1, y1 = x2, y2
    cuts.sort()
    out: list[tuple[Point, Point]] = []
    for t0, t1 in zip(cuts, cuts[1:], strict=False):
        if t1 - t0 < 1e-6:
            continue
        tm = 0.5 * (t0 + t1)
        if _in_poly((a[0] + tm * dx, a[1] + tm * dy), poly):
            p, q = (a[0] + t0 * dx, a[1] + t0 * dy), (a[0] + t1 * dx, a[1] + t1 * dy)
            if out and math.dist(out[-1][1], p) < 1e-6:
                out[-1] = (out[-1][0], q)
            else:
                out.append((p, q))
    return out


def _clip_seg(a: Point, b: Point, clips: list[list[Point]]) -> list[tuple[Point, Point]]:
    parts = [(a, b)]
    for poly in clips:
        parts = [piece for p, q in parts for piece in _clip_line(p, q, poly)]
    return parts


def _clip_fill(pts: list[Point], clips: list[list[Point]]) -> list[Point] | None:
    """A fill polygon cut by its clip (Sutherland-Hodgman); a concave clip keeps its bounding box."""
    out = pts
    for poly in clips:
        x0, y0, x1, y1 = _bbox(poly)
        bx0, by0, bx1, by1 = _bbox(out)
        if bx1 <= x0 or bx0 >= x1 or by1 <= y0 or by0 >= y1:
            return None
        if bx0 >= x0 and by0 >= y0 and bx1 <= x1 and by1 <= y1:
            continue
        for axis, lim, keep_low in ((0, x0, False), (0, x1, True), (1, y0, False), (1, y1, True)):
            kept: list[Point] = []
            prev = out[-1]
            for cur in out:
                pin = prev[axis] <= lim if keep_low else prev[axis] >= lim
                cin = cur[axis] <= lim if keep_low else cur[axis] >= lim
                if pin != cin:
                    t = (lim - prev[axis]) / (cur[axis] - prev[axis])
                    kept.append((prev[0] + t * (cur[0] - prev[0]), prev[1] + t * (cur[1] - prev[1])))
                if cin:
                    kept.append(cur)
                prev = cur
            out = kept
            if len(out) < 3:
                return None
    return out


def parse(
    drawings: list[Any], page_size: tuple[float, float] | None = None
) -> tuple[list[Seg], list[Fill], list[Curve]]:
    """Straight strokes, flattened curves and fill polygons of a page, as they show.

    Clip paths are applied and anything off the page is dropped: what is clipped
    away is not on the drawing, however much of the file it takes up.
    """
    segs: list[Seg] = []
    fills: list[Fill] = []
    curves: list[Curve] = []
    page = [(0.0, 0.0), (page_size[0], 0.0), (page_size[0], page_size[1]), (0.0, page_size[1])] if page_size else None
    for idx, path in enumerate(drawings or []):
        if not isinstance(path, dict):
            continue
        clips: list[list[Point]] = list(path.get("clip") or [])
        if page is not None:
            clips.append(page)
        n_segs, n_curves = len(segs), len(curves)
        items = path.get("items") or []
        typ = str(path.get("type") or "s")
        seq = int(path.get("seqno", idx) or idx)
        stroked = "s" in typ and not _dashed(path.get("dashes")) and _lum(path.get("color")) < 0.8
        filled = "f" in typ
        lw = float(path.get("width") or 0.0)
        polys: list[list[Point]] = []
        cur: list[Point] = []

        def flush() -> None:
            nonlocal cur
            if len(cur) >= 3:
                polys.append(cur)
            cur = []

        for it in items:
            if not it:
                continue
            op = it[0]
            if op in ("re", "qu"):
                flush()
                pts = _quad_points(it[1], op)
                if pts:
                    polys.append(pts)
                    if stroked:
                        segs.extend(Seg(pts[i], pts[(i + 1) % 4], lw, seq) for i in range(4))
            elif op in ("l", "c"):
                pts = [p for p in (_xy(x) for x in it[1:]) if p is not None]
                if len(pts) < 2:
                    continue
                a = pts[0]
                if not cur or abs(cur[-1][0] - a[0]) > 1e-3 or abs(cur[-1][1] - a[1]) > 1e-3:
                    flush()
                    cur = [a]
                if op == "l":
                    cur.append(pts[-1])
                    if stroked:
                        segs.append(Seg(a, pts[-1], lw, seq))
                elif len(pts) == 4:
                    flat = _bezier(*pts)
                    cur.extend(flat[1:])
                    if stroked:
                        curves.append(Curve(flat, seq))
        flush()
        if clips:
            segs[n_segs:] = [Seg(p, q, sg.lw, sg.seq) for sg in segs[n_segs:] for p, q in _clip_seg(sg.a, sg.b, clips)]
            curves[n_curves:] = [
                cv_ for cv_ in curves[n_curves:] if all(_in_poly(cv_.pts[len(cv_.pts) // 2], poly) for poly in clips)
            ]
        if filled:
            flum = _lum(path.get("fill"))
            for p in polys:
                ring = _clip_fill(_open_ring(p), clips) if clips else _open_ring(p)
                if ring:
                    fills.append(Fill(ring, flum, seq))
    return segs, fills, curves


def _quad_points(obj: Any, op: str) -> list[Point] | None:
    try:
        if op == "re":
            x0, y0, x1, y1 = (float(obj.x0), float(obj.y0), float(obj.x1), float(obj.y1))
            return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        pts = [_xy(obj.ul), _xy(obj.ll), _xy(obj.lr), _xy(obj.ur)]
        return [p for p in pts if p is not None] if all(pts) else None
    except (AttributeError, TypeError, ValueError):
        return None


# ── hatching ─────────────────────────────────────────────────────────────────

# Runs of this many evenly spaced parallels are a pattern. A wall drawn in layers
# has at most four or five faces, and stair flights lose nothing by going.
_HATCH_MIN_RUN = 6
# Pattern pitch on paper. Coarser is a floor grid or a row of party walls, told apart
# from walls only by scale, so with a scale the limit follows building dimensions.
_HATCH_MAX_PITCH_PT = 14.0
_HATCH_MAX_PITCH_M = 0.45
_HATCH_PITCH_TOL = 0.2


def drop_hatching(segs: list[Seg], pt_per_m: float | None = None) -> list[Seg]:
    """Strokes without the hatching: families of evenly spaced parallels, at any angle."""
    bins: dict[int, list[int]] = {}
    for i, sg in enumerate(segs):
        dx, dy = sg.b[0] - sg.a[0], sg.b[1] - sg.a[1]
        if dx * dx + dy * dy < 0.25:
            continue
        bins.setdefault(round(math.degrees(math.atan2(dy, dx)) % 180.0) % 180, []).append(i)
    pitch_max = max(_HATCH_MAX_PITCH_PT, _HATCH_MAX_PITCH_M * pt_per_m) if pt_per_m else _HATCH_MAX_PITCH_PT
    hatch: set[int] = set()
    for key, members in bins.items():
        if len(members) < _HATCH_MIN_RUN:
            continue
        for shift in (0.0, 1.0):  # a family sitting on a bin edge splits in two; nearby bins share it
            pool = members + bins.get((key + 1) % 180, []) if shift else members
            hatch.update(_hatch_runs(segs, pool, math.radians(key + 0.5 * shift), pitch_max))
    if not hatch:
        return segs
    return [sg for i, sg in enumerate(segs) if i not in hatch]


def _hatch_runs(segs: list[Seg], members: list[int], ang: float, pitch_max: float) -> list[int]:
    ca, sa = math.cos(ang), math.sin(ang)
    rows = []
    for i in members:
        (x1, y1), (x2, y2) = segs[i].a, segs[i].b
        s1, s2 = x1 * ca + y1 * sa, x2 * ca + y2 * sa
        rows.append((0.5 * ((-x1 * sa + y1 * ca) + (-x2 * sa + y2 * ca)), min(s1, s2), max(s1, s2), i))
    rows.sort()
    n = len(rows)
    # successor: the nearest stroke further across that faces this one along the run
    nxt = [-1] * n
    gap = [0.0] * n
    for a in range(n):
        ca_, lo, hi, _i = rows[a]
        slack = max(1.0, 0.5 * (hi - lo))
        for b in range(a + 1, min(n, a + 40)):
            cb, lo2, hi2, _j = rows[b]
            d = cb - ca_
            if d > pitch_max:
                break
            if d < 0.05 or min(hi, hi2) - max(lo, lo2) < -slack:
                continue
            nxt[a], gap[a] = b, d
            break
    # chains of steady gaps, walked from every stroke nobody points at
    pointed = {b for b in nxt if b >= 0}
    out: list[int] = []
    for start in range(n):
        if start in pointed or nxt[start] < 0:
            continue
        run = [start]
        cur = start
        ref = gap[start]
        while nxt[cur] >= 0:
            g = gap[cur]
            if abs(g - ref) <= _HATCH_PITCH_TOL * ref + 0.05:
                run.append(nxt[cur])
                ref = 0.8 * ref + 0.2 * g
                cur = nxt[cur]
                continue
            if len(run) >= _HATCH_MIN_RUN:
                out.extend(rows[x][3] for x in run)
            run = [cur, nxt[cur]]
            ref = g
            cur = nxt[cur]
        if len(run) >= _HATCH_MIN_RUN:
            out.extend(rows[x][3] for x in run)
    return out


# ── frame ────────────────────────────────────────────────────────────────────


def _open_ring(pts: list[Point]) -> list[Point]:
    """Drop a closing point that repeats the first one."""
    if len(pts) > 3 and math.dist(pts[0], pts[-1]) < 1e-3:
        return pts[:-1]
    return pts


def candidate_angles(segs: list[Seg], fills: list[Fill]) -> list[float]:
    """Up to three drawing angles in radians (-45..45 deg], strongest first.

    Peaks of a squared-length-weighted histogram of stroke and fill-edge angles mod 90.
    """
    bins = np.zeros(360)
    edges: list[tuple[Point, Point]] = [(s.a, s.b) for s in segs]
    for f in fills:
        edges.extend((f.pts[i], f.pts[(i + 1) % len(f.pts)]) for i in range(len(f.pts)))
    xs = [p[0] for e in edges for p in e] or [0.0]
    ys = [p[1] for e in edges for p in e] or [0.0]
    # The sheet frame is axis-aligned whatever the building does; leave it out.
    frame_len = 0.35 * math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    angs, wts = [], []
    for a, b in edges:
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy)
        if ln < 4.0 or ln > frame_len:
            continue
        angs.append(math.degrees(math.atan2(dy, dx)) % 90.0)
        wts.append(ln * ln)  # long strokes (walls) outweigh dense short ones (hatching)
    if not angs:
        return [0.0]
    ang = np.array(angs)
    wt = np.array(wts)
    np.add.at(bins, (ang * 4).astype(int) % 360, wt)
    smooth = bins + np.roll(bins, 1) + np.roll(bins, -1)
    out: list[float] = []
    first = float(smooth.max())
    for _ in range(3):
        top = int(np.argmax(smooth))
        if smooth[top] <= 0.03 * first:
            break
        peak = (top + 0.5) / 4.0
        diff = (ang - peak + 45.0) % 90.0 - 45.0
        sel = np.abs(diff) <= 0.6
        theta = peak + float(np.average(diff[sel], weights=wt[sel])) if sel.any() else peak
        theta = (theta + 45.0) % 90.0 - 45.0
        out.append(0.0 if abs(theta) < 0.02 else math.radians(theta))
        # suppress two degrees either side before looking for the next direction
        for d in range(-8, 9):
            smooth[(top + d) % 360] = 0.0
    return out


def dominant_angle(segs: list[Seg], fills: list[Fill]) -> float:
    """Drawing angle in radians (-45..45 deg], the strongest direction of the angle histogram."""
    return candidate_angles(segs, fills)[0]


class Frame:
    """Page points <-> work-frame pixels (rotated by the drawing angle, scaled, cropped)."""

    def __init__(self, theta: float, u0: float = 0.0, v0: float = 0.0, s: float = 1.0) -> None:
        self.cos, self.sin = math.cos(theta), math.sin(theta)
        self.u0, self.v0, self.s = u0, v0, s

    def work(self, p: Point) -> Point:
        return (p[0] * self.cos + p[1] * self.sin, -p[0] * self.sin + p[1] * self.cos)

    def page(self, w: Point) -> Point:
        return (w[0] * self.cos - w[1] * self.sin, w[0] * self.sin + w[1] * self.cos)

    def px(self, w: Point) -> Point:
        return ((w[0] - self.u0) * self.s, (w[1] - self.v0) * self.s)

    def from_px(self, q: Point) -> Point:
        return self.page((q[0] / self.s + self.u0, q[1] / self.s + self.v0))


# ── wall-face pairing ────────────────────────────────────────────────────────


@dataclass
class _Line1D:
    c: float
    lo: float
    hi: float
    idx: int


def _groups(wsegs: list[tuple[Point, Point]]) -> list[tuple[float, list[_Line1D]]]:
    """Group work-frame segments by direction; each group in its own along/across frame.

    The first two groups are the work axes (within one degree). Other
    directions go into one-degree bins and only strokes of at least 6 pt count
    there, so hatching and lettering do not flood the pairing.
    """
    bins: dict[int, list[int]] = {0: [], 90: []}
    for i, (a, b) in enumerate(wsegs):
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy)
        if ln < 0.5:
            continue
        ang = math.degrees(math.atan2(dy, dx)) % 180.0
        # a short stroke on a rotated sheet carries coordinate rounding as angle error
        tol = max(_AXIS_TOL_DEG, min(6.0, math.degrees(math.atan(0.3 / ln))))
        if min(ang, 180.0 - ang) <= tol:
            bins[0].append(i)
        elif abs(ang - 90.0) <= tol:
            bins[90].append(i)
        elif ln >= 6.0:
            bins.setdefault(round(ang) % 180 or 180, []).append(i)
    out = []
    for key, members in bins.items():
        ang = math.radians(0.0 if key == 180 else float(key))
        ca, sa = math.cos(ang), math.sin(ang)
        lines = []
        for i in members:
            (x1, y1), (x2, y2) = wsegs[i]
            s1, s2 = x1 * ca + y1 * sa, x2 * ca + y2 * sa
            c = 0.5 * ((-x1 * sa + y1 * ca) + (-x2 * sa + y2 * ca))
            lines.append(_Line1D(c, min(s1, s2), max(s1, s2), i))
        lines.sort(key=lambda ln: ln.c)
        out.append((ang, lines))
    return out


def _candidate_pairs(
    lines: list[_Line1D], dmax: float, budget: Budget | None = None
) -> list[tuple[int, int, float, float]]:
    """Parallel strokes up to ``dmax`` apart that overlap along their direction, ``lines`` sorted by c.

    Strokes sit in cells along the direction and only strokes sharing a cell are compared,
    so a dense sheet costs what it holds rather than the square of it.
    """
    n = len(lines)
    if n < 2:
        return []
    lo_all = min(ln.lo for ln in lines)
    hi_all = max(ln.hi for ln in lines)
    size = max(dmax, (hi_all - lo_all) / 512.0, 1.0)
    cells: dict[int, list[int]] = {}
    for i, ln in enumerate(lines):
        for cell in range(int((ln.lo - lo_all) // size), int((ln.hi - lo_all) // size) + 1):
            cells.setdefault(cell, []).append(i)
    out: list[tuple[int, int, float, float]] = []
    for i, a in enumerate(lines):
        if budget is not None and i % 512 == 0:
            budget.check()
        first_a = int((a.lo - lo_all) // size)
        found: list[tuple[float, int, float]] = []
        for cell in range(first_a, int((a.hi - lo_all) // size) + 1):
            members = cells[cell]
            scanned = 0
            for pos in range(bisect.bisect_right(members, i), len(members)):
                j = members[pos]
                b = lines[j]
                d = b.c - a.c
                if d > dmax or scanned >= 4 * _MAX_PARTNERS:
                    break
                scanned += 1
                if d < 0.35 or max(first_a, int((b.lo - lo_all) // size)) != cell:
                    continue  # a pair is seen once, in the first cell the two share
                ov = min(a.hi, b.hi) - max(a.lo, b.lo)
                if ov > 0.5:
                    found.append((d, j, ov))
        if len(found) > _MAX_PARTNERS:
            found = heapq.nsmallest(_MAX_PARTNERS, found)
        out.extend((i, j, d, ov) for d, j, ov in found)
    return out


def wall_modes(groups: list[tuple[float, list[_Line1D]]], dmax: float, budget: Budget | None = None) -> list[float]:
    """Wall thicknesses: peaks of the distances from each stroke to its nearest parallel.

    Each stretch of a stroke counts once, at the distance of the nearest stroke
    facing it there, so a face that runs past a window sill still votes for the
    wall thickness along the rest of its length.
    """
    ds, ws = [], []
    for _ang, lines in groups[:2]:
        near: dict[int, list[tuple[float, float, float]]] = {}
        for i, j, d, _ov in _candidate_pairs(lines, dmax, budget):
            lo, hi = max(lines[i].lo, lines[j].lo), min(lines[i].hi, lines[j].hi)
            near.setdefault(i, []).append((d, lo, hi))
            near.setdefault(j, []).append((d, lo, hi))
        for cands in near.values():
            taken: list[tuple[float, float]] = []
            for d, lo, hi in sorted(cands):
                free = (hi - lo) - sum(max(0.0, min(hi, t1) - max(lo, t0)) for t0, t1 in taken)
                taken.append((lo, hi))
                if free >= max(2.0 * d, 3.0):
                    ds.append(math.log(d))
                    ws.append(free)
    return _peaks(ds, ws, math.log(0.4), math.log(dmax))


def _in_modes(d: float, modes: list[float]) -> bool:
    return any(abs(d - m) <= max(0.35, 0.08 * m) for m in modes)


def wall_pairs(
    groups: list[tuple[float, list[_Line1D]]], modes: list[float], dmax: float, budget: Budget | None = None
) -> list[tuple[list[Point], int, int]]:
    """Wall bands as work-frame quads, with the indices of the two strokes bounding each.

    Pairs are taken nearest first over the whole group. A stroke is the face of one
    wall, so a stretch already paired is not paired again on either side; this keeps
    the gap between an outer face and its dimension line out of the walls.
    """
    out: list[tuple[list[Point], int, int]] = []
    for ang, lines in groups:
        ca, sa = math.cos(ang), math.sin(ang)
        cands = sorted(
            (d, i, j)
            for i, j, d, ov in _candidate_pairs(lines, dmax, budget)
            if _in_modes(d, modes) and ov >= max(0.8, 0.25 * d)
        )
        taken: dict[int, list[tuple[float, float]]] = {}
        for d, i, j in cands:
            a, b = lines[i], lines[j]
            lo, hi = max(a.lo, b.lo), min(a.hi, b.hi)
            if any(
                sum(max(0.0, min(hi, t1) - max(lo, t0)) for t0, t1 in taken.get(x, ())) > 0.5 * (hi - lo)
                for x in (i, j)
            ):
                continue
            taken.setdefault(i, []).append((lo, hi))
            taken.setdefault(j, []).append((lo, hi))
            quad = [(lo, a.c), (hi, a.c), (hi, b.c), (lo, b.c)]
            out.append(([(u * ca - c * sa, u * sa + c * ca) for u, c in quad], a.idx, b.idx))
    return out


def _supported_modes(modes: list[float], pairs: list[tuple[list[Point], int, int]]) -> list[float]:
    """Modes that still carry at least a tenth of the paired wall length."""
    if not pairs:
        return modes
    length = dict.fromkeys(range(len(modes)), 0.0)
    for q, _i, _j in pairs:
        d = math.dist(q[1], q[2])
        m = min(range(len(modes)), key=lambda x: abs(modes[x] - d))
        length[m] += math.dist(q[0], q[1])
    top = max(length.values())
    return [m for x, m in enumerate(modes) if length[x] >= 0.1 * top]


# ── the page reader ──────────────────────────────────────────────────────────


def _fill_area(pts: list[Point]) -> float:
    return fp.polygon_area(list(pts))


def _bbox(pts: list[Point]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


@dataclass
class _Setup:
    fr: Frame
    wsegs: list[tuple[Point, Point]]
    wfills: list[tuple[list[Point], float, int]]
    modes: list[float]
    pairs: list[tuple[list[Point], int, int]]
    dark: list[tuple[list[Point], int]]
    light: list[tuple[list[Point], int]]
    evidence: float


def _setup(segs: list[Seg], fills: list[Fill], theta: float, dmax: float, budget: Budget | None = None) -> _Setup:
    """Work frame at ``theta`` with its wall pairs, fills and how much wall they show."""
    fr = Frame(theta)
    wsegs = [(fr.work(sg.a), fr.work(sg.b)) for sg in segs]
    wfills = [([fr.work(p) for p in f.pts], f.lum, f.seq) for f in fills]
    groups = _groups(wsegs)
    modes = wall_modes(groups, dmax, budget)
    pairs = wall_pairs(groups, modes, dmax, budget) if modes else []
    modes = _supported_modes(modes, pairs)
    xs = [p[0] for f in wfills for p in f[0]] + [p[0] for sg in wsegs for p in sg] or [0.0]
    ys = [p[1] for f in wfills for p in f[0]] + [p[1] for sg in wsegs for p in sg] or [0.0]
    page_area = max(1.0, (max(xs) - min(xs)) * (max(ys) - min(ys)))
    dark = [(pts, seq) for pts, lum, seq in wfills if lum < 0.9 and _fill_area(pts) < 0.6 * page_area]
    light = [(pts, seq) for pts, lum, seq in wfills if lum >= 0.95]
    # squared lengths: a wall is long, hatching and lettering are many short strokes
    evidence = sum(max(math.dist(q[0], q[1]), math.dist(q[1], q[2])) ** 2 for q, _i, _j in pairs)
    for pts, _s in dark:
        if len(pts) == 4:
            dx, dy = pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]
            ang = math.degrees(math.atan2(dy, dx)) % 90.0
            if min(ang, 90.0 - ang) <= _AXIS_TOL_DEG:
                evidence += max(math.dist(pts[0], pts[1]), math.dist(pts[1], pts[2])) ** 2
    return _Setup(fr, wsegs, wfills, modes, pairs, dark, light, evidence)


def _cv(pts: list[Point]) -> np.ndarray:
    """Pixel-edge coordinates -> OpenCV fixed-point (shift 4) polygon."""
    return np.round((np.asarray(pts, dtype=np.float64) - 0.5) * 16).astype(np.int32)


def read_plan(
    drawings: list[Any],
    pt_per_m: float | None = None,
    *,
    page_size: tuple[float, float] | None = None,
    budget: Budget | None = None,
) -> PlanResult:
    """Rooms, wall runs and symbol counts of one vector page."""
    segs, fills, curves = parse(drawings, page_size)
    return read_parts(segs, fills, curves, pt_per_m, budget=budget)


def read_parts(
    segs: list[Seg],
    fills: list[Fill],
    curves: list[Curve],
    pt_per_m: float | None = None,
    *,
    budget: Budget | None = None,
) -> PlanResult:
    """Rooms, wall runs and symbol counts from strokes, fills and arcs in page points."""
    res = PlanResult()
    if not segs and not fills:
        return res
    k = pt_per_m if pt_per_m and pt_per_m > 0 else None
    segs = drop_hatching(segs, k)
    if budget is not None:
        budget.check()
    # Wider than any wall (0.55 m) is furniture, a counter or a dimension offset.
    dmax = min(45.0, 0.55 * k) if k else 45.0
    # A small rotated building can lose the angle vote to an upright title block;
    # the frame that finds the most wall evidence wins.
    best: _Setup | None = None
    for theta in candidate_angles(segs, fills):
        su = _setup(segs, fills, theta, dmax, budget)
        if best is None or su.evidence > best.evidence:
            best = su
    if best is None:
        return res
    fr, wsegs, wfills, modes, pairs, dark, light = (
        best.fr,
        best.wsegs,
        best.wfills,
        best.modes,
        best.pairs,
        best.dark,
        best.light,
    )
    res.wall_modes_pt = modes
    if not pairs and not dark:
        # A few outlines are a sketch, which the shape detectors measure exactly.
        pairs, modes = _line_walls(wsegs, segs, k) if len(segs) > _LINE_WALL_MIN_STROKES else ([], [])
        res.wall_modes_pt = modes
        if not pairs:
            return res
    box = _main_box([q for q, _i, _j in pairs] + [pts for pts, _s in dark], 2.5 * k if k else 60.0)
    if box is None:
        return res
    t_pt = modes
    fmodes = _fill_modes(dark)
    if fmodes:
        # Poche walls: when filled bands outweigh stroked pairs, the strokes that
        # did pair are window sills and frames, not walls.
        fill_len = sum(max(math.dist(p[0], p[1]), math.dist(p[1], p[2])) for p, _s in dark if len(p) == 4)
        pair_len = sum(max(math.dist(q[0], q[1]), math.dist(q[1], q[2])) for q, _i, _j in pairs)
        if fill_len > pair_len:
            t_pt = fmodes
            res.wall_modes_pt = fmodes
            pairs = [pr for pr in pairs if _in_modes(math.dist(pr[0][1], pr[0][2]), fmodes)]
    u0, v0, u1, v1 = box
    s = math.sqrt(_PX_BUDGET / max(1.0, (u1 - u0) * (v1 - v0)))
    if t_pt:
        s = min(s, max(1.0, 5.0 / min(t_pt)))
    fr.u0, fr.v0, fr.s = u0, v0, min(_MAX_PX_PER_PT, s)
    shape = (int((v1 - v0) * fr.s) + 2, int((u1 - u0) * fr.s) + 2)
    chords = [(fr.work(a), fr.work(b)) for a, b in door_chords(segs, curves, k)]
    if budget is not None:
        budget.check()
    rp = _rooms_pass(shape, fr, pairs, dark, light, wsegs, t_pt, k, chords)
    if rp is None:
        return res
    if pairs:
        # Bands that border no room are dimension offsets or details beside the plan,
        # unless taking them out loses rooms: then they were walls of unclosed rooms.
        keep = [pr for pr in pairs if _borders_room(pr[0], fr, rp.room_lab)]
        if len(keep) < len(pairs):
            again = _rooms_pass(shape, fr, keep, dark, light, wsegs, t_pt, k, chords)
            if again is not None and sum(r.area_px for r in again.rooms) >= sum(r.area_px for r in rp.rooms):
                pairs, rp = keep, again
    res.found_structure = True
    t_min = min(rp.t_px)
    faces = _faces(wsegs, wfills, fr)
    neighbours = _room_neighbours(rp.room_lab, len(rp.rooms), max(rp.t_px))
    for n_room, r in enumerate(rp.rooms):
        poly, snapped = _room_polygon(r, faces, t_min)
        if len(poly) < 3:
            continue
        x, y, bw, bh = cv2.boundingRect(r.contour)
        res.rooms.append(
            {
                "points": [fr.from_px(p) for p in poly],
                "snapped": snapped,
                "vertices": len(poly),
                "fill_ratio": r.area_px / max(1.0, r.filled_px),
                "closure": _closure(r, rp.raw),
                "box_px": (x, y, x + bw, y + bh),
                "rectangularity": r.filled_px / max(1.0, float(bw * bh)),
                "aspect": max(bw, bh) / max(1.0, float(min(bw, bh))),
                "neighbours": neighbours[n_room],
                "tol_px": max(rp.t_px) + 2.0,
            }
        )
    bands = fp.axis_bands(rp.mask, min_len_px=max(4.0, 1.5 * t_min))
    runs = fp.wall_runs(rp.mask, bands, rp.room_lab, min_len_px=(0.3 * k * fr.s) if k else 4 * t_min)
    for wr in runs:
        if wr.support < 0.3 or not any(abs(wr.t - m) <= max(1.5, 0.25 * m) for m in rp.t_px):
            continue
        a, b = ((wr.lo, wr.c), (wr.hi, wr.c)) if wr.axis == "h" else ((wr.c, wr.lo), (wr.c, wr.hi))
        res.walls.append(
            {
                "points": [fr.from_px(a), fr.from_px(b)],
                "thickness_pt": wr.t / fr.s,
                "support": wr.support,
                "joined": wr.ends_joined,
            }
        )
    used = {i for _q, a, b in pairs for i in (a, b)}
    try:
        if budget is not None:
            budget.check()
        res.counts = _symbols(segs, curves, fills, used, fr, rp.mask, rp.room_lab, k, max(rp.t_px) / fr.s, budget)
    except TimeBudgetExceeded:
        res.out_of_time = True
    return res


def looks_like_rooms(plan: PlanResult) -> bool:
    """Whether what was read has the shape of a floor plan, without any text to go on.

    Rooms of a plan share walls and cover their building. Windows of an elevation stand
    apart with wall between them, and the cells of a table meet four at a time at every
    crossing, which walls of a building hardly ever do.
    """
    rooms = plan.rooms
    if not rooms:
        return False
    if len(rooms) < 3:
        return True
    boxes = [r["box_px"] for r in rooms]
    extent = (
        (max(b[2] for b in boxes) - min(b[0] for b in boxes)) * (max(b[3] for b in boxes) - min(b[1] for b in boxes))
    ) or 1
    covered = sum((b[2] - b[0]) * (b[3] - b[1]) for b in boxes)
    joined = sum(1 for r in rooms if r["neighbours"]) / len(rooms)
    return covered / extent >= _MIN_COVERAGE and joined >= _MIN_JOINED and _crossing_share(rooms) < _MAX_CROSSINGS


def _crossing_share(rooms: list[dict[str, Any]]) -> float:
    """Share of the corners shared between rooms where four rooms meet."""
    tol = max(r["tol_px"] for r in rooms)
    cells: dict[tuple[int, int], list[tuple[float, float]]] = {}
    corners = []
    for r in rooms:
        x0, y0, x1, y1 = r["box_px"]
        for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
            corners.append((x, y))
            cells.setdefault((int(x // tol), int(y // tol)), []).append((x, y))
    shared = crossings = 0
    for x, y in corners:
        gx, gy = int(x // tol), int(y // tol)
        near = sum(
            1
            for i in range(gx - 1, gx + 2)
            for j in range(gy - 1, gy + 2)
            for ox, oy in cells.get((i, j), ())
            if abs(ox - x) <= tol and abs(oy - y) <= tol
        )
        shared += near >= 2
        crossings += near >= 4
    return crossings / shared if shared else 0.0


def _room_neighbours(room_lab: np.ndarray, n_rooms: int, t_max: float) -> list[int]:
    """How many other rooms lie across a wall from each room."""
    out = [0] * n_rooms
    if n_rooms == 0:
        return out
    r = max(2, round(0.5 * t_max) + 2)
    # Grey dilation spreads the higher label across a wall, erosion the lower one, so any
    # two rooms a wall apart show up as a pixel whose spread labels differ.
    kernel = np.ones((2 * r + 1, 2 * r + 1), np.uint8)
    lab = room_lab.astype(np.float32)
    hi = cv2.dilate(lab, kernel)
    filled = np.where(lab > 0, lab, float(n_rooms + 1))
    lo = cv2.erode(filled, kernel)
    both = (hi > 0) & (lo <= n_rooms) & (hi != lo)
    if not both.any():
        return out
    pairs = np.unique(np.stack([lo[both], hi[both]], axis=1).astype(np.int32), axis=0)
    for a, b in pairs:
        out[int(a) - 1] += 1
        out[int(b) - 1] += 1
    return out


def _closure(room: fp.MaskRoom, raw: np.ndarray) -> float:
    """Share of a room's outline that is wall as drawn, before any gap was bridged."""
    pts = room.contour[:, 0, :]
    if len(pts) == 0:
        return 0.0
    step = max(1, len(pts) // 400)
    h, w = raw.shape
    xs = np.clip(pts[::step, 0], 0, w - 1)
    ys = np.clip(pts[::step, 1], 0, h - 1)
    return float(np.count_nonzero(raw[ys, xs])) / len(xs)


def _line_walls(
    wsegs: list[tuple[Point, Point]], segs: list[Seg], k: float | None
) -> tuple[list[tuple[list[Point], int, int]], list[float]]:
    """Walls of a drawing that has no double lines or fills: its heaviest long strokes."""
    min_len = _LINE_WALL_MIN_M * k if k else _LINE_WALL_MIN_PT
    long_ = [i for i, (a, b) in enumerate(wsegs) if math.dist(a, b) >= min_len]
    if not long_:
        return [], []
    heaviest = max(segs[i].lw for i in long_)
    out: list[tuple[list[Point], int, int]] = []
    half = max(0.5, 0.5 * heaviest)
    for i in long_:
        if segs[i].lw < 0.6 * heaviest:
            continue
        (x1, y1), (x2, y2) = wsegs[i]
        ln = math.hypot(x2 - x1, y2 - y1)
        nx, ny = -(y2 - y1) / ln * half, (x2 - x1) / ln * half
        out.append((_quad_about((x1, y1), (x2, y2), nx, ny), i, i))
    return out, [2.0 * half]


def _quad_about(a: Point, b: Point, nx: float, ny: float) -> list[Point]:
    return [(a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny), (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)]


@dataclass
class _RoomsPass:
    mask: np.ndarray
    rooms: list[fp.MaskRoom]
    room_lab: np.ndarray
    t_px: list[float]
    raw: np.ndarray  # wall as drawn: no bridges, no door chords, grown onto room outlines


def _rooms_pass(
    shape: tuple[int, int],
    fr: Frame,
    pairs: list[tuple[list[Point], int, int]],
    dark: list[tuple[list[Point], int]],
    light: list[tuple[list[Point], int]],
    wsegs: list[tuple[Point, Point]],
    t_pt: list[float],
    k: float | None,
    chords: list[tuple[Point, Point]],
) -> _RoomsPass | None:
    """Paint the wall mask, bridge door gaps and read the rooms.

    Door chords close the rooms but stay out of the returned wall mask.
    """
    s = fr.s
    mask = np.zeros(shape, dtype=np.uint8)
    paint = sorted([(seq, 255, pts) for pts, seq in dark] + [(seq, 0, pts) for pts, seq in light], key=lambda x: x[0])
    for _seq, val, pts in paint:
        cv2.fillPoly(mask, [_cv([fr.px(p) for p in pts])], val, lineType=cv2.LINE_8, shift=4)
    for q, _a, _b in pairs:
        cv2.fillPoly(mask, [_cv([fr.px(p) for p in q])], 255, lineType=cv2.LINE_8, shift=4)
    for i in {i for _q, a, b in pairs for i in (a, b)}:
        a, b = (_cvpt(fr.px(p)) for p in wsegs[i])
        cv2.line(mask, a, b, 255, 1, cv2.LINE_8, 4)
    # Bands meeting at a junction can leave a sub-pixel seam between them.
    cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), dst=mask)
    t_px = [m * s for m in t_pt] or _band_modes(fp.axis_bands(mask, min_len_px=4))
    if not t_px:
        return None
    t_min, t_max = min(t_px), max(t_px)
    # Finish layers and clearances leave channels between a partition and the wall it
    # meets, and hollow double-line partitions are channels too. Nobody walks through those.
    seal = max(3, round((_MIN_PASSAGE_M * k * s) if k else 0.8 * t_max))
    cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((seal, seal), np.uint8), dst=mask)
    fp.fill_small_holes(mask, (1.6 * t_max + 2) ** 2)
    raw = cv2.dilate(mask, np.ones((5, 5), np.uint8))
    bands = fp.axis_bands(mask, min_len_px=max(4.0, 1.5 * t_min))

    def gap_px(t: float) -> float:
        return _MAX_OPENING_M * k * s if k else _MAX_OPENING_WALLS * t

    fp.bridge_gaps(mask, bands, gap_px)
    # After bridging, a wall stub between two openings is joined to its wall;
    # what stays small and isolated is a column, an arrowhead or a symbol fill.
    _drop_blobs(mask, max(4.0 * t_max, (0.9 * k * s) if k else 0.0))
    fp.fill_small_holes(mask, (1.6 * t_max + 2) ** 2)
    min_area = (0.8 * (k * s) ** 2) if k else (8 * t_min) ** 2
    min_r = (0.25 * k * s) if k else 2.0 * t_min
    closed = mask.copy()
    for a, b in chords:
        cv2.line(closed, _cvpt(fr.px(a)), _cvpt(fr.px(b)), 255, max(2, round(t_min / 2)), cv2.LINE_8, 4)
    rooms, room_lab = fp.find_rooms(
        closed, min_area_px=min_area, min_inscribed_px=min_r, notch_px=round(1.5 * t_min) | 1
    )
    if not rooms:
        return None
    return _RoomsPass(mask, rooms, room_lab, t_px, raw)


def door_chords(segs: list[Seg], curves: list[Curve], k: float | None) -> list[tuple[Point, Point]]:
    """Closed position of each swing door: hinge to the free end of its arc, page points.

    A door is a leaf stroke from the hinge plus an arc centred on the hinge; the
    chord from the hinge to the arc end away from the leaf spans the opening, even
    where the walls either side of it do not line up.
    """
    ends: dict[tuple[int, int], list[tuple[Point, Point]]] = {}
    for sg in segs:
        for p, q in ((sg.a, sg.b), (sg.b, sg.a)):
            ends.setdefault((int(p[0]), int(p[1])), []).append((p, q))
    lo_r, hi_r = (0.45 * k, 1.4 * k) if k else (8.0, 120.0)
    out: list[tuple[Point, Point]] = []
    for cv in curves:
        if len(cv.pts) < 3:
            continue
        e0, e1, mid = cv.pts[0], cv.pts[-1], cv.pts[len(cv.pts) // 2]
        found = None
        for tip, other in ((e0, e1), (e1, e0)):
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for p, hinge in ends.get((int(tip[0]) + dx, int(tip[1]) + dy), ()):
                        if math.dist(p, tip) > 0.8:
                            continue
                        r = math.dist(hinge, tip)
                        if (
                            lo_r <= r <= hi_r
                            and abs(math.dist(hinge, other) - r) <= 0.12 * r
                            and abs(math.dist(hinge, mid) - r) <= 0.12 * r
                        ):
                            found = (hinge, other)
            if found:
                break
        if found:
            out.append(found)
    return out


def _cvpt(p: Point) -> tuple[int, int]:
    return (int(round((p[0] - 0.5) * 16)), int(round((p[1] - 0.5) * 16)))


def _borders_room(quad: list[Point], fr: Frame, room_lab: np.ndarray) -> bool:
    """True when a room lies just outside one of the band's long sides."""
    h, w = room_lab.shape
    q = [fr.px(p) for p in quad]
    cx, cy = sum(p[0] for p in q) / 4, sum(p[1] for p in q) / 4
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        ln = math.dist(a, b)
        if ln < 1e-6:
            continue
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        nx, ny = -(b[1] - a[1]) / ln, (b[0] - a[0]) / ln
        if (mx - cx) * nx + (my - cy) * ny < 0:
            nx, ny = -nx, -ny
        for f in (0.2, 0.5, 0.8):
            x = a[0] + (b[0] - a[0]) * f + nx * 2.5
            y = a[1] + (b[1] - a[1]) * f + ny * 2.5
            if 0 <= int(x) < w and 0 <= int(y) < h and room_lab[int(y), int(x)] > 0:
                return True
    return False


def _fill_modes(dark: list[tuple[list[Point], int]]) -> list[float]:
    """Wall thicknesses from thin rectangular dark fills (poche walls), in points."""
    ds, ws = [], []
    for pts, _s in dark:
        if len(pts) != 4:
            continue
        a, b = math.dist(pts[0], pts[1]), math.dist(pts[1], pts[2])
        t, ln = min(a, b), max(a, b)
        if t > 0.3 and ln >= 3 * t:
            ds.append(math.log(t))
            ws.append(ln)
    return _peaks(ds, ws, math.log(0.3), math.log(60.0))


def _peaks(ds: list[float], ws: list[float], lo: float, hi: float) -> list[float]:
    """Up to four peaks of a weighted log-distance density (bandwidth 3 %)."""
    if not ds:
        return []
    grid = np.arange(lo, hi + 0.01, 0.01)
    weights = np.zeros_like(grid)
    at = np.round((np.asarray(ds) - lo) / 0.01).astype(np.int64)
    inside = (at >= 0) & (at < len(grid))
    np.add.at(weights, at[inside], np.asarray(ws)[inside])
    reach = np.arange(-15, 16) * 0.01
    dens = np.convolve(weights, np.exp(-0.5 * (reach / 0.03) ** 2), mode="same")
    top = dens.max()
    if top <= 0:
        return []
    peaks = [
        i for i in range(1, len(grid) - 1) if dens[i] >= dens[i - 1] and dens[i] > dens[i + 1] and dens[i] >= 0.12 * top
    ]
    peaks.sort(key=lambda i: -dens[i])
    return sorted(float(math.exp(grid[i])) for i in peaks[:4])


def _band_modes(bands: list[fp.Band]) -> list[float]:
    ts = [(b.t, b.hi - b.lo) for b in bands if fp.is_straight(b) and b.hi - b.lo >= 4 * b.t and b.t >= 2]
    if not ts:
        return []
    hist: dict[int, float] = {}
    for t, ln in ts:
        hist[round(t)] = hist.get(round(t), 0.0) + ln
    top = max(hist.values())
    peaks = [
        t for t, wgt in hist.items() if wgt >= 0.15 * top and wgt >= hist.get(t - 1, 0) and wgt >= hist.get(t + 1, 0)
    ]
    return sorted(float(t) for t in peaks)[:4]


def _main_box(elems: list[list[Point]], join_pt: float) -> tuple[float, float, float, float] | None:
    if not elems:
        return None
    xs = [p[0] for e in elems for p in e]
    ys = [p[1] for e in elems for p in e]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    s0 = min(1.0, math.sqrt(1_500_000 / max(1.0, (x1 - x0) * (y1 - y0))))
    w, h = int((x1 - x0) * s0) + 3, int((y1 - y0) * s0) + 3
    m = np.zeros((h, w), dtype=np.uint8)
    for e in elems:
        cv2.fillPoly(m, [np.round((np.asarray(e) - (x0, y0)) * s0 * 16).astype(np.int32)], 255, cv2.LINE_8, 4)
    # Openings break a wall outline; joining across the widest opening keeps one
    # building in one piece while a title block or a detail stays apart.
    r = max(2, int(0.5 * join_pt * s0))
    grown = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_RECT, (2 * r + 1, 2 * r + 1)))
    n, lab = cv2.connectedComponents(grown, connectivity=8)
    if n <= 1:
        return None
    counts = np.bincount(lab[m > 0], minlength=n)
    counts[0] = 0
    ys_, xs_ = np.nonzero((lab == int(np.argmax(counts))) & (m > 0))
    cur = (float(xs_.min()), float(ys_.min()), float(xs_.max() + 1), float(ys_.max() + 1))
    bx0, by0, bx1, by1 = cur[0] / s0 + x0, cur[1] / s0 + y0, cur[2] / s0 + x0, cur[3] / s0 + y0
    margin = max(15.0, 0.03 * max(bx1 - bx0, by1 - by0))
    return (bx0 - margin, by0 - margin, bx1 + margin, by1 + margin)


def _drop_blobs(mask: np.ndarray, max_side_px: float) -> None:
    """Remove small isolated mask blobs (columns, arrowheads, symbol fills)."""
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    small = np.zeros(n, dtype=bool)
    small[1:] = np.maximum(stats[1:, cv2.CC_STAT_WIDTH], stats[1:, cv2.CC_STAT_HEIGHT]) < max_side_px
    mask[small[lab]] = 0


@dataclass
class _Faces:
    h: list[tuple[float, float, float]]  # (c, lo, hi) px
    v: list[tuple[float, float, float]]


def _faces(wsegs: list[tuple[Point, Point]], wfills: list[tuple[list[Point], float, int]], fr: Frame) -> _Faces:
    out = _Faces([], [])
    edges = list(wsegs)
    for pts, _l, _s in wfills:
        edges.extend((pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts)))
    tol = math.tan(math.radians(_AXIS_TOL_DEG))
    for a, b in edges:
        (x1, y1), (x2, y2) = fr.px(a), fr.px(b)
        dx, dy = x2 - x1, y2 - y1
        if abs(dy) <= tol * abs(dx) and abs(dx) > 1:
            out.h.append(((y1 + y2) / 2, min(x1, x2), max(x1, x2)))
        elif abs(dx) <= tol * abs(dy) and abs(dy) > 1:
            out.v.append(((x1 + x2) / 2, min(y1, y2), max(y1, y2)))
    out.h.sort()
    out.v.sort()
    return out


def _snap(faces: list[tuple[float, float, float]], c: float, lo: float, hi: float, tol: float) -> float | None:
    import bisect

    i = bisect.bisect_left(faces, (c - tol, -1e18, -1e18))
    best = None
    span = max(1.0, hi - lo)
    while i < len(faces) and faces[i][0] <= c + tol:
        fc, flo, fhi = faces[i]
        ov = min(hi, fhi) - max(lo, flo)
        if ov >= 0.3 * span and (best is None or abs(fc - c) < abs(best - c)):
            best = fc
        i += 1
    return best


def _room_polygon(r: fp.MaskRoom, faces: _Faces, t_min: float) -> tuple[list[Point], float]:
    """Room outline in pixels, edges snapped onto vector face lines where one is close."""
    poly = fp.simplify(r.contour, max(1.0, min(2.0, 0.3 * t_min)))
    if len(poly) < 3:
        return [], 0.0
    lines = fp.shift_lines(fp.edge_lines(poly), poly, 0.5)
    n = len(poly)
    snapped = 0
    out: list[fp.Line] = []
    # edge_lines skips zero-length edges; rebuild the extents alongside
    ext = []
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if a != b:
            ext.append((a, b))
    for (p, d), (a, b) in zip(lines, ext, strict=False):
        if d[1] == 0.0:
            c = _snap(faces.h, p[1], min(a[0], b[0]), max(a[0], b[0]), 1.6)
            if c is not None:
                p = (p[0], c)
                snapped += 1
        elif d[0] == 0.0:
            c = _snap(faces.v, p[0], min(a[1], b[1]), max(a[1], b[1]), 1.6)
            if c is not None:
                p = (c, p[1])
                snapped += 1
        out.append((p, d))
    return fp.rebuild(out), snapped / max(1, len(out))


# ── symbols ──────────────────────────────────────────────────────────────────


@dataclass
class _Inst:
    pts: list[Point]  # all points (page)
    n_l: int = 0
    n_c: int = 0
    n_f: int = 0
    length: float = 0.0
    sig: tuple[float, ...] = ()
    centre: Point = (0.0, 0.0)
    size: float = 0.0


def _symbols(
    segs: list[Seg],
    curves: list[Curve],
    fills: list[Fill],
    used: set[int],
    fr: Frame,
    mask: np.ndarray,
    room_lab: np.ndarray,
    k: float | None,
    t_max_pt: float,
    budget: Budget | None = None,
) -> list[dict[str, Any]]:
    """Repeated small drawings inside rooms, grouped by a rotation-invariant signature."""
    h, w = mask.shape
    smax = (1.4 * k) if k else max(40.0, 6 * t_max_pt)
    wall = cv2.dilate(mask, np.ones((3, 3), np.uint8))

    def on_wall(p: Point) -> bool:
        x, y = fr.px(fr.work(p))
        xi, yi = int(x), int(y)
        return 0 <= xi < w and 0 <= yi < h and wall[yi, xi] > 0

    prims: list[tuple[str, list[Point], float]] = []
    for i, sg in enumerate(segs):
        ln = math.dist(sg.a, sg.b)
        if i in used or ln > smax or ln < 0.2:
            continue
        mid = ((sg.a[0] + sg.b[0]) / 2, (sg.a[1] + sg.b[1]) / 2)
        if on_wall(mid):
            continue
        prims.append(("l", [sg.a, sg.b], ln))
    for cv_ in curves:
        bx = _bbox(cv_.pts)
        if max(bx[2] - bx[0], bx[3] - bx[1]) > smax:
            continue
        ln = sum(math.dist(cv_.pts[i], cv_.pts[i + 1]) for i in range(len(cv_.pts) - 1))
        prims.append(("c", cv_.pts, ln))
    for f in fills:
        if f.lum >= 0.9:
            continue
        bx = _bbox(f.pts)
        if max(bx[2] - bx[0], bx[3] - bx[1]) > 0.6 * smax:
            continue
        prims.append(("f", f.pts, 0.0))
    if not prims:
        return []
    # union-find on touching bounding boxes
    parent = list(range(len(prims)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    boxes = [_bbox(p[1]) for p in prims]
    cell = max(4.0, smax / 4)
    grid: dict[tuple[int, int], list[int]] = {}
    tol = 0.3
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        for gx in range(int((x0 - tol) // cell), int((x1 + tol) // cell) + 1):
            for gy in range(int((y0 - tol) // cell), int((y1 + tol) // cell) + 1):
                for j in grid.get((gx, gy), []):
                    bx0, by0, bx1, by1 = boxes[j]
                    if x0 - tol <= bx1 and bx0 <= x1 + tol and y0 - tol <= by1 and by0 <= y1 + tol:
                        if _touch(prims[i], prims[j], tol):
                            ri, rj = find(i), find(j)
                            if ri != rj:
                                parent[ri] = rj
                grid.setdefault((gx, gy), []).append(i)
    comps: dict[int, list[int]] = {}
    for i in range(len(prims)):
        comps.setdefault(find(i), []).append(i)
    insts: list[_Inst] = []
    for members in comps.values():
        pts = [p for i in members for p in prims[i][1]]
        bx = _bbox(pts)
        size = max(bx[2] - bx[0], bx[3] - bx[1])
        if size > smax or size < 1.0:
            continue
        centre = ((bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2)
        cx, cy = fr.px(fr.work(centre))
        if not (0 <= int(cx) < w and 0 <= int(cy) < h) or room_lab[int(cy), int(cx)] == 0:
            continue
        inst = _Inst(pts, centre=centre, size=size)
        for i in members:
            kind, _p, ln = prims[i]
            inst.n_l += kind == "l"
            inst.n_c += kind == "c"
            inst.n_f += kind == "f"
            inst.length += ln
        if inst.n_l == 1 and inst.n_c == 0 and inst.n_f == 0:
            continue  # a lone stroke is never a symbol
        mx = sum(p[0] for p in pts) / len(pts)
        my = sum(p[1] for p in pts) / len(pts)
        rad = sorted(math.dist(p, (mx, my)) for p in pts)
        q = [rad[int(f * (len(rad) - 1))] for f in (0.25, 0.5, 0.75, 1.0)]
        inst.sig = (inst.length, *q, size)
        insts.append(inst)
    # greedy clustering on exact counts + relative shape tolerance
    insts.sort(key=lambda i: -i.length)
    groups: list[list[_Inst]] = []
    by_parts: dict[tuple[int, int, int], list[list[_Inst]]] = {}
    for n, inst in enumerate(insts):
        if budget is not None and n % 512 == 0:
            budget.check()
        same = by_parts.setdefault((inst.n_l, inst.n_c, inst.n_f), [])
        for g in same:
            if _close(g[0].sig, inst.sig):
                g.append(inst)
                break
        else:
            g = [inst]
            same.append(g)
            groups.append(g)
    cell = max(4.0, smax)
    around: dict[tuple[int, int], list[_Inst]] = {}
    for inst in insts:
        around.setdefault((int(inst.centre[0] // cell), int(inst.centre[1] // cell)), []).append(inst)
    out = []
    for g in groups:
        if len(g) < 2:
            continue
        if _texty(g, around, cell):
            continue
        n = len(g)
        conf = 0.45 if n == 2 else min(0.85, 0.6 + 0.04 * n)
        out.append({"points": [i.centre for i in g], "count": n, "confidence": round(conf, 2), "size": g[0].size})
    return out


def _touch(a: tuple[str, list[Point], float], b: tuple[str, list[Point], float], tol: float) -> bool:
    if a[0] == "f" or b[0] == "f":
        return True
    for p in (a[1][0], a[1][-1]):
        for q in b[1]:
            if abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol:
                return True
    for p in (b[1][0], b[1][-1]):
        for q in a[1]:
            if abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol:
                return True
    if a[0] == "l" and b[0] == "l":
        return _seg_cross(a[1][0], a[1][1], b[1][0], b[1][1])
    return False


def _seg_cross(p: Point, q: Point, r: Point, s: Point) -> bool:
    def orient(a: Point, b: Point, c: Point) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    return orient(p, q, r) * orient(p, q, s) < 0 and orient(r, s, p) * orient(r, s, q) < 0


def _close(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return all(abs(x - y) <= max(0.4, 0.06 * max(abs(x), abs(y))) for x, y in zip(a, b, strict=True))


def _texty(group: list[_Inst], around: dict[tuple[int, int], list[_Inst]], cell: float) -> bool:
    """A group whose members mostly sit in a row with differently shaped neighbours is text."""
    members = {id(i) for i in group}
    hits = 0
    for m in group:
        gx, gy = int(m.centre[0] // cell), int(m.centre[1] // cell)
        reach = int(1.6 * m.size // cell) + 1
        hit = False
        for x in range(gx - reach, gx + reach + 1):
            for y in range(gy - reach, gy + reach + 1):
                for o in around.get((x, y), ()):
                    if id(o) in members:
                        continue
                    dx, dy = abs(o.centre[0] - m.centre[0]), abs(o.centre[1] - m.centre[1])
                    if (dy <= 0.3 * m.size and dx <= 1.6 * m.size) or (dx <= 0.3 * m.size and dy <= 1.6 * m.size):
                        hit = True
                        break
                if hit:
                    break
            if hit:
                break
        hits += hit
    return hits >= 0.5 * len(group)
