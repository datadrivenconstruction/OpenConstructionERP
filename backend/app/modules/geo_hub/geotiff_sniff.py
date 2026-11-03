# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""GeoTIFF header sniffing for survey orthophotos.

:func:`sniff_geotiff` reads only the TIFF directory (dimensions, GeoTIFF tags)
with Pillow; it never decodes pixels. The georeferencing comes from three tags:

* 33550 ``ModelPixelScale``   - ground size of one pixel (sx, sy, sz)
* 33922 ``ModelTiepoint``     - (i, j, k, x, y, z) pins a pixel to a map position
* 34735 ``GeoKeyDirectory``   - carries the EPSG code (key 3072 projected,
  2048 geographic)

A file without usable tags is still a valid TIFF: the result has ``crs_epsg``
and ``bbox_wgs84`` set to ``None`` and a warning, and the caller decides.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from pathlib import Path
from struct import error as struct_error

from app.modules.geo_hub.raster_pipeline import ImagePixelBudgetExceeded

TAG_SAMPLES_PER_PIXEL = 277
TAG_TILE_WIDTH = 322
TAG_PIXEL_SCALE = 33550
TAG_TIEPOINT = 33922
TAG_GEOKEYS = 34735

_KEY_RASTER_TYPE = 1025
_KEY_GEOGRAPHIC = 2048
_KEY_PROJECTED = 3072
_KEY_LINEAR_UNITS = 3076
_USER_DEFINED = 32767
_METRES_PER_DEGREE = 111_320.0
_FOOT_METRES = {9002: 0.3048, 9003: 1200.0 / 3937.0}


class GeoTiffError(ValueError):
    """The bytes are not a TIFF we can read."""


@dataclass(frozen=True)
class GeoTiffMeta:
    """What the header says about a TIFF."""

    width: int
    height: int
    band_count: int
    is_cog: bool
    crs_epsg: int | None = None
    # (min_lon, min_lat, max_lon, max_lat) in WGS84 degrees.
    bbox_wgs84: tuple[float, float, float, float] | None = None
    gsd_m: float | None = None
    warnings: list[str] = field(default_factory=list)


def sniff_geotiff(source: bytes | str | Path) -> GeoTiffMeta:
    """Read a GeoTIFF header.

    Raises:
        GeoTiffError: not a readable TIFF (caller maps to HTTP 422).
        ImagePixelBudgetExceeded: the declared surface is above Pillow's pixel
            guard (caller maps to HTTP 413).
    """
    import warnings as _warnings

    from PIL import Image, UnidentifiedImageError

    fh = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else open(source, "rb")  # noqa: SIM115
    try:
        with _warnings.catch_warnings():
            _warnings.simplefilter("error", Image.DecompressionBombWarning)
            try:
                img = Image.open(fh)
            except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
                raise ImagePixelBudgetExceeded(str(exc)) from exc
            except (UnidentifiedImageError, OSError, SyntaxError, struct_error) as exc:
                raise GeoTiffError("not a readable TIFF") from exc
        with img:
            if img.format != "TIFF":
                raise GeoTiffError("not a TIFF file")
            width, height = img.size
            limit = Image.MAX_IMAGE_PIXELS
            if limit is not None and width * height > limit:
                raise ImagePixelBudgetExceeded(f"{width}x{height} exceeds the pixel budget")
            return _meta_from_image(img, width, height)
    finally:
        fh.close()


def _meta_from_image(img, width: int, height: int) -> GeoTiffMeta:  # noqa: ANN001
    tags = getattr(img, "tag_v2", None)
    get = (lambda k: tags.get(k)) if tags is not None else (lambda _k: None)

    bands = int(get(TAG_SAMPLES_PER_PIXEL) or len(img.getbands()) or 1)
    try:
        frames = int(getattr(img, "n_frames", 1) or 1)
    except Exception:  # noqa: BLE001 - a broken IFD chain is not fatal for a sniff
        frames = 1
    is_cog = get(TAG_TILE_WIDTH) is not None and frames > 1

    warns: list[str] = []
    scale = _floats(get(TAG_PIXEL_SCALE))
    tie = _floats(get(TAG_TIEPOINT))
    keys = _geokeys(get(TAG_GEOKEYS))
    epsg = _epsg(keys)

    if len(scale) < 2 or len(tie) < 6:
        warns.append("not_georeferenced")
        return GeoTiffMeta(width, height, bands, is_cog, None, None, None, warns)
    if epsg is None:
        warns.append("crs_unknown")
        return GeoTiffMeta(width, height, bands, is_cog, None, None, None, warns)

    sx, sy = abs(scale[0]), abs(scale[1])
    i, j, x, y = tie[0], tie[1], tie[3], tie[4]
    min_x, max_x = x + (0 - i) * sx, x + (width - i) * sx
    max_y, min_y = y - (0 - j) * sy, y - (height - j) * sy

    geographic = epsg in _GEOGRAPHIC_EPSG
    bbox = _to_wgs84(epsg, (min_x, min_y, max_x, max_y))
    if bbox is None:
        warns.append("crs_transform_unavailable")
        return GeoTiffMeta(width, height, bands, is_cog, epsg, None, _gsd(sx, geographic, None, keys), warns)
    mid_lat = (bbox[1] + bbox[3]) / 2
    return GeoTiffMeta(width, height, bands, is_cog, epsg, bbox, _gsd(sx, geographic, mid_lat, keys), warns)


