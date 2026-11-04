# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rooms and wall runs from a wall mask, shared by the vector and raster detectors.

Both offline takeoff detectors reduce a page to the same intermediate: a binary
WALL MASK in a work frame whose axes follow the drawing's walls. The vector
path paints it from paired wall faces and dark fills; the raster path derives
it from the scan. From that mask this module reads

* axis bands: every mask pixel belongs to the horizontal or the vertical band
  it runs longer in, so a wall is one straight band of constant thickness;
* door and window gaps: two collinear bands of the same thickness with a short
  gap between them are bridged, which closes each room's outline;
* rooms: free regions enclosed by walls that do not reach the frame border, are
  wide enough to stand in and do not enclose other rooms;
* wall runs: bands that border a room, with their ends moved to the centreline
  of the wall they run into (a wall length is measured centreline to centreline).

Coordinates are mask pixels, pixel ``i`` covering ``[i, i + 1)``. Callers own
the transforms to page points. Pure numpy/OpenCV, no I/O.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

PointF = tuple[float, float]


@dataclass
class Band:
    """A straight run of the wall mask along one axis."""

    axis: str  # "h" runs along x, "v" runs along y
    c: float  # centre across the axis
    t: float  # mean thickness
    lo: float  # start along the axis
    hi: float  # end along the axis
    npx: int
    span: float  # bounding extent across the axis


@dataclass
class MaskRoom:
    """One enclosed free region of the wall mask."""

    contour: np.ndarray  # outer contour, int32 (N, 1, 2)
    area_px: float  # free pixels of the region
    filled_px: float  # area inside the outer contour
    inscribed_px: float  # radius of the largest inscribed circle
    label: int


@dataclass
class WallRun:
    """A wall centreline segment along one axis."""

    axis: str
    c: float
    t: float
    lo: float
    hi: float
    support: float  # share of the run that borders a room
    ends_joined: int  # ends that meet another wall (0..2)


def _row_runs(mask: np.ndarray) -> np.ndarray:
    """Length of the horizontal run of ``mask`` through every pixel (0 off the mask)."""
    h, w = mask.shape
    pad = np.zeros((h, w + 2), dtype=np.int8)
    pad[:, 1:-1] = mask > 0
    flat = pad.ravel()
    d = np.diff(flat)
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    lens = (ends - starts).astype(np.int32)
    out = np.zeros(flat.shape, dtype=np.int32)
    out[flat.astype(bool)] = np.repeat(lens, lens)
    return out.reshape(h, w + 2)[:, 1:-1]


def axis_bands(mask: np.ndarray, *, min_len_px: float) -> list[Band]:
    """Split the mask into horizontal and vertical bands.

    A pixel joins the direction it runs longer in, once that run reaches
    ``min_len_px``; a short stub (a wall end beside a door) keeps the pixels
    it has in its own direction.
    """
    hrun = _row_runs(mask)
    vrun = cv2.transpose(_row_runs(cv2.transpose(mask)))
    on = mask > 0
    classes = {
        "h": on & (hrun >= vrun) & (hrun >= min_len_px),
        "v": on & (vrun > hrun) & (vrun >= min_len_px),
    }
    del hrun, vrun, on
    bands: list[Band] = []
    for axis, cls in classes.items():
        n, _labels, stats, cents = cv2.connectedComponentsWithStats(cls.view(np.uint8), connectivity=4)
        for i in range(1, n):
            x, y, bw, bh, area = (int(v) for v in stats[i])
            along, across = (bw, bh) if axis == "h" else (bh, bw)
            if along < 3:
                continue
            c = float(cents[i][1] if axis == "h" else cents[i][0]) + 0.5
            lo = float(x if axis == "h" else y)
            bands.append(Band(axis, c, area / along, lo, lo + along, area, float(across)))
    return bands


def is_straight(b: Band) -> bool:
    """A band whose extent across stays close to its mean thickness."""
    return b.span <= 1.35 * b.t + 2.0 and b.hi - b.lo >= 0.6 * b.t


def bridge_gaps(mask: np.ndarray, bands: list[Band], gap_px: Callable[[float], float]) -> int:
    """Fill short gaps between collinear bands of equal thickness (doors, windows).

    Each band end is bridged at most once, to its nearest partner. Returns the
    number of bridges painted into ``mask`` (in place).
    """
    painted = 0
    for axis in ("h", "v"):
        bs = sorted((b for b in bands if b.axis == axis and is_straight(b)), key=lambda b: b.c)
        cands: list[tuple[float, int, int]] = []
        for i, a in enumerate(bs):
            for j in range(i + 1, len(bs)):
                b = bs[j]
                if b.c - a.c > max(1.5, 0.5 * min(a.t, b.t)):
                    break
                if not 0.7 <= b.t / max(a.t, 1e-6) <= 1.43:
                    continue
                left, right = (i, j) if a.lo < b.lo else (j, i)
                g = bs[right].lo - bs[left].hi
                if 0 < g <= gap_px(0.5 * (a.t + b.t)):
                    cands.append((g, left, right))
        cands.sort()
        used_r: set[int] = set()
        used_l: set[int] = set()
        for _g, left, right in cands:
            if left in used_r or right in used_l:
                continue
            used_r.add(left)
            used_l.add(right)
            a, b = bs[left], bs[right]
            t = 0.5 * (a.t + b.t)
            c = 0.5 * (a.c + b.c)
            c0, c1 = round(c - t / 2), round(c + t / 2)
            l0, l1 = round(a.hi) - 1, round(b.lo) + 1
            if axis == "h":
                mask[max(0, c0) : c1, max(0, l0) : l1] = 255
            else:
                mask[max(0, l0) : l1, max(0, c0) : c1] = 255
            painted += 1
    return painted


