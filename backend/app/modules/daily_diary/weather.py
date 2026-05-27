"""‌⁠‍Real weather ingestion for the daily-diary module.

This module fetches actual weather observations from the public, free,
no-API-key-required `Open-Meteo <https://open-meteo.com>`_ API.

It is also responsible for the **productivity factor** calculator —
mapping observed weather into trade-specific work-loss coefficients per
the UK SCL Delay & Disruption Protocol Annex C and standard concrete /
finishes practice (ACI 305R, ACI 306R, EN 13670, BS 8110).

All HTTP calls are wrapped in ``asyncio.wait_for`` with a hard 8-second
timeout so a flaky upstream cannot stall the diary pipeline. Failures
return :data:`None` — callers fall back to the most recent local
:class:`WeatherRecord`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


_OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_OPEN_METEO_HISTORICAL_URL = "https://archive-api.open-meteo.com/v1/archive"
_HTTP_TIMEOUT_SECONDS = 8.0

# Open-Meteo WMO weather codes → (conditions_code, human-readable text)
# Per WMO 4677 / Open-Meteo documentation.
_OPEN_METEO_WEATHER_CODES: dict[int, tuple[str, str]] = {
    0: ("clear", "Clear sky"),
    1: ("mainly_clear", "Mainly clear"),
    2: ("partly_cloudy", "Partly cloudy"),
    3: ("overcast", "Overcast"),
    45: ("fog", "Fog"),
    48: ("fog_rime", "Depositing rime fog"),
    51: ("drizzle_light", "Light drizzle"),
    53: ("drizzle_moderate", "Moderate drizzle"),
    55: ("drizzle_dense", "Dense drizzle"),
    56: ("freezing_drizzle_light", "Light freezing drizzle"),
    57: ("freezing_drizzle_dense", "Dense freezing drizzle"),
    61: ("rain_light", "Light rain"),
    63: ("rain_moderate", "Moderate rain"),
    65: ("rain_heavy", "Heavy rain"),
    66: ("freezing_rain_light", "Light freezing rain"),
    67: ("freezing_rain_heavy", "Heavy freezing rain"),
    71: ("snow_light", "Light snowfall"),
    73: ("snow_moderate", "Moderate snowfall"),
    75: ("snow_heavy", "Heavy snowfall"),
    77: ("snow_grains", "Snow grains"),
    80: ("rain_showers_light", "Light rain showers"),
    81: ("rain_showers_moderate", "Moderate rain showers"),
    82: ("rain_showers_violent", "Violent rain showers"),
    85: ("snow_showers_light", "Light snow showers"),
    86: ("snow_showers_heavy", "Heavy snow showers"),
    95: ("thunderstorm", "Thunderstorm"),
    96: ("thunderstorm_hail_light", "Thunderstorm with light hail"),
    99: ("thunderstorm_hail_heavy", "Thunderstorm with heavy hail"),
}


def _classify_conditions(code: int | None) -> tuple[str | None, str | None]:
    if code is None:
        return None, None
    return _OPEN_METEO_WEATHER_CODES.get(int(code), ("unknown", "Unknown"))


def _build_forecast_url(lat: float, lng: float, target: date) -> str:
    """‌⁠‍Build the Open-Meteo forecast URL for a specific date."""
    params = {
        "latitude": f"{lat:.6f}",
        "longitude": f"{lng:.6f}",
        "hourly": ("temperature_2m,relativehumidity_2m,precipitation,weathercode,windspeed_10m"),
        "daily": "sunrise,sunset",
        "timezone": "UTC",
        "start_date": target.isoformat(),
        "end_date": target.isoformat(),
    }
    return f"{_OPEN_METEO_FORECAST_URL}?{urllib.parse.urlencode(params)}"


def _build_historical_url(lat: float, lng: float, target: date) -> str:
    """‌⁠‍Build the Open-Meteo archive URL for a historical date."""
    params = {
        "latitude": f"{lat:.6f}",
        "longitude": f"{lng:.6f}",
        "hourly": ("temperature_2m,relativehumidity_2m,precipitation,weathercode,windspeed_10m"),
        "daily": "sunrise,sunset",
        "timezone": "UTC",
        "start_date": target.isoformat(),
        "end_date": target.isoformat(),
    }
    return f"{_OPEN_METEO_HISTORICAL_URL}?{urllib.parse.urlencode(params)}"


def _do_get(url: str) -> dict[str, Any] | None:
    """Blocking GET — wrapped in :func:`asyncio.to_thread` by the async caller."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "OpenConstructionERP/daily-diary"},
        )
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return json.loads(resp.read().decode(charset))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        logger.info("Open-Meteo fetch failed for %s: %s", url, exc)
        return None
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Open-Meteo fetch unexpected error: %s", exc)
        return None