def _gsd(sx: float, geographic: bool, mid_lat: float | None, keys: dict[int, int]) -> float | None:
    if geographic:
        if mid_lat is None:
            return None
        return sx * _METRES_PER_DEGREE * math.cos(math.radians(mid_lat))
    return sx * _FOOT_METRES.get(keys.get(_KEY_LINEAR_UNITS, 9001), 1.0)


def _floats(value) -> list[float]:  # noqa: ANN001
    if value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    try:
        return [float(v) for v in value]
    except (TypeError, ValueError):
        return []


def _geokeys(value) -> dict[int, int]:  # noqa: ANN001
    """Decode the GeoKeyDirectory into ``{key_id: value}`` for inline (location 0) keys."""
    raw = [int(v) for v in value] if value is not None else []
    if len(raw) < 4:
        return {}
    out: dict[int, int] = {}
    for n in range(min(raw[3], (len(raw) - 4) // 4)):
        key_id, location, _count, val = raw[4 + 4 * n : 8 + 4 * n]
        if location == 0:
            out[key_id] = val
    return out


def _epsg(keys: dict[int, int]) -> int | None:
    for key in (_KEY_PROJECTED, _KEY_GEOGRAPHIC):
        val = keys.get(key)
        if val is not None and val != _USER_DEFINED and 1000 <= val < 32767:
            return val
    return None


_GEOGRAPHIC_EPSG = frozenset({4326, 4258, 4269, 4283, 4617, 4674, 4167, 6318})


def _to_wgs84(epsg: int, box: tuple[float, float, float, float]) -> tuple[float, float, float, float] | None:
    """Transform a native bbox to WGS84, returning ``(min_lon, min_lat, max_lon, max_lat)``."""
    min_x, min_y, max_x, max_y = box
    corners = [(min_x, min_y), (min_x, max_y), (max_x, min_y), (max_x, max_y)]
    out: list[tuple[float, float]] = []
    for cx, cy in corners:
        if epsg in _GEOGRAPHIC_EPSG:
            lon, lat = cx, cy
        else:
            pt = _project(epsg, cx, cy)
            if pt is None:
                return None
            lon, lat = pt
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            return None
        out.append((lon, lat))
    lons, lats = [p[0] for p in out], [p[1] for p in out]
    return (min(lons), min(lats), max(lons), max(lats))


def _project(epsg: int, x: float, y: float) -> tuple[float, float] | None:
    from app.modules.geo_hub.coord_transforms import transform

    try:
        lon, lat, _ = transform(epsg, 4326, x, y, 0.0)
        return lon, lat
    except NotImplementedError:
        pass  # pyproj missing: UTM below needs no library
    except Exception:  # noqa: BLE001 - unknown EPSG for pyproj
        return None
    utm = _utm_zone(epsg)
    return _utm_inverse(x, y, *utm) if utm else None


def _utm_zone(epsg: int) -> tuple[int, bool] | None:
    """``(zone, south)`` for WGS84 UTM EPSG 32601-32660 / 32701-32760."""
    if 32601 <= epsg <= 32660:
        return epsg - 32600, False
    if 32701 <= epsg <= 32760:
        return epsg - 32700, True
    return None


def _utm_inverse(easting: float, northing: float, zone: int, south: bool) -> tuple[float, float]:
    """Transverse Mercator inverse (Krueger series, WGS84), accurate to centimetres."""
    a, f = 6378137.0, 1 / 298.257223563
    k0 = 0.9996
    n = f / (2 - f)
    big_a = a / (1 + n) * (1 + n**2 / 4 + n**4 / 64)
    beta = [
        n / 2 - 2 * n**2 / 3 + 37 * n**3 / 96,
        n**2 / 48 + n**3 / 15,
        17 * n**3 / 480,
    ]
    delta = [
        2 * n - 2 * n**2 / 3 - 2 * n**3,
        7 * n**2 / 3 - 8 * n**3 / 5,
        56 * n**3 / 15,
    ]
    xi = (northing - (10_000_000.0 if south else 0.0)) / (k0 * big_a)
    eta = (easting - 500_000.0) / (k0 * big_a)
    xi_p = xi - sum(b * math.sin(2 * (j + 1) * xi) * math.cosh(2 * (j + 1) * eta) for j, b in enumerate(beta))
    eta_p = eta - sum(b * math.cos(2 * (j + 1) * xi) * math.sinh(2 * (j + 1) * eta) for j, b in enumerate(beta))
    chi = math.asin(math.sin(xi_p) / math.cosh(eta_p))
    lat = chi + sum(d * math.sin(2 * (j + 1) * chi) for j, d in enumerate(delta))
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    lon = lon0 + math.atan2(math.sinh(eta_p), math.cos(xi_p))
    return math.degrees(lon), math.degrees(lat)
