# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Parcel subdivision, merge, setback distances and corner precision (no GIS library).

* Split by a line: the infinite line through two points cuts a simple ring
  that it crosses exactly twice into two rings.
* Split to a target area: the cut runs parallel to one side and moves inward
  until the part next to that side has the target area, or it turns about a
  fixed point. Both are solved by bisection on a monotone area, to 1e-6 m2.
* Merge: two rings that share a run of edges (same vertices, opposite
  direction) become one ring once the shared edges are dropped.
* Setback: the smallest distance from a footprint to each boundary edge; a
  footprint vertex outside the parcel is an encroachment (negative distance).
* Corner precision: an allowance ``base + ppm * distance`` (for example a
  relative positional precision class); the values come from a pack.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

Pt = tuple[float, float]
_EPS = 1e-9


class SubdivisionError(ValueError):
    """The split or merge cannot be made on these rings."""


def _open(ring: Sequence[Sequence[float]]) -> list[Pt]:
    pts = [(float(p[0]), float(p[1])) for p in ring]
    if len(pts) > 1 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-6:
        pts = pts[:-1]
    if len(pts) < 3:
        raise SubdivisionError("A parcel ring needs at least three corners")
    return pts


def signed_area(ring: Sequence[Pt]) -> float:
    ox, oy = ring[0]
    twice = 0.0
    for i, (x1, y1) in enumerate(ring):
        x2, y2 = ring[(i + 1) % len(ring)]
        twice += (x1 - ox) * (y2 - oy) - (x2 - ox) * (y1 - oy)
    return twice / 2.0


def area(ring: Sequence[Sequence[float]]) -> float:
    return abs(signed_area(_open(ring)))


def _side(p: Pt, a: Pt, d: Pt) -> float:
    """Positive left of the directed line through ``a`` with direction ``d``."""
    return d[0] * (p[1] - a[1]) - d[1] * (p[0] - a[0])


@dataclass
class Split:
    left: list[Pt]
    right: list[Pt]
    cut: tuple[Pt, Pt]

    @property
    def cut_length(self) -> float:
        (x1, y1), (x2, y2) = self.cut
        return math.hypot(x2 - x1, y2 - y1)


def split_by_line(ring: Sequence[Sequence[float]], a: Sequence[float], b: Sequence[float]) -> Split:
    """Cut ``ring`` with the infinite line through ``a`` and ``b``.

    Raises:
        SubdivisionError: when the line misses the parcel or crosses it more than twice.
    """
    pts = _open(ring)
    origin = (float(a[0]), float(a[1]))
    d = (float(b[0]) - origin[0], float(b[1]) - origin[1])
    if math.hypot(*d) < _EPS:
        raise SubdivisionError("The cut line needs two different points")
    return _split(pts, origin, d)


def _split(pts: list[Pt], origin: Pt, d: Pt) -> Split:
    left: list[Pt] = []
    right: list[Pt] = []
    crossings: list[Pt] = []
    n = len(pts)
    for i in range(n):
        p, q = pts[i], pts[(i + 1) % n]
        sp, sq = _side(p, origin, d), _side(q, origin, d)
        if sp >= -_EPS:
            left.append(p)
        if sp <= _EPS:
            right.append(p)
        if abs(sp) <= _EPS:
            crossings.append(p)
        elif (sp > _EPS and sq < -_EPS) or (sp < -_EPS and sq > _EPS):
            t = sp / (sp - sq)
            x = (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))
            left.append(x)
            right.append(x)
            crossings.append(x)
    if len(crossings) != 2 or len(left) < 3 or len(right) < 3:
        raise SubdivisionError("The cut line must cross the parcel boundary exactly twice")
    return Split(left, right, (crossings[0], crossings[1]))


