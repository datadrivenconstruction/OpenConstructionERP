# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A design pad: a level (or cross-fall) platform inside an outline, with batters to the ground.

The top is a plane through ``level`` at the outline's centroid, falling by
``cross_fall_pct`` towards ``fall_bearing_deg`` (grid bearing, clockwise from
north). Each outline corner is pushed out along its mitre, so every batter face
keeps the same plan slope ``1:n`` (n horizontal to 1 vertical): down where the
pad is above the ground (fill), up where it is below (cut). The batter stops at
the daylight line where it meets the ground surface. Without a ground surface
the pad is the top alone.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from app.modules.surfaces_volumes.tin import Tin

Ring = list[tuple[float, float]]
#: The furthest a batter is followed before the corner is left at the pad edge, m.
MAX_BATTER_M = 500.0
_STEP_M = 0.25


@dataclass
class PadResult:
    """The pad TIN, its rings and what could not be built."""

    tin: Tin
    top: list[tuple[float, float, float]]
    daylight: list[tuple[float, float, float]] = field(default_factory=list)
    #: Corners whose batter did not reach the ground inside :data:`MAX_BATTER_M` (or left the surface).
    unresolved: int = 0


@dataclass(frozen=True)
class RingCheck:
    """SRV-083 facts about an outline."""

    closed_points: int
    self_intersections: int
    area_m2: float

    @property
    def valid(self) -> bool:
        return self.closed_points >= 3 and self.self_intersections == 0 and self.area_m2 > 0


def open_ring(ring: Ring) -> Ring:
    """The ring without a repeated closing vertex."""
    pts = [(float(e), float(n)) for e, n in ring]
    if (
        len(pts) > 1
        and math.isclose(pts[0][0], pts[-1][0], abs_tol=1e-6)
        and math.isclose(pts[0][1], pts[-1][1], abs_tol=1e-6)
    ):
        pts = pts[:-1]
    return pts


def signed_area(ring: Ring) -> float:
    """Shoelace area, positive for counter-clockwise rings."""
    pts = open_ring(ring)
    s = 0.0
    for i, (x1, y1) in enumerate(pts):
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def _cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _proper_cross(p: tuple, q: tuple, r: tuple, s: tuple) -> bool:
    d1, d2 = _cross(r, s, p), _cross(r, s, q)
    d3, d4 = _cross(p, q, r), _cross(p, q, s)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and 0 not in (d1, d2, d3, d4)


def check_ring(ring: Ring) -> RingCheck:
    """Distinct points, crossings of non-adjacent sides and the area of an outline."""
    pts = open_ring(ring)
    n = len(pts)
    crossings = 0
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if _proper_cross(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n]):
                crossings += 1
    return RingCheck(closed_points=n, self_intersections=crossings, area_m2=abs(signed_area(pts)) if n >= 3 else 0.0)


def top_height(
    e: float, n: float, centroid: tuple[float, float], level: float, fall_pct: float, bearing: float
) -> float:
    """Height of the pad plane at (e, n)."""
    if not fall_pct:
        return level
    b = math.radians(bearing)
    along = (e - centroid[0]) * math.sin(b) + (n - centroid[1]) * math.cos(b)
    return level - along * fall_pct / 100.0


def _centroid(pts: Ring) -> tuple[float, float]:
    a = signed_area(pts)
    if abs(a) < 1e-12:
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    cx = cy = 0.0
    for i, (x1, y1) in enumerate(pts):
        x2, y2 = pts[(i + 1) % len(pts)]
        f = x1 * y2 - x2 * y1
        cx += (x1 + x2) * f
        cy += (y1 + y2) * f
    return (cx / (6 * a), cy / (6 * a))


def mitre_directions(pts: Ring) -> list[tuple[float, float]]:
    """Per corner of a CCW ring: the outward vector whose perpendicular reach to both sides is 1."""
    n = len(pts)
    out = []
    for i in range(n):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
        normals = []
        for a, b in ((p0, p1), (p1, p2)):
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy) or 1.0
            normals.append((dy / length, -dx / length))  # right of the direction = outside for CCW
        sx, sy = normals[0][0] + normals[1][0], normals[0][1] + normals[1][1]
        dot = sx * normals[0][0] + sy * normals[0][1]
        if dot < 1e-6:
            out.append(normals[1])
            continue
        out.append((sx / dot, sy / dot))
    return out


def _daylight(
    ground: Tin, start: tuple[float, float, float], direction: tuple[float, float], n_ratio: float
) -> tuple[float, float, float] | None:
    """Walk the batter out from ``start`` until it meets ``ground``; ``None`` when it never does."""
    e0, n0, z0 = start
    g0 = ground.sample(np.array([e0]), np.array([n0]))[0]
    if not math.isfinite(g0):
        return None
    if abs(z0 - g0) < 1e-6:
        return (e0, n0, z0)
    sign = -1.0 if z0 > g0 else 1.0  # fill slopes down, cut slopes up

    def gap(d: float) -> float:
        g = ground.sample(np.array([e0 + direction[0] * d]), np.array([n0 + direction[1] * d]))[0]
        return (z0 + sign * d / n_ratio) - g if math.isfinite(g) else math.nan

    first = gap(0.0)
    prev_d, prev_g = 0.0, first
    d = _STEP_M
    while d <= MAX_BATTER_M:
        g = gap(d)
        if not math.isfinite(g):
            return None
        if (g > 0) != (prev_g > 0) or g == 0:
            lo, hi, glo = prev_d, d, prev_g
            for _ in range(40):
                mid = (lo + hi) / 2
                gm = gap(mid)
                if (gm > 0) == (glo > 0):
                    lo, glo = mid, gm
                else:
                    hi = mid
            dd = (lo + hi) / 2
            return (e0 + direction[0] * dd, n0 + direction[1] * dd, z0 + sign * dd / n_ratio)
        prev_d, prev_g = d, g
        d += _STEP_M
    return None


def build_pad(
    outline: Ring,
    level: float,
    batter_n: float = 2.0,
    cross_fall_pct: float = 0.0,
    fall_bearing_deg: float = 0.0,
    ground: Tin | None = None,
) -> PadResult:
    """The pad TIN: the top plane, and the batters down or up to ``ground`` when one is given."""
    pts = open_ring(outline)
    if signed_area(pts) < 0:
        pts = pts[::-1]
    centroid = _centroid(pts)
    top = [(e, n, top_height(e, n, centroid, level, cross_fall_pct, fall_bearing_deg)) for e, n in pts]
    daylight: list[tuple[float, float, float]] = []
    unresolved = 0
    if ground is not None and batter_n > 0:
        for corner, direction in zip(top, mitre_directions(pts), strict=True):
            hit = _daylight(ground, corner, direction, batter_n)
            if hit is None:
                unresolved += 1
                hit = corner
            daylight.append(hit)
    lines = [[*top, top[0]]]
    if daylight:
        lines.append([*daylight, daylight[0]])
    outer = daylight or top
    tin = Tin.from_points_with_breaklines([], [], [], lines, boundary=[(p[0], p[1]) for p in outer])
    return PadResult(tin=tin, top=top, daylight=daylight, unresolved=unresolved)


__all__ = [
    "MAX_BATTER_M",
    "PadResult",
    "RingCheck",
    "build_pad",
    "check_ring",
    "mitre_directions",
    "open_ring",
    "signed_area",
    "top_height",
]