def _summarise_open_meteo(
    payload: dict[str, Any],
    target: date,
) -> dict[str, Any] | None:
    """Reduce an Open-Meteo hourly payload to a single daily summary."""
    hourly = payload.get("hourly") or {}
    times: list[str] = hourly.get("time") or []
    if not times:
        return None

    temps = hourly.get("temperature_2m") or []
    hums = hourly.get("relativehumidity_2m") or []
    precs = hourly.get("precipitation") or []
    codes = hourly.get("weathercode") or []
    winds = hourly.get("windspeed_10m") or []

    def _avg(values: list[Any]) -> float | None:
        nums = [float(v) for v in values if v is not None]
        return sum(nums) / len(nums) if nums else None

    def _max(values: list[Any]) -> float | None:
        nums = [float(v) for v in values if v is not None]
        return max(nums) if nums else None

    def _sum(values: list[Any]) -> float | None:
        nums = [float(v) for v in values if v is not None]
        return sum(nums) if nums else None

    avg_temp = _avg(temps)
    avg_hum = _avg(hums)
    total_prec = _sum(precs)
    max_wind = _max(winds)

    # Dominant weather code = the one occurring most frequently in the day
    dominant_code: int | None = None
    if codes:
        from collections import Counter

        cnt = Counter(int(c) for c in codes if c is not None)
        if cnt:
            dominant_code = cnt.most_common(1)[0][0]
    conditions_code, conditions_text = _classify_conditions(dominant_code)

    daily = payload.get("daily") or {}
    sunrise = (daily.get("sunrise") or [None])[0]
    sunset = (daily.get("sunset") or [None])[0]

    # Rain hours = number of hourly buckets with precipitation > 0.1 mm
    rain_hours = 0
    for p in precs:
        try:
            if p is not None and float(p) > 0.1:
                rain_hours += 1
        except (TypeError, ValueError):
            continue

    # Reasonable bounds — return None if everything is missing
    if avg_temp is None and avg_hum is None and total_prec is None and dominant_code is None:
        return None

    return {
        "captured_at": datetime.combine(target, datetime.min.time()).isoformat() + "Z",
        "source": "open_meteo",
        "temperature_c": (Decimal(str(round(avg_temp, 2))) if avg_temp is not None else None),
        "humidity_pct": (Decimal(str(round(avg_hum, 2))) if avg_hum is not None else None),
        "wind_speed_kmh": (Decimal(str(round(max_wind, 2))) if max_wind is not None else None),
        "precipitation_mm": (Decimal(str(round(total_prec, 2))) if total_prec is not None else None),
        "conditions_code": conditions_code,
        "conditions_text": conditions_text,
        "sunrise": sunrise,
        "sunset": sunset,
        "rain_hours": rain_hours,
    }


