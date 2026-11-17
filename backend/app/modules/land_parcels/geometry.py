# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plane geometry for parcel boundaries, in the project CRS (metres).

No GIS library: parcels are small simple polygons, so the checks are exact
loops over their edges.

* Area by the shoelace formula ``A = 0.5 * |sum(x_i * y_i+1 - x_i+1 * y_i)|``,
  in :class:`~decimal.Decimal` so a lesson number never drifts by a float step.
* Overlap area of two simple polygons (convex or not) by Green's theorem: the
  boundary of ``A n B`` is the part of A's boundary inside B plus the part of
  B's boundary inside A. Edges shared by two neighbours run in opposite
  directions and drop out, so touching parcels overlap by exactly zero.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

Pt = tuple[float, float]
_EPS = 1e-6


def open_ring(ring: Sequence[tuple]) -> list:
    """The ring without its closing vertex (if it repeats the first)."""
    pts = list(ring)
    if len(pts) > 1 and _same(pts[0], pts[-1]):
        pts = pts[:-1]
    return pts


def _same(a: Sequence, b: Sequence, tol: float = 1e-4) -> bool:
    return abs(float(a[0]) - float(b[0])) <= tol and abs(float(a[1]) - float(b[1])) <= tol


def ring_closed(ring: Sequence[tuple]) -> bool:
    """Whether the ring ends on its first vertex (GeoJSON and Shapefile rings must)."""
    return len(ring) >= 4 and _same(ring[0], ring[-1])


def shoelace_area(ring: Sequence[tuple[Decimal, Decimal]]) -> Decimal:
    """Exact plane area of a simple ring, closing vertex optional."""
    pts = [(Decimal(str(x)), Decimal(str(y))) for x, y in open_ring(ring)]
    if len(pts) < 3:
        return Decimal("0")
    total = Decimal("0")
    for i, (x1, y1) in enumerate(pts):
        x2, y2 = pts[(i + 1) % len(pts)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def round_area(area: Decimal, decimals: int) -> Decimal:
    """Area rounded half-up to the profile's decimals (0.01 m2 without a pack)."""
    return area.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def _floats(ring: Sequence[tuple], origin: Pt) -> list[Pt]:
    return [(float(x) - origin[0], float(y) - origin[1]) for x, y in open_ring(ring)]


def _signed(ring: Sequence[Pt]) -> float:
    return (
        sum(
            ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1]
            for i in range(len(ring))
        )
        / 2
    )


def _ccw(ring: list[Pt]) -> list[Pt]:
    return ring if _signed(ring) >= 0 else list(reversed(ring))


def _cross(o: Pt, a: Pt, b: Pt) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _segments_intersect(p: Pt, q: Pt, r: Pt, s: Pt) -> bool:
    d1, d2 = _cross(r, s, p), _cross(r, s, q)
    d3, d4 = _cross(p, q, r), _cross(p, q, s)
    if ((d1 > _EPS and d2 < -_EPS) or (d1 < -_EPS and d2 > _EPS)) and (
        (d3 > _EPS and d4 < -_EPS) or (d3 < -_EPS and d4 > _EPS)
    ):
        return True
    return any(
        abs(d) <= _EPS and _on_segment(a, b, c)
        for d, a, b, c in ((d1, r, s, p), (d2, r, s, q), (d3, p, q, r), (d4, p, q, s))
    )


def _on_segment(a: Pt, b: Pt, p: Pt) -> bool:
    return (
        min(a[0], b[0]) - _EPS <= p[0] <= max(a[0], b[0]) + _EPS
        and min(a[1], b[1]) - _EPS <= p[1] <= max(a[1], b[1]) + _EPS
    )


def self_intersections(ring: Sequence[tuple]) -> list[tuple[int, int]]:
    """Index pairs of non-adjacent edges that touch or cross, plus zero-length edges."""
    origin = (float(ring[0][0]), float(ring[0][1])) if ring else (0.0, 0.0)
    pts = _floats(ring, origin)
    n = len(pts)
    out: list[tuple[int, int]] = []
    for i in range(n):
        if math.dist(pts[i], pts[(i + 1) % n]) <= _EPS:
            out.append((i, i))
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if _segments_intersect(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n]):
                out.append((i, j))
    return out