def fill_small_holes(mask: np.ndarray, max_area_px: float) -> None:
    """Fill free regions smaller than ``max_area_px`` (wall-junction voids), in place."""
    free = (mask == 0).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
    small = np.zeros(n, dtype=bool)
    small[1:] = stats[1:, cv2.CC_STAT_AREA] < max_area_px
    mask[small[labels]] = 255


def find_rooms(mask: np.ndarray, *, min_area_px: float, min_inscribed_px: float) -> tuple[list[MaskRoom], np.ndarray]:
    """Enclosed free regions of ``mask`` that qualify as rooms, plus the room label image.

    The label image holds the room's index + 1 on its pixels and 0 elsewhere.
    """
    h, w = mask.shape
    free = (mask == 0).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
    rooms: list[MaskRoom] = []
    for i in range(1, n):
        x, y, bw, bh, area = (int(v) for v in stats[i])
        if x <= 0 or y <= 0 or x + bw >= w or y + bh >= h:
            continue  # reaches the frame border: outside the building
        if area < min_area_px or area > 0.8 * h * w:
            continue
        crop = (labels[y - 1 : y + bh + 1, x - 1 : x + bw + 1] == i).astype(np.uint8)
        inscribed = float(cv2.distanceTransform(crop, cv2.DIST_L2, 3).max())
        if inscribed < min_inscribed_px:
            continue
        contours, _ = cv2.findContours(crop, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            continue
        cnt = max(contours, key=cv2.contourArea) + np.array([[[x - 1, y - 1]]], dtype=np.int32)
        rooms.append(MaskRoom(cnt, float(area), float(cv2.contourArea(cnt)), inscribed, i))
    rooms = _drop_envelopes(rooms)
    lut = np.zeros(n, dtype=np.int32)
    for k, r in enumerate(rooms):
        lut[r.label] = k + 1
    return rooms, lut[labels]


def _drop_envelopes(rooms: list[MaskRoom]) -> list[MaskRoom]:
    """Drop regions that enclose another room: the space between a frame and a building."""
    keep = []
    for r in rooms:
        enclosing = False
        for o in rooms:
            if o is r or o.filled_px >= r.filled_px:
                continue
            px, py = (float(v) for v in o.contour[0, 0])
            if cv2.pointPolygonTest(r.contour, (px, py), False) > 0:
                enclosing = True
                break
        if not enclosing:
            keep.append(r)
    return keep


# ── polygons ─────────────────────────────────────────────────────────────────

Line = tuple[PointF, PointF]  # (point on the line, unit direction)


def simplify(contour: np.ndarray, eps_px: float) -> list[PointF]:
    """Douglas-Peucker polygon of a contour, in pixel-centre coordinates."""
    approx = cv2.approxPolyDP(contour, eps_px, True)
    return [(float(p[0][0]) + 0.5, float(p[0][1]) + 0.5) for p in approx]


def edge_lines(poly: list[PointF], tol_deg: float = 6.0) -> list[Line]:
    """Edge lines of a polygon; near-axis edges snap to the axes through their midpoint."""
    lines: list[Line] = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        if dx == 0 and dy == 0:
            continue
        ang = math.degrees(math.atan2(dy, dx)) % 180.0
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        if min(ang, 180.0 - ang) <= tol_deg:
            lines.append((mid, (1.0 if dx >= 0 else -1.0, 0.0)))
        elif abs(ang - 90.0) <= tol_deg:
            lines.append((mid, (0.0, 1.0 if dy >= 0 else -1.0)))
        else:
            ln = math.hypot(dx, dy)
            lines.append((mid, (dx / ln, dy / ln)))
    return lines


def rebuild(lines: list[Line]) -> list[PointF]:
    """Polygon vertices from consecutive edge lines.

    Consecutive parallel lines on one offset merge; on different offsets they
    become a step with both corners kept.
    """
    merged: list[Line] = []
    for ln in lines:
        if merged and _parallel(merged[-1], ln) and _offset(merged[-1], ln) < 0.75:
            continue
        merged.append(ln)
    while len(merged) > 2 and _parallel(merged[-1], merged[0]) and _offset(merged[-1], merged[0]) < 0.75:
        merged.pop()
    if len(merged) < 3:
        return []
    out: list[PointF] = []
    for i in range(len(merged)):
        (p, d), (q, e) = merged[i - 1], merged[i]
        x = _intersect(p, d, q, e)
        if x is None:
            out.append(_project(q, p, d))
            out.append(q)
        else:
            out.append(x)
    return out


def _parallel(l1: Line, l2: Line, tol_deg: float = 2.0) -> bool:
    d, e = l1[1], l2[1]
    return abs(d[0] * e[1] - d[1] * e[0]) < math.sin(math.radians(tol_deg))


def _offset(l1: Line, l2: Line) -> float:
    (p, d), (q, _) = l1, l2
    return abs((q[0] - p[0]) * d[1] - (q[1] - p[1]) * d[0])


def _intersect(p: PointF, d: PointF, q: PointF, e: PointF) -> PointF | None:
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-9:
        return None
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
    return (p[0] + d[0] * t, p[1] + d[1] * t)


def _project(q: PointF, p: PointF, d: PointF) -> PointF:
    t = (q[0] - p[0]) * d[0] + (q[1] - p[1]) * d[1]
    return (p[0] + d[0] * t, p[1] + d[1] * t)


def polygon_area(poly: list[PointF]) -> float:
    return abs(_signed_area(poly))


def _signed_area(poly: list[PointF]) -> float:
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def shift_lines(lines: list[Line], poly: list[PointF], d: float) -> list[Line]:
    """Move every edge line of ``poly`` outward by ``d`` (inward when negative)."""
    sign = 1.0 if _signed_area(poly) > 0 else -1.0
    out = []
    for p, e in lines:
        nx, ny = sign * e[1], -sign * e[0]
        out.append(((p[0] + nx * d, p[1] + ny * d), e))
    return out


# ── wall runs ────────────────────────────────────────────────────────────────


def wall_runs(
    mask: np.ndarray,
    bands: list[Band],
    room_lab: np.ndarray,
    *,
    min_len_px: float,
) -> list[WallRun]:
    """Centreline runs of the straight bands, with their room support.

    Collinear bands of one thickness separated only by wall pixels (a crossing
    wall) are one run. Ends inside or against a perpendicular band move to that
    band's centreline.
    """
    straight = [b for b in bands if is_straight(b)]
    t_max = max((b.t for b in straight), default=1.0)
    merged: list[Band] = []
    for axis in ("h", "v"):
        groups: list[list[Band]] = []
        for b in sorted((b for b in straight if b.axis == axis), key=lambda b: b.lo):
            for g in groups:
                last = g[-1]
                if abs(last.c - b.c) <= max(1.5, 0.3 * last.t) and 0.7 <= b.t / last.t <= 1.43:
                    if b.lo - last.hi <= 1.4 * t_max + 2 and _solid(mask, axis, last, b):
                        g.append(b)
                        break
            else:
                groups.append([b])
        for g in groups:
            npx = sum(b.npx for b in g)
            c = sum(b.c * b.npx for b in g) / npx
            t = sum(b.t * (b.hi - b.lo) for b in g) / sum(b.hi - b.lo for b in g)
            merged.append(Band(axis, c, t, g[0].lo, max(b.hi for b in g), npx, max(b.span for b in g)))
    perp = {"h": [b for b in merged if b.axis == "v"], "v": [b for b in merged if b.axis == "h"]}
    out: list[WallRun] = []
    for b in merged:
        lo, j0 = _end_to_centre(b, b.lo, perp[b.axis])
        hi, j1 = _end_to_centre(b, b.hi, perp[b.axis])
        if hi - lo < min_len_px:
            continue
        out.append(WallRun(b.axis, b.c, b.t, lo, hi, _support(room_lab, b), j0 + j1))
    return out


def _solid(mask: np.ndarray, axis: str, a: Band, b: Band) -> bool:
    """True when the gap between two collinear bands is (almost) all wall."""
    lo, hi = round(a.hi), round(b.lo)
    if hi <= lo:
        return True
    c0, c1 = max(0, round(a.c - a.t / 4)), round(a.c + a.t / 4) + 1
    win = mask[c0:c1, lo:hi] if axis == "h" else mask[lo:hi, c0:c1]
    return win.size == 0 or float(np.count_nonzero(win)) / win.size >= 0.8


def _end_to_centre(b: Band, end: float, perp: list[Band]) -> tuple[float, int]:
    best: tuple[float, float] | None = None
    for p in perp:
        if not (p.lo - 2 <= b.c <= p.hi + 2):
            continue
        dist = abs(p.c - end)
        if dist <= p.t / 2 + 3 and (best is None or dist < best[0]):
            best = (dist, p.c)
    if best is None:
        return end, 0
    return best[1], 1


def _support(room_lab: np.ndarray, b: Band) -> float:
    h, w = room_lab.shape
    n = max(2, int((b.hi - b.lo) / 3))
    along = np.linspace(b.lo + 1, b.hi - 1, n).astype(int)
    hit = np.zeros(n, dtype=bool)
    for side in (-1, 1):
        off = int(b.c + side * (b.t / 2 + 2.0))
        rows, cols = (np.full(n, off), along) if b.axis == "h" else (along, np.full(n, off))
        ok = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)
        vals = np.zeros(n, dtype=bool)
        vals[ok] = room_lab[rows[ok], cols[ok]] > 0
        hit |= vals
    return float(hit.mean())