def _bisect(f, lo: float, hi: float, target: float) -> float:
    flo = f(lo) - target
    for _ in range(200):
        mid = (lo + hi) / 2.0
        fm = f(mid) - target
        if abs(fm) < 1e-9 or hi - lo < 1e-12:
            return mid
        if (fm < 0) == (flo < 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2.0


@dataclass
class AreaSplit:
    part: list[Pt]
    rest: list[Pt]
    cut: tuple[Pt, Pt]
    #: Distance of the cut from the chosen side (parallel mode) or its azimuth in degrees (rotate mode).
    position: float

    @property
    def cut_length(self) -> float:
        (x1, y1), (x2, y2) = self.cut
        return math.hypot(x2 - x1, y2 - y1)


def split_parallel(ring: Sequence[Sequence[float]], side: int, target_area: float) -> AreaSplit:
    """Part of ``target_area`` next to side ``side`` (edge from corner ``side`` to ``side + 1``), cut parallel to it.

    Raises:
        SubdivisionError: when the target is not between 0 and the parcel area, or the side does not exist.
    """
    pts = _open(ring)
    if signed_area(pts) < 0:
        pts = pts[::-1]
        side = (len(pts) - 2 - side) % len(pts)
    total = abs(signed_area(pts))
    if not 0 < target_area < total:
        raise SubdivisionError(f"Target area must lie between 0 and {total:.2f} m2")
    if not 0 <= side < len(pts):
        raise SubdivisionError("No such side")
    a, b = pts[side], pts[(side + 1) % len(pts)]
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    d = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
    inward = (-d[1], d[0])  # left of a counter-clockwise edge is inside
    depth = max(_side(p, a, d) for p in pts)

    def part_at(t: float) -> Split:
        return _split(pts, (a[0] + inward[0] * t, a[1] + inward[1] * t), d)

    def part_area(t: float) -> float:
        if t <= 0:
            return 0.0
        if t >= depth:
            return total
        return abs(signed_area(part_at(t).right))

    t = _bisect(part_area, 0.0, depth, target_area)
    cut = part_at(t)
    return AreaSplit(cut.right, cut.left, cut.cut, t)


def split_rotating(ring: Sequence[Sequence[float]], pivot: Sequence[float], target_area: float) -> AreaSplit:
    """Part of ``target_area`` cut by a line that turns about ``pivot`` (usually a corner).

    The part is the one left of the line as its azimuth grows from the first azimuth that
    gives an empty part.
    """
    pts = _open(ring)
    total = abs(signed_area(pts))
    if not 0 < target_area < total:
        raise SubdivisionError(f"Target area must lie between 0 and {total:.2f} m2")
    p = (float(pivot[0]), float(pivot[1]))

    def left_area(az: float) -> float:
        d = (math.sin(math.radians(az)), math.cos(math.radians(az)))
        try:
            return abs(signed_area(_split(pts, p, d).left))
        except SubdivisionError:
            return 0.0 if all(_side(q, p, d) <= _EPS for q in pts) else total

    samples = [(az, left_area(az)) for az in (i * 0.5 for i in range(721))]
    for (a0, f0), (a1, f1) in zip(samples, samples[1:], strict=False):
        if f0 <= target_area <= f1 and f1 - f0 < total:
            az = _bisect(left_area, a0, a1, target_area)
            d = (math.sin(math.radians(az)), math.cos(math.radians(az)))
            cut = _split(pts, p, d)
            return AreaSplit(cut.left, cut.right, cut.cut, az % 360.0)
    raise SubdivisionError("No cut through this point gives the target area")


def _key(p: Pt, tol: float) -> tuple[int, int]:
    return round(p[0] / tol), round(p[1] / tol)


def merge(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]], tol: float = 0.001) -> list[Pt]:
    """One ring from two parcels that share a run of boundary edges.

    Raises:
        SubdivisionError: when they share no edge or the outline is not one ring.
    """
    ra, rb = _open(a), _open(b)
    if signed_area(ra) < 0:
        ra = ra[::-1]
    if signed_area(rb) < 0:
        rb = rb[::-1]
    coords: dict[tuple[int, int], Pt] = {}
    edges: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for ring in (ra, rb):
        for i, p in enumerate(ring):
            q = ring[(i + 1) % len(ring)]
            kp, kq = _key(p, tol), _key(q, tol)
            coords.setdefault(kp, p)
            coords.setdefault(kq, q)
            edges.append((kp, kq))
    edge_set = set(edges)
    kept = [e for e in edges if (e[1], e[0]) not in edge_set]
    if len(kept) == len(edges):
        raise SubdivisionError("The parcels share no boundary edge")
    nxt: dict[tuple[int, int], tuple[int, int]] = {}
    for u, v in kept:
        if u in nxt:
            raise SubdivisionError("The merged outline is not a single ring")
        nxt[u] = v
    start = kept[0][0]
    out = [coords[start]]
    cur = nxt[start]
    while cur != start:
        out.append(coords[cur])
        if cur not in nxt or len(out) > len(kept):
            raise SubdivisionError("The merged outline is not a single ring")
        cur = nxt[cur]
    if len(out) != len(kept):
        raise SubdivisionError("The merged outline is not a single ring")
    return _drop_collinear(out)


