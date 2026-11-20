# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Grid to WGS 84 view transform of the plan canvas.

The canvas computes in grid metres; MapLibre draws in WGS 84. Instead of shipping a
projection library to the browser, the server fits a second-order polynomial over a 5x5
lattice spanning the work extent, both ways, and reports the worst residual on a denser
check lattice. Display only: no saved coordinate passes through it.

A local grid is never pinned to a place: it gets ``kind="local"`` and the browser maps
metres to degrees at the equator around the work centre.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from pyproj import CRS, Geod, Transformer

MIN_HALF_EXTENT_M = 200.0
_GEOD = Geod(ellps="WGS84")


def _design(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones_like(u), u, v, u * u, u * v, v * v])


def _poly(c: np.ndarray, u: float | np.ndarray, v: float | np.ndarray) -> Any:
    return c[0] + c[1] * u + c[2] * v + c[3] * u * u + c[4] * u * v + c[5] * v * v


def local_view(e0: float, n0: float, extent: list[float] | None, name: str = "") -> dict[str, Any]:
    """The view transform of a local grid around ``(e0, n0)``."""
    return {
        "kind": "local",
        "epsg": None,
        "crs_name": name,
        "e0": e0,
        "n0": n0,
        "s": 1.0,
        "lon": [],
        "lat": [],
        "lon0": 0.0,
        "lat0": 0.0,
        "q": 1.0,
        "e": [],
        "n": [],
        "residual_mm": 0.0,
        "grid_north_bearing": 0.0,
        "extent": extent,
    }


def fit_view(epsg: int, e_min: float, n_min: float, e_max: float, n_max: float) -> dict[str, Any]:
    """Fit the polynomial view transform of a projected CRS over an extent.

    Raises:
        ValueError: when the CRS is not projected.
    """
    crs = CRS.from_epsg(int(epsg))
    if not crs.is_projected:
        raise ValueError(f"EPSG {epsg} is not a projected system")
    to_ll = Transformer.from_crs(crs, 4326, always_xy=True)
    to_grid = Transformer.from_crs(4326, crs, always_xy=True)
    e0, n0 = (e_min + e_max) / 2.0, (n_min + n_max) / 2.0
    s = max((e_max - e_min) / 2.0, (n_max - n_min) / 2.0, MIN_HALF_EXTENT_M)

    g = np.linspace(-1.0, 1.0, 5)
    uu, vv = (a.ravel() for a in np.meshgrid(g, g))
    lon, lat = (np.asarray(x) for x in to_ll.transform(e0 + uu * s, n0 + vv * s))
    a = _design(uu, vv)
    c_lon = np.linalg.lstsq(a, lon, rcond=None)[0]
    c_lat = np.linalg.lstsq(a, lat, rcond=None)[0]

    lon0, lat0 = (float(x) for x in to_ll.transform(e0, n0))
    q = float(max(np.abs(lon - lon0).max(), np.abs(lat - lat0).max())) or 1.0
    p, r = (lon - lon0) / q, (lat - lat0) / q
    b = _design(p, r)
    c_e = np.linalg.lstsq(b, e0 + uu * s, rcond=None)[0]
    c_n = np.linalg.lstsq(b, n0 + vv * s, rcond=None)[0]

    # Worst forward residual on a 9x9 check lattice, measured back on the grid.
    h = np.linspace(-1.0, 1.0, 9)
    cu, cv = (x.ravel() for x in np.meshgrid(h, h))
    fe, fn = to_grid.transform(_poly(c_lon, cu, cv), _poly(c_lat, cu, cv))
    residual_mm = float(np.hypot(np.asarray(fe) - (e0 + cu * s), np.asarray(fn) - (n0 + cv * s)).max() * 1000.0)

    north_lon, north_lat = to_ll.transform(e0, n0 + 100.0)
    az, _, _ = _GEOD.inv(lon0, lat0, float(north_lon), float(north_lat))
    bearing = ((float(az) + 180.0) % 360.0) - 180.0

    return {
        "kind": "polynomial",
        "epsg": int(epsg),
        "crs_name": crs.name,
        "e0": e0,
        "n0": n0,
        "s": s,
        "lon": [float(x) for x in c_lon],
        "lat": [float(x) for x in c_lat],
        "lon0": lon0,
        "lat0": lat0,
        "q": q,
        "e": [float(x) for x in c_e],
        "n": [float(x) for x in c_n],
        "residual_mm": round(residual_mm, 4) if math.isfinite(residual_mm) else 1e9,
        "grid_north_bearing": round(bearing, 8),
        "extent": [e_min, n_min, e_max, n_max],
    }


def to_view(dto: dict[str, Any], e: float, n: float) -> tuple[float, float]:
    """Apply a fitted transform (the same arithmetic as the browser)."""
    if dto["kind"] == "local":
        k = 111319.49
        return (e - dto["e0"]) / k, (n - dto["n0"]) / k
    u, v = (e - dto["e0"]) / dto["s"], (n - dto["n0"]) / dto["s"]
    return float(_poly(np.asarray(dto["lon"]), u, v)), float(_poly(np.asarray(dto["lat"]), u, v))


def to_grid(dto: dict[str, Any], lon: float, lat: float) -> tuple[float, float]:
    """Inverse of :func:`to_view` without the browser's Newton refinement."""
    if dto["kind"] == "local":
        k = 111319.49
        return dto["e0"] + lon * k, dto["n0"] + lat * k
    p, r = (lon - dto["lon0"]) / dto["q"], (lat - dto["lat0"]) / dto["q"]
    return float(_poly(np.asarray(dto["e"]), p, r)), float(_poly(np.asarray(dto["n"]), p, r))


__all__ = ["MIN_HALF_EXTENT_M", "fit_view", "local_view", "to_grid", "to_view"]
