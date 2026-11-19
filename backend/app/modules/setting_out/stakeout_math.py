# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Setting-out geometry: stake deltas, verdicts, and chainage/offset on an alignment.

Pure functions, no database. Conventions:

* Coordinates are (E, N) metres in the project CRS.
* Radial deviation d = sqrt(dE^2 + dN^2); dZ = measured Z - design Z.
* A stake passes when d <= horizontal tolerance and |dZ| <= vertical tolerance
  (the vertical check only runs when both heights and a vertical tolerance exist).
  Values are compared at 0.1 mm so float noise never flips a verdict.
* Chainage grows along the alignment; offset is positive to the RIGHT of the
  direction of travel, negative to the left.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

Verdict = Literal["pass", "fail", "no_tolerance"]


@dataclass(frozen=True)
class Delta:
    """Measured minus design, in millimetres, and the verdict against a tolerance."""

    de_mm: float
    dn_mm: float
    d_mm: float
    dz_mm: float | None
    verdict: Verdict


def _mm(value_m: float) -> float:
    return round(value_m * 1000.0, 1)


def stake_delta(
    design: tuple[float, float, float | None],
    measured: tuple[float, float, float | None],
    tol_h_mm: float | None,
    tol_v_mm: float | None = None,
) -> Delta:
    """Radial and height deviation of one stake and its verdict.

    Args:
        design: Design (E, N, Z) in metres; Z may be None.
        measured: Measured (E, N, Z) in metres; Z may be None.
        tol_h_mm: Horizontal (radial) tolerance in mm; None means no profile, no verdict.
        tol_v_mm: Vertical tolerance in mm; None skips the height check.

    Returns:
        The deltas in mm (rounded to 0.1 mm) and ``pass``, ``fail`` or ``no_tolerance``.
    """
    de = measured[0] - design[0]
    dn = measured[1] - design[1]
    d_mm = _mm(math.hypot(de, dn))
    dz_mm = _mm(measured[2] - design[2]) if design[2] is not None and measured[2] is not None else None
    if tol_h_mm is None:
        verdict: Verdict = "no_tolerance"
    else:
        ok = d_mm <= round(tol_h_mm, 1)
        if ok and tol_v_mm is not None and dz_mm is not None:
            ok = abs(dz_mm) <= round(tol_v_mm, 1)
        verdict = "pass" if ok else "fail"
    return Delta(de_mm=_mm(de), dn_mm=_mm(dn), d_mm=d_mm, dz_mm=dz_mm, verdict=verdict)


# ── Alignment ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LineElement:
    """A straight from ``start`` to ``end``."""

    start: tuple[float, float]
    end: tuple[float, float]

    @property
    def length(self) -> float:
        return math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])


@dataclass(frozen=True)
class ArcElement:
    """A circular arc from ``start`` to ``end`` about ``center``; ``ccw`` is the turning sense."""

    start: tuple[float, float]
    center: tuple[float, float]
    end: tuple[float, float]
    ccw: bool

    @property
    def radius(self) -> float:
        return math.hypot(self.start[0] - self.center[0], self.start[1] - self.center[1])

    @property
    def sweep(self) -> float:
        """Swept angle in radians, always positive, in (0, 2*pi]."""
        a0 = math.atan2(self.start[1] - self.center[1], self.start[0] - self.center[0])
        a1 = math.atan2(self.end[1] - self.center[1], self.end[0] - self.center[0])
        delta = (a1 - a0) if self.ccw else (a0 - a1)
        delta %= 2 * math.pi
        return delta or 2 * math.pi

    @property
    def length(self) -> float:
        return self.radius * self.sweep


@dataclass(frozen=True)
class SpiralElement:
    """A clothoid: curvature changes linearly from ``1/radius_start`` to ``1/radius_end`` over ``length``.

    ``azimuth_deg`` is the tangent direction at ``start`` (from grid north, clockwise). A radius of
    ``None`` is a straight (infinite radius). ``ccw`` turns left. Positions are integrated with
    Simpson's rule, which is exact to well under a millimetre for road spirals.
    """

    start: tuple[float, float]
    azimuth_deg: float
    length: float
    radius_start: float | None
    radius_end: float | None
    ccw: bool

    def _k(self, radius: float | None) -> float:
        if not radius:
            return 0.0
        return (-1.0 if self.ccw else 1.0) / radius

    def azimuth_at(self, s: float) -> float:
        """Tangent azimuth in radians at arc length ``s`` (clockwise from north)."""
        k0, k1 = self._k(self.radius_start), self._k(self.radius_end)
        return math.radians(self.azimuth_deg) + k0 * s + (k1 - k0) * s * s / (2.0 * self.length)

    def centre_at(self, s: float) -> tuple[float, float]:
        """(E, N) on the spiral at arc length ``s``."""
        steps = max(16, 2 * math.ceil(s / 2.0))
        h = s / steps
        se = ce = 0.0
        for i in range(steps + 1):
            w = 1 if i in (0, steps) else (4 if i % 2 else 2)
            a = self.azimuth_at(i * h)
            se += w * math.sin(a)
            ce += w * math.cos(a)
        return self.start[0] + se * h / 3.0, self.start[1] + ce * h / 3.0

    @property
    def end(self) -> tuple[float, float]:
        return self.centre_at(self.length)

    def point(self, s: float, offset: float) -> tuple[float, float]:
        e, n = self.centre_at(s)
        a = self.azimuth_at(s)
        return e + offset * math.cos(a), n - offset * math.sin(a)

    def project(self, e: float, n: float) -> tuple[float, float] | None:
        """(s, right-positive offset) of the foot of (E, N) on the spiral, or None beyond its ends."""
        samples = max(20, math.ceil(self.length))
        best_s, best_d = 0.0, math.inf
        for i in range(samples + 1):
            s = self.length * i / samples
            pe, pn = self.centre_at(s)
            d = math.hypot(e - pe, n - pn)
            if d < best_d:
                best_s, best_d = s, d
        lo, hi = max(best_s - self.length / samples, 0.0), min(best_s + self.length / samples, self.length)
        for _ in range(40):
            m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
            d1 = math.hypot(e - self.centre_at(m1)[0], n - self.centre_at(m1)[1])
            d2 = math.hypot(e - self.centre_at(m2)[0], n - self.centre_at(m2)[1])
            lo, hi = (lo, m2) if d1 < d2 else (m1, hi)
        s = (lo + hi) / 2
        pe, pn = self.centre_at(s)
        a = self.azimuth_at(s)
        along = (e - pe) * math.sin(a) + (n - pn) * math.cos(a)
        if abs(along) > 1e-3:
            return None  # the nearest spiral point is an end and the foot lies beyond it
        return s, (e - pe) * math.cos(a) - (n - pn) * math.sin(a)