def _params(p: Pt, q: Pt, r: Pt, s: Pt) -> list[float]:
    """Positions along pq (0..1) where segment rs meets it."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    ex, ey = s[0] - r[0], s[1] - r[1]
    den = dx * ey - dy * ex
    length2 = dx * dx + dy * dy
    if length2 <= 0:
        return []
    if abs(den) <= _EPS * math.sqrt(length2 * (ex * ex + ey * ey) or 1):
        if abs(_cross(p, q, r)) > _EPS * math.sqrt(length2):
            return []
        out = []
        for pt in (r, s):
            t = ((pt[0] - p[0]) * dx + (pt[1] - p[1]) * dy) / length2
            if -_EPS <= t <= 1 + _EPS:
                out.append(min(1.0, max(0.0, t)))
        return out
    t = ((r[0] - p[0]) * ey - (r[1] - p[1]) * ex) / den
    u = ((r[0] - p[0]) * dy - (r[1] - p[1]) * dx) / den
    if -_EPS <= t <= 1 + _EPS and -_EPS <= u <= 1 + _EPS:
        return [min(1.0, max(0.0, t))]
    return []


def _point_seg_dist(p: Pt, a: Pt, b: Pt) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def _inside(p: Pt, ring: Sequence[Pt]) -> bool:
    hit = False
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
            hit = not hit
    return hit


def _classify(p: Pt, direction: Pt, ring: Sequence[Pt]) -> str:
    """``inside``, ``outside``, ``same`` (on an edge running the same way) or ``opposite``."""
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        if _point_seg_dist(p, a, b) <= _EPS * 10:
            dot = direction[0] * (b[0] - a[0]) + direction[1] * (b[1] - a[1])
            return "same" if dot > 0 else "opposite"
    return "inside" if _inside(p, ring) else "outside"


def _boundary_inside(a: list[Pt], b: list[Pt], keep_same: bool) -> float:
    total = 0.0
    n = len(a)
    for i in range(n):
        p, q = a[i], a[(i + 1) % n]
        ts = {0.0, 1.0}
        for j in range(len(b)):
            ts.update(_params(p, q, b[j], b[(j + 1) % len(b)]))
        cuts = sorted(ts)
        for t0, t1 in zip(cuts, cuts[1:], strict=False):
            if t1 - t0 <= 1e-12:
                continue
            s = (p[0] + (q[0] - p[0]) * t0, p[1] + (q[1] - p[1]) * t0)
            e = (p[0] + (q[0] - p[0]) * t1, p[1] + (q[1] - p[1]) * t1)
            where = _classify(((s[0] + e[0]) / 2, (s[1] + e[1]) / 2), (q[0] - p[0], q[1] - p[1]), b)
            if where == "inside" or (keep_same and where == "same"):
                total += (s[0] * e[1] - e[0] * s[1]) / 2
    return total


def _bbox(ring: Sequence[Pt]) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def bboxes_apart(a: Sequence[tuple], b: Sequence[tuple], margin: float = 0.0) -> bool:
    """True when the two rings' boxes are further apart than ``margin``."""
    ax0, ay0, ax1, ay1 = _bbox([(float(x), float(y)) for x, y in a])
    bx0, by0, bx1, by1 = _bbox([(float(x), float(y)) for x, y in b])
    return ax1 + margin < bx0 or bx1 + margin < ax0 or ay1 + margin < by0 or by1 + margin < ay0


def intersection_area(a: Sequence[tuple], b: Sequence[tuple]) -> float:
    """Area shared by two simple polygons, 0.0 for neighbours that only touch."""
    if len(open_ring(a)) < 3 or len(open_ring(b)) < 3 or bboxes_apart(a, b):
        return 0.0
    origin = (float(a[0][0]), float(a[0][1]))
    ra, rb = _ccw(_floats(a, origin)), _ccw(_floats(b, origin))
    area = _boundary_inside(ra, rb, keep_same=True) + _boundary_inside(rb, ra, keep_same=False)
    return max(0.0, area) if area > 1e-9 else 0.0


def boundary_gap(a: Sequence[tuple], b: Sequence[tuple]) -> float:
    """Shortest distance between two boundaries; 0.0 when they touch or cross."""
    origin = (float(a[0][0]), float(a[0][1]))
    ra, rb = _floats(a, origin), _floats(b, origin)
    best = math.inf
    for i in range(len(ra)):
        p, q = ra[i], ra[(i + 1) % len(ra)]
        for j in range(len(rb)):
            r, s = rb[j], rb[(j + 1) % len(rb)]
            if _segments_intersect(p, q, r, s):
                return 0.0
            best = min(
                best,
                _point_seg_dist(p, r, s),
                _point_seg_dist(q, r, s),
                _point_seg_dist(r, p, q),
                _point_seg_dist(s, p, q),
            )
    return 0.0 if best <= _EPS else best


__all__ = [
    "boundary_gap",
    "bboxes_apart",
    "intersection_area",
    "open_ring",
    "ring_closed",
    "round_area",
    "self_intersections",
    "shoelace_area",
]