def _drop_collinear(ring: list[Pt]) -> list[Pt]:
    out = []
    n = len(ring)
    for i, p in enumerate(ring):
        o, q = ring[i - 1], ring[(i + 1) % n]
        cross = (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
        if abs(cross) > 1e-6:
            out.append(p)
    return out


def _point_seg(p: Pt, a: Pt, b: Pt) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def _inside(p: Pt, ring: Sequence[Pt]) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % n]
        if (y1 > p[1]) != (y2 > p[1]) and p[0] < (x2 - x1) * (p[1] - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _segments_cross(p: Pt, q: Pt, r: Pt, s: Pt) -> bool:
    def cross(o: Pt, a: Pt, b: Pt) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    d1, d2, d3, d4 = cross(r, s, p), cross(r, s, q), cross(p, q, r), cross(p, q, s)
    return d1 * d2 < 0 and d3 * d4 < 0


@dataclass
class EdgeDistance:
    edge: int
    distance: float
    #: Index of the footprint vertex nearest to this edge (or -1 when an edge of the footprint is nearest).
    nearest: int
    encroaches: bool


def setback_distances(footprint: Sequence[Sequence[float]], boundary: Sequence[Sequence[float]]) -> list[EdgeDistance]:
    """Smallest distance from the footprint to each boundary edge; encroachment makes it negative."""
    fp, bd = _open(footprint), _open(boundary)
    outside = [i for i, p in enumerate(fp) if not _inside(p, bd)]
    out: list[EdgeDistance] = []
    for j in range(len(bd)):
        a, b = bd[j], bd[(j + 1) % len(bd)]
        best, which = math.inf, -1
        for i, p in enumerate(fp):
            dist = _point_seg(p, a, b)
            if dist < best:
                best, which = dist, i
        for i in range(len(fp)):
            p, q = fp[i], fp[(i + 1) % len(fp)]
            for c in (a, b):
                dist = _point_seg(c, p, q)
                if dist < best - 1e-12:
                    best, which = dist, -1
            if _segments_cross(p, q, a, b):
                best, which = 0.0, i
        crossing = any(_segments_cross(fp[i], fp[(i + 1) % len(fp)], a, b) for i in range(len(fp)))
        encroaches = crossing or (which in outside)
        out.append(EdgeDistance(j, -best if encroaches and best > 0 else best, which, encroaches))
    return out


def rpp_allowance(base_m: float, ppm: float, distance_m: float) -> float:
    """Allowance ``base + ppm * 1e-6 * distance`` in metres."""
    return base_m + ppm * 1e-6 * distance_m


__all__ = [
    "AreaSplit",
    "EdgeDistance",
    "Split",
    "SubdivisionError",
    "area",
    "merge",
    "rpp_allowance",
    "setback_distances",
    "signed_area",
    "split_by_line",
    "split_parallel",
    "split_rotating",
]