Element = LineElement | ArcElement | SpiralElement


class AlignmentError(ValueError):
    """The alignment cannot answer: empty, or the point lies off every element."""


@dataclass(frozen=True)
class Alignment:
    """A horizontal alignment: elements in order, starting at ``start_chainage``."""

    elements: tuple[Element, ...]
    start_chainage: float = 0.0
    name: str = ""

    @property
    def length(self) -> float:
        return sum(e.length for e in self.elements)

    def point_at(self, chainage: float, offset: float = 0.0) -> tuple[float, float]:
        """(E, N) of the point at ``chainage`` with ``offset`` to the right (negative = left)."""
        if not self.elements:
            raise AlignmentError("alignment has no elements")
        s = chainage - self.start_chainage
        tol = 1e-6
        if s < -tol or s > self.length + tol:
            raise AlignmentError(f"chainage {chainage:.3f} is outside the alignment")
        for i, el in enumerate(self.elements):
            last = i == len(self.elements) - 1
            if s <= el.length + tol or last:
                return _point_on(el, min(max(s, 0.0), el.length), offset)
            s -= el.length
        raise AlignmentError("unreachable")  # pragma: no cover

    def station_offset(self, e: float, n: float) -> tuple[float, float]:
        """Chainage and right-positive offset of (E, N): the element with the smallest |offset| wins."""
        if not self.elements:
            raise AlignmentError("alignment has no elements")
        best: tuple[float, float] | None = None
        base = self.start_chainage
        for el in self.elements:
            hit = _project(el, e, n)
            if hit is not None and (best is None or abs(hit[1]) < abs(best[1])):
                best = (base + hit[0], hit[1])
            base += el.length
        if best is None:
            raise AlignmentError("point is beyond both ends of the alignment")
        return best


def _point_on(el: Element, s: float, offset: float) -> tuple[float, float]:
    if isinstance(el, SpiralElement):
        return el.point(s, offset)
    if isinstance(el, LineElement):
        length = el.length or 1.0
        ux, uy = (el.end[0] - el.start[0]) / length, (el.end[1] - el.start[1]) / length
        # Right of travel direction (ux, uy) is (uy, -ux).
        return el.start[0] + ux * s + uy * offset, el.start[1] + uy * s - ux * offset
    r = el.radius
    a0 = math.atan2(el.start[1] - el.center[1], el.start[0] - el.center[0])
    a = a0 + (s / r if el.ccw else -s / r)
    # Turning left (ccw), right of travel points away from the centre; turning right, towards it.
    rr = r + offset if el.ccw else r - offset
    return el.center[0] + rr * math.cos(a), el.center[1] + rr * math.sin(a)


def _project(el: Element, e: float, n: float) -> tuple[float, float] | None:
    tol = 1e-6
    if isinstance(el, SpiralElement):
        return el.project(e, n)
    if isinstance(el, LineElement):
        length = el.length
        if length == 0:
            return None
        ux, uy = (el.end[0] - el.start[0]) / length, (el.end[1] - el.start[1]) / length
        px, py = e - el.start[0], n - el.start[1]
        s = px * ux + py * uy
        if s < -tol or s > length + tol:
            return None
        return s, px * uy - py * ux
    r = el.radius
    dist = math.hypot(e - el.center[0], n - el.center[1])
    a0 = math.atan2(el.start[1] - el.center[1], el.start[0] - el.center[0])
    a = math.atan2(n - el.center[1], e - el.center[0])
    swept = ((a - a0) if el.ccw else (a0 - a)) % (2 * math.pi)
    if swept > el.sweep + tol:
        return None
    return r * swept, (dist - r) if el.ccw else (r - dist)


__all__ = [
    "Alignment",
    "AlignmentError",
    "ArcElement",
    "Delta",
    "LineElement",
    "SpiralElement",
    "Verdict",
    "stake_delta",
]
