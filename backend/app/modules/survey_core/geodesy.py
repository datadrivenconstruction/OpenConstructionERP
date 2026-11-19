# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site grid to national grid, and grid to ground distances (no database).

Local grid: a 2D similarity (Helmert) transform solved from points known in
both systems, ``E = a*x - b*y + tE`` and ``N = b*x + a*y + tN`` with
``a = s*cos(r)`` and ``b = s*sin(r)``. Two points give the exact solution,
three or more a least-squares fit; every common point gets its residual.

Combined scale factor: ``CSF = k * R / (R + h)`` with the point scale ``k`` of
the projection (pyproj ``get_factors``) and the mean Earth radius
R = 6,371,000 m (IUGG mean radius 6,371,008.8 m, rounded). For transverse
Mercator the check is ``k ~= k0 * (1 + x^2 / (2 R^2))``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from pyproj import CRS, Proj, Transformer

EARTH_RADIUS_M = 6_371_000.0

#: Scale factors a unit mix-up produces (metres read as feet and back); SRV-024 flags them without a tolerance.
UNIT_SIGNATURES = (0.3048, 1 / 0.3048, 1200 / 3937, 3937 / 1200)


@dataclass(frozen=True)
class CommonPoint:
    """A point known in the site grid (x, y) and in the national grid (e, n)."""

    point_id: str
    x: float
    y: float
    e: float
    n: float
    use: bool = True


@dataclass(frozen=True)
class Residual:
    """Measured minus computed national coordinates of one common point, in millimetres."""

    point_id: str
    de_mm: float
    dn_mm: float
    r_mm: float
    used: bool


@dataclass(frozen=True)
class Helmert2D:
    """Local (x, y) -> grid (E, N)."""

    a: float
    b: float
    te: float
    tn: float

    @property
    def scale(self) -> float:
        return math.hypot(self.a, self.b)

    @property
    def scale_ppm(self) -> float:
        return (self.scale - 1.0) * 1e6

    @property
    def rotation_deg(self) -> float:
        return math.degrees(math.atan2(self.b, self.a))

    def forward(self, x: float, y: float) -> tuple[float, float]:
        return self.a * x - self.b * y + self.te, self.b * x + self.a * y + self.tn

    def inverse(self, e: float, n: float) -> tuple[float, float]:
        det = self.a * self.a + self.b * self.b
        de, dn = e - self.te, n - self.tn
        return (self.a * de + self.b * dn) / det, (-self.b * de + self.a * dn) / det

    @classmethod
    def from_params(cls, scale: float, rotation_deg: float, te: float, tn: float) -> Helmert2D:
        r = math.radians(rotation_deg)
        return cls(scale * math.cos(r), scale * math.sin(r), te, tn)


@dataclass
class LocalGridFit:
    """The solved transform, each common point's residual and the RMS of the fitted ones."""

    transform: Helmert2D
    residuals: list[Residual] = field(default_factory=list)
    rms_mm: float = 0.0
    used: int = 0


def solve_helmert(points: Sequence[CommonPoint]) -> LocalGridFit:
    """Fit the similarity transform; points with ``use=False`` are check points only.

    Raises:
        ValueError: with fewer than two fitted points, or when they coincide (SRV-022).
    """
    fit = [p for p in points if p.use]
    if len(fit) < 2:
        raise ValueError("A local grid needs at least 2 common points")
    k = len(fit)
    cx, cy = sum(p.x for p in fit) / k, sum(p.y for p in fit) / k
    ce, cn = sum(p.e for p in fit) / k, sum(p.n for p in fit) / k
    sxx = num_a = num_b = 0.0
    for p in fit:
        x, y, e, n = p.x - cx, p.y - cy, p.e - ce, p.n - cn
        sxx += x * x + y * y
        num_a += x * e + y * n
        num_b += x * n - y * e
    if sxx < 1e-12:
        raise ValueError("The common points coincide in the local grid")
    a, b = num_a / sxx, num_b / sxx
    tr = Helmert2D(a, b, ce - (a * cx - b * cy), cn - (b * cx + a * cy))
    out = LocalGridFit(transform=tr, used=k)
    sq = 0.0
    for p in points:
        e, n = tr.forward(p.x, p.y)
        de, dn = (p.e - e) * 1000.0, (p.n - n) * 1000.0
        r = math.hypot(de, dn)
        out.residuals.append(Residual(p.point_id, round(de, 2), round(dn, 2), round(r, 2), p.use))
        if p.use:
            sq += de * de + dn * dn
    # Two points fit exactly; their RMS is zero by construction.
    out.rms_mm = round(math.sqrt(sq / k), 2) if k > 2 else 0.0
    return out


def unit_mixup(scale: float) -> bool:
    """Whether a solved scale looks like metres taken for feet or the reverse (within 1 %)."""
    return any(abs(scale / s - 1.0) < 0.01 for s in UNIT_SIGNATURES)


# ── Grid and ground ─────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScaleFactor:
    """Point scale, elevation factor and their product at one place."""

    k: float
    elevation_factor: float
    csf: float
    height_m: float

    def grid_from_ground(self, ground_m: float) -> float:
        return ground_m * self.csf

    def ground_from_grid(self, grid_m: float) -> float:
        return grid_m / self.csf


def elevation_factor(height_m: float, radius_m: float = EARTH_RADIUS_M) -> float:
    """``R / (R + h)``: a distance at height h shrinks by this much on the ellipsoid."""
    return radius_m / (radius_m + height_m)


def tm_scale_approx(easting_offset_m: float, k0: float = 0.9996, radius_m: float = EARTH_RADIUS_M) -> float:
    """Transverse Mercator point scale ``k0 * (1 + x^2 / (2 R^2))`` (the check on pyproj)."""
    return k0 * (1.0 + easting_offset_m**2 / (2.0 * radius_m**2))


def point_scale(epsg: int, e: float, n: float) -> float:
    """Exact projection scale at a grid position via pyproj ``get_factors``.

    Raises:
        ValueError: when the system is not projected.
    """
    crs = CRS.from_epsg(int(epsg))
    if not crs.is_projected:
        raise ValueError(f"EPSG {epsg} is not a projected system")
    geo = crs.geodetic_crs
    lon, lat = Transformer.from_crs(crs, geo, always_xy=True).transform(e, n)
    factors = Proj(crs).get_factors(lon, lat)
    # Conformal projections: meridional and parallel scale agree; their mean guards non-conformal ones.
    return float((factors.meridional_scale + factors.parallel_scale) / 2.0)


def combined_scale_factor(epsg: int, e: float, n: float, height_m: float) -> ScaleFactor:
    """CSF at a place: what a ground distance becomes on the grid."""
    k = point_scale(epsg, e, n)
    ef = elevation_factor(height_m)
    return ScaleFactor(k=k, elevation_factor=ef, csf=k * ef, height_m=height_m)


def ground_grid_difference_mm(csf: float, distance_m: float) -> float:
    """Ground minus grid over ``distance_m`` on the ground, in millimetres."""
    return (distance_m - distance_m * csf) * 1000.0


__all__ = [
    "EARTH_RADIUS_M",
    "CommonPoint",
    "Helmert2D",
    "LocalGridFit",
    "Residual",
    "ScaleFactor",
    "combined_scale_factor",
    "elevation_factor",
    "ground_grid_difference_mm",
    "point_scale",
    "solve_helmert",
    "tm_scale_approx",
    "unit_mixup",
]
