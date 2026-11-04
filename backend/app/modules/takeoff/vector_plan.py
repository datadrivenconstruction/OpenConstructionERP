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
   Dashed strokes (grid axes, hidden lines) and light strokes are not walls.
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

import math
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from app.modules.takeoff import floorplan as fp

Point = tuple[float, float]

_PX_BUDGET = 2_500_000  # wall-mask pixels; keeps the peak near 60 MB on any sheet
_MAX_PX_PER_PT = 3.0
_AXIS_TOL_DEG = 1.0


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


def parse(drawings: list[Any]) -> tuple[list[Seg], list[Fill], list[Curve]]:
    """Straight strokes, flattened curves and fill polygons of a page."""
    segs: list[Seg] = []
    fills: list[Fill] = []
    curves: list[Curve] = []
    for idx, path in enumerate(drawings or []):
        if not isinstance(path, dict):
            continue
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
        if filled:
            flum = _lum(path.get("fill"))
            fills.extend(Fill(_open_ring(p), flum, seq) for p in polys)
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


def _candidate_pairs(lines: list[_Line1D], dmax: float) -> list[tuple[int, int, float, float]]:
    out = []
    n = len(lines)
    for i in range(n):
        a = lines[i]
        for j in range(i + 1, n):
            b = lines[j]
            d = b.c - a.c
            if d > dmax:
                break
            if d < 0.35:
                continue
            ov = min(a.hi, b.hi) - max(a.lo, b.lo)
            if ov > 0.5:
                out.append((i, j, d, ov))
    return out


def wall_modes(groups: list[tuple[float, list[_Line1D]]], dmax: float) -> list[float]:
    """Wall thicknesses: peaks of the overlap-weighted nearest-parallel distances."""
    ds, ws = [], []
    for _ang, lines in groups[:2]:
        best: dict[int, tuple[float, float]] = {}
        for i, j, d, ov in _candidate_pairs(lines, dmax):
            for k in (i, j):
                if k not in best or d < best[k][0]:
                    best[k] = (d, ov)
        for d, ov in best.values():
            if ov >= max(2.0 * d, 3.0):
                ds.append(math.log(d))
                ws.append(ov)
    return _peaks(ds, ws, math.log(0.4), math.log(dmax))


def _in_modes(d: float, modes: list[float]) -> bool:
    return any(abs(d - m) <= max(0.35, 0.08 * m) for m in modes)


def wall_pairs(
    groups: list[tuple[float, list[_Line1D]]], modes: list[float], dmax: float
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
            for i, j, d, ov in _candidate_pairs(lines, dmax)
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


def _setup(segs: list[Seg], fills: list[Fill], theta: float, dmax: float) -> _Setup:
    """Work frame at ``theta`` with its wall pairs, fills and how much wall they show."""
    fr = Frame(theta)
    wsegs = [(fr.work(sg.a), fr.work(sg.b)) for sg in segs]
    wfills = [([fr.work(p) for p in f.pts], f.lum, f.seq) for f in fills]
    groups = _groups(wsegs)
    modes = wall_modes(groups, dmax)
    pairs = wall_pairs(groups, modes, dmax) if modes else []
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


def read_plan(drawings: list[Any], pt_per_m: float | None = None) -> PlanResult:
    """Rooms, wall runs and symbol counts of one vector page."""
    segs, fills, curves = parse(drawings)
    return read_parts(segs, fills, curves, pt_per_m)


def read_parts(segs: list[Seg], fills: list[Fill], curves: list[Curve], pt_per_m: float | None = None) -> PlanResult:
    """Rooms, wall runs and symbol counts from strokes, fills and arcs in page points."""
    res = PlanResult()
    if not segs and not fills:
        return res
    k = pt_per_m if pt_per_m and pt_per_m > 0 else None
    # Wider than any wall (0.55 m) is furniture, a counter or a dimension offset.
    dmax = min(45.0, 0.55 * k) if k else 45.0
    # A small rotated building can lose the angle vote to an upright title block;
    # the frame that finds the most wall evidence wins.
    best: _Setup | None = None
    for theta in candidate_angles(segs, fills):
        su = _setup(segs, fills, theta, dmax)
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
    rp = _rooms_pass(shape, fr, pairs, dark, light, wsegs, t_pt, k, chords)
    if rp is None:
        return res
    if pairs:
        # Bands that border no room are dimension offsets or details beside the plan.
        keep = [pr for pr in pairs if _borders_room(pr[0], fr, rp.room_lab)]
        if len(keep) < len(pairs):
            pairs = keep
            rp = _rooms_pass(shape, fr, pairs, dark, light, wsegs, t_pt, k, chords) or rp
    res.found_structure = True
    t_min = min(rp.t_px)
    faces = _faces(wsegs, wfills, fr)
    for r in rp.rooms:
        poly, snapped = _room_polygon(r, faces, t_min)
        if len(poly) < 3:
            continue
        res.rooms.append(
            {
                "points": [fr.from_px(p) for p in poly],
                "snapped": snapped,
                "vertices": len(poly),
                "fill_ratio": r.area_px / max(1.0, r.filled_px),
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
    res.counts = _symbols(segs, curves, fills, used, fr, rp.mask, rp.room_lab, k, max(rp.t_px) / fr.s)
    return res


@dataclass
class _RoomsPass:
    mask: np.ndarray
    rooms: list[fp.MaskRoom]
    room_lab: np.ndarray
    t_px: list[float]


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
    fp.fill_small_holes(mask, (1.6 * t_max + 2) ** 2)
    bands = fp.axis_bands(mask, min_len_px=max(4.0, 1.5 * t_min))

    def gap_px(t: float) -> float:
        if k:
            return (2.25 if t / (k * s) >= 0.2 else 1.3) * k * s
        thick = len(t_px) > 1 and t >= 0.7 * t_max
        return (6.5 if thick else 11.0) * t

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
    rooms, room_lab = fp.find_rooms(closed, min_area_px=min_area, min_inscribed_px=min_r)
    if not rooms:
        return None
    return _RoomsPass(mask, rooms, room_lab, t_px)


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
    dens = np.zeros_like(grid)
    for d, w in zip(ds, ws, strict=True):
        dens += w * np.exp(-0.5 * ((grid - d) / 0.03) ** 2)
    top = dens.max()
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
    for inst in insts:
        for g in groups:
            ref = g[0]
            if (ref.n_l, ref.n_c, ref.n_f) == (inst.n_l, inst.n_c, inst.n_f) and _close(ref.sig, inst.sig):
                g.append(inst)
                break
        else:
            groups.append([inst])
    out = []
    for g in groups:
        if len(g) < 2:
            continue
        if _texty(g, insts):
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


def _texty(group: list[_Inst], everything: list[_Inst]) -> bool:
    """A group whose members mostly sit in a row with differently shaped neighbours is text."""
    members = {id(i) for i in group}
    hits = 0
    for m in group:
        for o in everything:
            if id(o) in members:
                continue
            if abs(o.centre[1] - m.centre[1]) <= 0.3 * m.size and abs(o.centre[0] - m.centre[0]) <= 1.6 * m.size:
                hits += 1
                break
            if abs(o.centre[0] - m.centre[0]) <= 0.3 * m.size and abs(o.centre[1] - m.centre[1]) <= 1.6 * m.size:
                hits += 1
                break
    return hits >= 0.5 * len(group)