async def fetch_weather_for_day(
    lat: float,
    lng: float,
    target: date,
) -> dict[str, Any] | None:
    """Fetch a daily-summary weather observation from Open-Meteo.

    Returns ``None`` if the upstream fails or returns an unusable payload.
    Tries the forecast endpoint first; if the requested date is in the
    archive window (≥5 days old) it falls back to the historical archive.

    All blocking I/O runs through :func:`asyncio.to_thread` so the event
    loop is never frozen.
    """
    today = date.today()
    use_archive = (today - target) >= timedelta(days=5)
    url = _build_historical_url(lat, lng, target) if use_archive else _build_forecast_url(lat, lng, target)

    try:
        payload = await asyncio.wait_for(
            asyncio.to_thread(_do_get, url),
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.info("Open-Meteo request timed out for %s", url)
        return None

    if not payload:
        return None
    summary = _summarise_open_meteo(payload, target)
    if summary is not None:
        summary["location_lat"] = lat
        summary["location_lng"] = lng
    return summary


# ── Productivity factor (trade-aware) ─────────────────────────────────────


# SCL Protocol Annex C / ACI 305R-20 / ACI 306R-16 / EN 13670 / BS 8110
# Each entry is (rain mm/h threshold, temp-low °C, temp-high °C, productivity %).
# Productivity is the *remaining* fraction of nominal output (1.0 = full).
# Values are calibrated to the standard "wet-trade vs dry-trade" rule:
#   * Wet concrete pour: any rain >2mm/h or temp <5°C / >35°C → effectively stopped (0%)
#   * Steel erection: high winds (>40km/h) → stopped (0%)
#   * Roofing & waterproofing: any rain → stopped (0%)
#   * External masonry: rain >5mm/h → stopped (0%); cold (<5°C) → 50%
#   * Sitework / excavation: heavy rain (>10mm/h) → 20%; light rain → 80%
#   * Interior finishes: only stopped if no temporary roof
#   * MEP rough-in: minimal weather sensitivity (>95%)
_TRADE_RULES: dict[str, dict[str, Any]] = {
    "concrete": {
        "rain_stop_mm_h": 2.0,
        "temp_min_c": 5.0,
        "temp_max_c": 35.0,
        "wind_stop_kmh": 60.0,
        "rain_loss_per_hour": 1.0,
    },
    "roofing": {
        "rain_stop_mm_h": 0.5,
        "temp_min_c": 2.0,
        "temp_max_c": 45.0,
        "wind_stop_kmh": 40.0,
        "rain_loss_per_hour": 1.0,
    },
    "waterproofing": {
        "rain_stop_mm_h": 0.5,
        "temp_min_c": 5.0,
        "temp_max_c": 45.0,
        "wind_stop_kmh": 40.0,
        "rain_loss_per_hour": 1.0,
    },
    "external_masonry": {
        "rain_stop_mm_h": 5.0,
        "temp_min_c": 2.0,
        "temp_max_c": 40.0,
        "wind_stop_kmh": 50.0,
        "rain_loss_per_hour": 0.8,
    },
    "steel_erection": {
        "rain_stop_mm_h": 5.0,
        "temp_min_c": -10.0,
        "temp_max_c": 40.0,
        "wind_stop_kmh": 40.0,
        "rain_loss_per_hour": 0.4,
    },
    "earthworks": {
        "rain_stop_mm_h": 10.0,
        "temp_min_c": -5.0,
        "temp_max_c": 45.0,
        "wind_stop_kmh": 60.0,
        "rain_loss_per_hour": 0.8,
    },
    "sitework": {
        "rain_stop_mm_h": 15.0,
        "temp_min_c": -5.0,
        "temp_max_c": 45.0,
        "wind_stop_kmh": 60.0,
        "rain_loss_per_hour": 0.8,
    },
    "finishes_interior": {
        "rain_stop_mm_h": 999.0,  # not weather sensitive (assumes dry envelope)
        "temp_min_c": -20.0,
        "temp_max_c": 50.0,
        "wind_stop_kmh": 999.0,
        "rain_loss_per_hour": 0.3,
    },
    "mep_roughin": {
        "rain_stop_mm_h": 999.0,
        "temp_min_c": -20.0,
        "temp_max_c": 50.0,
        "wind_stop_kmh": 999.0,
        "rain_loss_per_hour": 0.05,
    },
}


def list_supported_trades() -> list[str]:
    """Return the list of trades supported by :func:`compute_productivity_factor`."""
    return list(_TRADE_RULES.keys())


def compute_productivity_factor(
    *,
    trade: str,
    rain_hours: int = 0,
    precipitation_mm: float | Decimal | None = None,
    temperature_c: float | Decimal | None = None,
    wind_speed_kmh: float | Decimal | None = None,
    working_hours: int = 8,
) -> dict[str, Any]:
    """Compute the productivity factor for a trade on a given day.

    Args:
        trade: One of the values returned by :func:`list_supported_trades`.
            Unknown trades fall back to ``sitework``.
        rain_hours: Number of hours within the working day with measurable
            precipitation. Default 0.
        precipitation_mm: Total precipitation across the working day
            (mm). Used to determine mean rain intensity.
        temperature_c: Mean / representative air temperature in °C.
        wind_speed_kmh: Maximum sustained wind speed in km/h.
        working_hours: Length of the work shift in hours.

    Returns:
        ``{"trade": str, "factor": Decimal (0..1), "stopped": bool,
        "reason": str, "lost_hours": Decimal}``.
    """
    rules = _TRADE_RULES.get(trade) or _TRADE_RULES["sitework"]
    rh = max(0, int(rain_hours))
    wh = max(1, int(working_hours))
    rain_mean_mm_h: float | None = None
    if precipitation_mm is not None and rh > 0:
        rain_mean_mm_h = float(precipitation_mm) / max(rh, 1)

    reason_parts: list[str] = []
    stopped = False

    # Hard stops first — any one stop condition pegs productivity to 0.
    if temperature_c is not None:
        t = float(temperature_c)
        if t < float(rules["temp_min_c"]):
            reason_parts.append(f"temperature {t}°C below threshold {rules['temp_min_c']}°C")
            stopped = True
        elif t > float(rules["temp_max_c"]):
            reason_parts.append(f"temperature {t}°C above threshold {rules['temp_max_c']}°C")
            stopped = True
    if wind_speed_kmh is not None:
        w = float(wind_speed_kmh)
        if w > float(rules["wind_stop_kmh"]):
            reason_parts.append(f"wind {w}km/h above threshold {rules['wind_stop_kmh']}km/h")
            stopped = True
    if rain_mean_mm_h is not None and rain_mean_mm_h > float(rules["rain_stop_mm_h"]):
        reason_parts.append(f"rain {rain_mean_mm_h:.1f}mm/h above threshold {rules['rain_stop_mm_h']}mm/h")
        stopped = True

    if stopped:
        return {
            "trade": trade,
            "factor": Decimal("0.00"),
            "stopped": True,
            "reason": "; ".join(reason_parts) or "stop condition triggered",
            "lost_hours": Decimal(str(wh)),
        }

    # Otherwise apply gradient loss based on rain hours.
    loss = float(rules["rain_loss_per_hour"]) * min(rh, wh)
    factor = max(0.0, 1.0 - (loss / wh))
    lost_hours = wh * (1.0 - factor)
    reason = (
        f"{rh}h of rain × loss-coefficient {rules['rain_loss_per_hour']}" if rh > 0 else "no significant weather impact"
    )

    return {
        "trade": trade,
        "factor": Decimal(str(round(factor, 4))),
        "stopped": False,
        "reason": reason,
        "lost_hours": Decimal(str(round(lost_hours, 2))),
    }


# ── EXIF GPS extraction ───────────────────────────────────────────────────


def _exif_to_decimal(value: tuple[Any, ...], ref: str) -> float | None:
    """Convert an EXIF GPS ratio triple to decimal degrees.

    EXIF stores latitude/longitude as a tuple of three rational-number
    triples ``((d_num, d_den), (m_num, m_den), (s_num, s_den))``. The
    Pillow ``IFDRational`` already coerces these to floats so we accept
    either form.
    """
    if not value or len(value) != 3:
        return None
    try:
        deg = float(value[0])
        mins = float(value[1])
        secs = float(value[2])
    except (TypeError, ValueError):
        return None
    decimal = deg + (mins / 60.0) + (secs / 3600.0)
    if (ref or "").upper() in ("S", "W"):
        decimal = -decimal
    return decimal


def extract_exif_gps(image_bytes: bytes) -> dict[str, Any] | None:
    """Extract GPS metadata from a JPEG/HEIC image's EXIF tags.

    Returns a dict with ``lat``, ``lng`` and optionally ``altitude_m``
    and ``timestamp``. Returns ``None`` if no GPS data is present or
    Pillow is not available.

    Pillow is an optional dependency in this codebase; the function is
    a graceful no-op when it is absent.
    """
    if not image_bytes:
        return None

    try:
        from io import BytesIO

        from PIL import ExifTags, Image
    except ImportError:
        logger.info("Pillow not installed — EXIF GPS extraction skipped")
        return None

    try:
        img = Image.open(BytesIO(image_bytes))
        exif = img.getexif() if hasattr(img, "getexif") else None
        if not exif:
            return None
        gps_ifd_tag = next(
            (k for k, v in ExifTags.TAGS.items() if v == "GPSInfo"),
            None,
        )
        if gps_ifd_tag is None:
            return None
        gps_info = exif.get_ifd(gps_ifd_tag) or {}
        if not gps_info:
            return None
        decoded: dict[str, Any] = {}
        for k, v in gps_info.items():
            decoded[ExifTags.GPSTAGS.get(k, k)] = v

        lat_val = decoded.get("GPSLatitude")
        lat_ref = decoded.get("GPSLatitudeRef") or "N"
        lng_val = decoded.get("GPSLongitude")
        lng_ref = decoded.get("GPSLongitudeRef") or "E"
        if not lat_val or not lng_val:
            return None
        lat = _exif_to_decimal(tuple(lat_val), str(lat_ref))
        lng = _exif_to_decimal(tuple(lng_val), str(lng_ref))
        if lat is None or lng is None:
            return None
        # Validate ranges
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
            return None

        out: dict[str, Any] = {"lat": round(lat, 7), "lng": round(lng, 7)}
        alt_val = decoded.get("GPSAltitude")
        alt_ref = decoded.get("GPSAltitudeRef")
        if alt_val is not None:
            try:
                altitude = float(alt_val)
                if alt_ref in (1, b"\x01", "1"):
                    altitude = -altitude
                out["altitude_m"] = round(altitude, 2)
            except (TypeError, ValueError):
                pass
        ts = decoded.get("GPSTimeStamp")
        ds = decoded.get("GPSDateStamp")
        if ts and ds:
            try:
                t_h, t_m, t_s = (int(float(x)) for x in ts)
                out["timestamp"] = f"{ds.replace(':', '-')}T{t_h:02d}:{t_m:02d}:{t_s:02d}Z"
            except (TypeError, ValueError):
                pass
        return out
    except Exception as exc:
        logger.debug("EXIF GPS extraction failed: %s", exc)
        return None
