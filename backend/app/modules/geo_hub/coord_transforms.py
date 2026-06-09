# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Coordinate-reference-system helpers.

Tiny pure-Python coord-transform layer used by the tile pipeline. We
deliberately avoid forcing a hard dependency on ``pyproj``: the
construction-ERP installer should stay LIGHTWEIGHT. ``pyproj`` is a
~30 MB wheel and pulls PROJ shared libraries that bite on Windows.

What we ship out of the box:

* WGS84 <-> ECEF (earth-centred earth-fixed Cartesian metres). Pure
  numpy-free Python - the formulas are short and well-known.
* WGS84 <-> Web Mercator (EPSG 3857). Pure Python.
* WGS84 <-> local ENU (east-north-up tangent plane at an anchor). Used
  to place a tile relative to its Cesium-native bounding volume.
* A ``transform(src_epsg, dst_epsg, x, y, z)`` umbrella that picks the
  right pair above OR - if ``pyproj`` is importable - falls through to
  it for anything more exotic (UTM, ETRS89, ...).

This keeps the common path (WGS84 + Web Mercator) working in a 4 GB
VPS that doesn't have PROJ libs installed, while letting power users
opt in to ``pip install openconstructionerp[geo]`` for the full set.
"""

from __future__ import annotations

import math
from typing import Iterable

# WGS84 ellipsoid constants.
_A = 6_378_137.0  # semi-major axis in metres
_F = 1.0 / 298.257_223_563  # flattening
_B = _A * (1.0 - _F)  # semi-minor axis in metres
_E2 = 1.0 - (_B / _A) ** 2  # eccentricity squared


def _has_pyproj() -> bool:
    try:  # pragma: no cover - depends on installer
        import pyproj  # noqa: F401

        return True
    except ImportError:
        return False


# ── WGS84 (geographic) <-> ECEF (Cartesian) ─────────────────────────────


def wgs84_to_ecef(
    lat_deg: float,
    lon_deg: float,
    alt_m: float = 0.0,
) -> tuple[float, float, float]:
    """Convert WGS84 (lat, lon, alt) -> ECEF (X, Y, Z) in metres.

    Standard formulas - see e.g. *Vermeille, "Direct transformation
    from geocentric coordinates to geodetic coordinates", 2002*.
    """
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    n = _A / math.sqrt(1.0 - _E2 * sin_lat * sin_lat)
    x = (n + alt_m) * cos_lat * math.cos(lon)
    y = (n + alt_m) * cos_lat * math.sin(lon)
    z = (n * (1.0 - _E2) + alt_m) * sin_lat
    return x, y, z


def ecef_to_wgs84(
    x: float,
    y: float,
    z: float,
) -> tuple[float, float, float]:
    """ECEF (m) -> WGS84 (lat_deg, lon_deg, alt_m) - Bowring's method.

    Closed-form approximation accurate to a few millimetres at the
    surface; perfectly fine for siting a tile bounding box.
    """
    lon = math.atan2(y, x)
    p = math.sqrt(x * x + y * y)
    # Initial parametric latitude.
    theta = math.atan2(z * _A, p * _B)
    sin_t = math.sin(theta)
    cos_t = math.cos(theta)
    lat = math.atan2(
        z + (_E2 * _B / (1.0 - _E2)) * sin_t * sin_t * sin_t,
        p - _E2 * _A * cos_t * cos_t * cos_t,
    )
    sin_lat = math.sin(lat)
    n = _A / math.sqrt(1.0 - _E2 * sin_lat * sin_lat)
    alt = p / math.cos(lat) - n
    return math.degrees(lat), math.degrees(lon), alt


# ── WGS84 <-> Web Mercator (EPSG 3857) ──────────────────────────────────

# Web Mercator's clamp to ±85.05112878° latitude is the Mercator pole-
# avoidance limit (the standard).
_MERC_LAT_CLAMP = 85.051_128_78
_ORIGIN_SHIFT = 2.0 * math.pi * _A / 2.0  # = pi * A; "meters per 180°"


def wgs84_to_web_mercator(lat_deg: float, lon_deg: float) -> tuple[float, float]:
    """WGS84 (lat, lon) -> EPSG 3857 (x, y) in metres."""
    lat = max(-_MERC_LAT_CLAMP, min(_MERC_LAT_CLAMP, lat_deg))
    x = lon_deg * _ORIGIN_SHIFT / 180.0
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) * _ORIGIN_SHIFT / math.pi
    return x, y


def web_mercator_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """EPSG 3857 (x, y) -> WGS84 (lat_deg, lon_deg)."""
    lon = x / _ORIGIN_SHIFT * 180.0
    lat = math.degrees(2.0 * math.atan(math.exp(y * math.pi / _ORIGIN_SHIFT))) - 90.0
    return lat, lon


# ── Local ENU (east-north-up tangent plane) ─────────────────────────────


def ecef_to_enu(
    x: float,
    y: float,
    z: float,
    ref_lat_deg: float,
    ref_lon_deg: float,
    ref_alt_m: float = 0.0,
) -> tuple[float, float, float]:
    """Rotate ECEF deltas into the local east-north-up frame at the anchor."""
    ref_ecef = wgs84_to_ecef(ref_lat_deg, ref_lon_deg, ref_alt_m)
    dx = x - ref_ecef[0]
    dy = y - ref_ecef[1]
    dz = z - ref_ecef[2]
    lat = math.radians(ref_lat_deg)
    lon = math.radians(ref_lon_deg)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)
    east = -sin_lon * dx + cos_lon * dy
    north = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
    up = cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz
    return east, north, up


def enu_to_ecef(
    east: float,
    north: float,
    up: float,
    ref_lat_deg: float,
    ref_lon_deg: float,
    ref_alt_m: float = 0.0,
) -> tuple[float, float, float]:
    """Inverse of :func:`ecef_to_enu` - local ENU back to ECEF."""
    ref_ecef = wgs84_to_ecef(ref_lat_deg, ref_lon_deg, ref_alt_m)
    lat = math.radians(ref_lat_deg)
    lon = math.radians(ref_lon_deg)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)
    x = -sin_lon * east - sin_lat * cos_lon * north + cos_lat * cos_lon * up + ref_ecef[0]
    y = cos_lon * east - sin_lat * sin_lon * north + cos_lat * sin_lon * up + ref_ecef[1]
    z = cos_lat * north + sin_lat * up + ref_ecef[2]
    return x, y, z


# ── Umbrella entry point ────────────────────────────────────────────────


def transform(
    src_epsg: int,
    dst_epsg: int,
    x: float,
    y: float,
    z: float = 0.0,
) -> tuple[float, float, float]:
    """Transform one (x, y, z) triple between two EPSG codes.

    Axis convention is lon, lat (``always_xy``): for geographic EPSG 4326
    ``x`` is longitude and ``y`` is latitude, both in degrees. This matches
    the ``always_xy=True`` pyproj fallback so the built-in fast paths and
    the library path agree on argument order.

    Supports the common WGS84 / Web Mercator / ECEF pairs without any
    external library. Falls through to ``pyproj`` if available for
    anything else (UTM zones, ETRS89, ...). Raises ``NotImplementedError``
    when we have neither a built-in path nor pyproj installed.
    """
    if src_epsg == dst_epsg:
        return x, y, z

    # Built-in fast paths first. Geographic 4326 is (lon=x, lat=y).
    if src_epsg == 4326 and dst_epsg == 3857:
        ex, ey = wgs84_to_web_mercator(lat_deg=y, lon_deg=x)
        return ex, ey, z
    if src_epsg == 3857 and dst_epsg == 4326:
        lat, lon = web_mercator_to_wgs84(x, y)
        return lon, lat, z
    if src_epsg == 4326 and dst_epsg == 4978:  # ECEF
        ex, ey, ez = wgs84_to_ecef(lat_deg=y, lon_deg=x, alt_m=z)
        return ex, ey, ez
    if src_epsg == 4978 and dst_epsg == 4326:
        lat, lon, alt = ecef_to_wgs84(x, y, z)
        return lon, lat, alt

    if _has_pyproj():  # pragma: no cover - installer-dependent
        import pyproj

        transformer = pyproj.Transformer.from_crs(
            src_epsg,
            dst_epsg,
            always_xy=True,
        )
        nx, ny, nz = transformer.transform(x, y, z)
        return nx, ny, nz

    raise NotImplementedError(
        f"transform({src_epsg} -> {dst_epsg}) requires pyproj - install openconstructionerp[geo] to enable it",
    )


def project_points(
    src_epsg: int,
    dst_epsg: int,
    points: Iterable[tuple[float, float, float]],
) -> list[tuple[float, float, float]]:
    """Vectorised wrapper around :func:`transform`. Pure-Python loop.

    Shares the lon, lat (``always_xy``) axis convention of :func:`transform`.
    """
    return [transform(src_epsg, dst_epsg, x, y, z) for (x, y, z) in points]


__all__ = [
    "ecef_to_enu",
    "ecef_to_wgs84",
    "enu_to_ecef",
    "project_points",
    "transform",
    "web_mercator_to_wgs84",
    "wgs84_to_ecef",
    "wgs84_to_web_mercator",
]
