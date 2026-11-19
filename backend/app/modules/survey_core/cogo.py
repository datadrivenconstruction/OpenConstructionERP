# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Coordinate geometry (COGO) on the plane of the project CRS (no database).

Bearings are whole-circle azimuths from grid north, clockwise, in decimal
degrees internally. Angles come in and go out as decimal degrees (``deg``),
degrees-minutes-seconds (``dms``) or gon (``gon``, 400 gon = 360 deg).

* Inverse: distance ``sqrt(dE^2 + dN^2)``, bearing ``atan2(dE, dN)``.
* Polar: ``E = E0 + d sin(b)``, ``N = N0 + d cos(b)``.
* Bearing-bearing intersection: two rays solved as a 2x2 linear system;
  parallel rays have no solution (SRV-040).
* Distance-distance intersection: two circles; two solutions are both
  returned and the person picks one (SRV-041).
* Offset: chainage along A->B and the perpendicular offset, right positive.
* Area: shoelace formula over the ring, with its perimeter.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

ANGLE_UNITS: tuple[str, ...] = ("deg", "dms", "gon")
_DEG_PER_GON = 360.0 / 400.0
_PARALLEL_EPS = 1e-12

Pt = tuple[float, float]


class CogoError(ValueError):
    """The computation has no answer for these inputs (for example parallel lines)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ── Angles ────────────────────────────────────────────────────────────────

_DMS_SPLIT = re.compile(r"[^0-9.]+")


def parse_angle(value: str | float | int, unit: str = "deg") -> float:
    """An angle in decimal degrees from a number or text in ``unit``.

    ``dms`` accepts ``49 06 23.4``, ``49°06'23.4"``, ``49-06-23.4`` or the
    calculator form ``49.06234`` (DDD.MMSSss).

    Raises:
        ValueError: when the text is not an angle in that unit.
    """
    if unit not in ANGLE_UNITS:
        raise ValueError(f"unknown angle unit {unit}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if unit == "gon":
            return number * _DEG_PER_GON
        if unit == "dms":
            return _calculator_dms(number)
        return number
    text = str(value).strip().replace(",", ".")
    if not text:
        raise ValueError("empty angle")
    if unit == "dms":
        sign = -1.0 if text.startswith("-") else 1.0
        parts = [p for p in _DMS_SPLIT.split(text.lstrip("+-")) if p]
        if len(parts) == 1:
            return sign * _calculator_dms(float(parts[0]))
        if not 2 <= len(parts) <= 3:
            raise ValueError(f"not a DMS angle: {text}")
        d, m = float(parts[0]), float(parts[1])
        s = float(parts[2]) if len(parts) == 3 else 0.0
        if m >= 60 or s >= 60:
            raise ValueError(f"minutes and seconds must be below 60: {text}")
        return sign * (d + m / 60.0 + s / 3600.0)
    number = float(text)
    return number * _DEG_PER_GON if unit == "gon" else number


def _calculator_dms(number: float) -> float:
    sign = -1.0 if number < 0 else 1.0
    number = abs(number)
    d = math.floor(number)
    rest = round((number - d) * 100, 8)
    m = math.floor(rest)
    s = round((rest - m) * 100, 6)
    if m >= 60 or s >= 60:
        raise ValueError(f"not a DDD.MMSS angle: {number}")
    return sign * (d + m / 60.0 + s / 3600.0)


def to_unit(deg: float, unit: str) -> float:
    """Decimal degrees as a number in ``unit`` (``dms`` gives decimal degrees; format it for text)."""
    return deg / _DEG_PER_GON if unit == "gon" else deg


def format_angle(deg: float, unit: str = "deg", places: int = 4) -> str:
    """Display text: ``49.1066``, ``54.5629`` gon or ``49°06'23.6"`` (seconds to ``places - 3``)."""
    if unit == "gon":
        return f"{deg / _DEG_PER_GON:.{places}f}"
    if unit != "dms":
        return f"{deg:.{places}f}"
    sec_places = max(places - 3, 0)
    sign = "-" if deg < 0 else ""
    total = round(abs(deg) * 3600.0, sec_places)
    d = int(total // 3600)
    m = int((total - d * 3600) // 60)
    s = total - d * 3600 - m * 60
    width = 2 + (sec_places + 1 if sec_places else 0)
    return f"{sign}{d}°{m:02d}'{s:0{width}.{sec_places}f}\""


def norm360(deg: float) -> float:
    """An azimuth folded into [0, 360)."""
    out = deg % 360.0
    return 0.0 if math.isclose(out, 360.0) else out


# ── Computations ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Inverse:
    distance: float
    bearing_deg: float
    d_e: float
    d_n: float
    d_z: float | None = None


def inverse(a: Sequence[float], b: Sequence[float]) -> Inverse:
    """Bearing and distance from ``a`` to ``b`` (E, N[, Z])."""
    d_e, d_n = float(b[0]) - float(a[0]), float(b[1]) - float(a[1])
    dz = None
    if len(a) > 2 and len(b) > 2 and a[2] is not None and b[2] is not None:
        dz = float(b[2]) - float(a[2])
    return Inverse(math.hypot(d_e, d_n), norm360(math.degrees(math.atan2(d_e, d_n))), d_e, d_n, dz)


def polar(origin: Sequence[float], bearing_deg: float, distance: float) -> Pt:
    """The point at ``distance`` along ``bearing_deg`` from ``origin``."""
    b = math.radians(bearing_deg)
    return float(origin[0]) + distance * math.sin(b), float(origin[1]) + distance * math.cos(b)


def bearing_bearing(a: Sequence[float], bearing_a: float, b: Sequence[float], bearing_b: float) -> Pt:
    """Where the line from ``a`` on ``bearing_a`` meets the line from ``b`` on ``bearing_b``.

    Raises:
        CogoError: ``parallel`` when the lines never meet.
    """
    ua = (math.sin(math.radians(bearing_a)), math.cos(math.radians(bearing_a)))
    ub = (math.sin(math.radians(bearing_b)), math.cos(math.radians(bearing_b)))
    det = ua[0] * (-ub[1]) - ua[1] * (-ub[0])
    if abs(det) < _PARALLEL_EPS:
        raise CogoError("parallel", "Lines are parallel: no intersection.")
    rx, ry = float(b[0]) - float(a[0]), float(b[1]) - float(a[1])
    t = (rx * (-ub[1]) - ry * (-ub[0])) / det
    return float(a[0]) + t * ua[0], float(a[1]) + t * ua[1]


def line_line(a1: Sequence[float], a2: Sequence[float], b1: Sequence[float], b2: Sequence[float]) -> Pt:
    """Intersection of line a1-a2 with line b1-b2 (both extended)."""
    return bearing_bearing(a1, inverse(a1, a2).bearing_deg, b1, inverse(b1, b2).bearing_deg)


def distance_distance(a: Sequence[float], ra: float, b: Sequence[float], rb: float) -> list[Pt]:
    """Points at ``ra`` from ``a`` and ``rb`` from ``b``: none, one (tangent) or two.

    The first solution lies to the right of the direction a->b, the second to the left.

    Raises:
        CogoError: ``no_solution`` when the circles do not meet.
    """
    ax, ay, bx, by = float(a[0]), float(a[1]), float(b[0]), float(b[1])
    d = math.hypot(bx - ax, by - ay)
    if d == 0 or d > ra + rb + 1e-9 or d < abs(ra - rb) - 1e-9:
        raise CogoError("no_solution", "The two distances do not meet.")
    along = (ra * ra - rb * rb + d * d) / (2 * d)
    h = math.sqrt(max(ra * ra - along * along, 0.0))
    ux, uy = (bx - ax) / d, (by - ay) / d
    mx, my = ax + along * ux, ay + along * uy
    if h < 1e-9:
        return [(mx, my)]
    # Right of travel (ux, uy) is (uy, -ux).
    return [(mx + h * uy, my - h * ux), (mx - h * uy, my + h * ux)]


@dataclass(frozen=True)
class Offset:
    chainage: float
    offset: float
    foot: Pt


def offset_to_line(a: Sequence[float], b: Sequence[float], p: Sequence[float]) -> Offset:
    """Chainage of ``p`` along a->b from ``a``, its perpendicular offset (right positive) and the foot."""
    ax, ay = float(a[0]), float(a[1])
    length = math.hypot(float(b[0]) - ax, float(b[1]) - ay)
    if length == 0:
        raise CogoError("degenerate", "The line has no length.")
    ux, uy = (float(b[0]) - ax) / length, (float(b[1]) - ay) / length
    px, py = float(p[0]) - ax, float(p[1]) - ay
    s = px * ux + py * uy
    return Offset(s, px * uy - py * ux, (ax + s * ux, ay + s * uy))


def area(ring: Sequence[Sequence[float]]) -> tuple[float, float]:
    """Area (always positive) and perimeter of a ring of at least three points."""
    pts = [(float(p[0]), float(p[1])) for p in ring]
    if len(pts) > 1 and math.isclose(pts[0][0], pts[-1][0]) and math.isclose(pts[0][1], pts[-1][1]):
        pts = pts[:-1]
    if len(pts) < 3:
        raise CogoError("degenerate", "An area needs at least three points.")
    ox, oy = pts[0]
    twice = 0.0
    perimeter = 0.0
    for i, (x1, y1) in enumerate(pts):
        x2, y2 = pts[(i + 1) % len(pts)]
        twice += (x1 - ox) * (y2 - oy) - (x2 - ox) * (y1 - oy)
        perimeter += math.hypot(x2 - x1, y2 - y1)
    return abs(twice) / 2.0, perimeter


__all__ = [
    "ANGLE_UNITS",
    "CogoError",
    "Inverse",
    "Offset",
    "area",
    "bearing_bearing",
    "distance_distance",
    "format_angle",
    "inverse",
    "line_line",
    "norm360",
    "offset_to_line",
    "parse_angle",
    "polar",
    "to_unit",
]
