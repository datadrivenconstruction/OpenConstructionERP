# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site monitoring​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ limits per country: noise, dust, vibration, working hours, emission classes.

Country-neutral engine over ``country_data/site_monitoring.json``. A metric a
country does not list has no known limit: the engine returns None and the
caller falls back to the device's own limit, never to another country's figure.

Standard library only. Nothing here may import from ``app.modules``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = [
    "DATA_PATH",
    "EMISSION_CLASS_RANK",
    "FREQUENCY_BANDS",
    "Limit",
    "emission_class_meets",
    "fuel_co2_kg_per_l",
    "inspection_interval_days",
    "limit_for",
    "night_noise_by_ordinance",
    "sensor_limit",
    "working_hours",
]

DATA_PATH = Path(__file__).resolve().parent / "country_data" / "site_monitoring.json"

#: Engine emission classes, ordered within one family from oldest to cleanest.
EMISSION_CLASS_RANK: dict[str, tuple[str, int]] = {
    "eu_stage_iiia": ("eu", 1),
    "eu_stage_iiib": ("eu", 2),
    "eu_stage_iv": ("eu", 3),
    "eu_stage_v": ("eu", 4),
    "us_epa_tier_3": ("us", 1),
    "us_epa_tier_4i": ("us", 2),
    "us_epa_tier_4f": ("us", 3),
    "cn_stage_iii": ("cn", 1),
    "cn_stage_iv": ("cn", 2),
    "electric": ("any", 99),
}

#: Sensor kind to the data key that limits it (day variant where there is one).
_SENSOR_KEYS = {
    "noise": "noise_dba_day",
    "dust_pm10": "dust_pm10_ugm3_24h",
    "vibration": "vibration_ppv_mms",
}


@dataclass(frozen=True)
class Limit:
    """One statutory figure with its provenance."""

    value: Decimal
    source: str
    confidence: str


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _row(country: str | None, key: str) -> dict[str, Any] | None:
    if not country:
        return None
    row = (_data().get("countries") or {}).get(country.upper(), {}).get(key)
    return row if isinstance(row, dict) else None


def limit_for(country: str | None, key: str) -> Limit | None:
    """The numeric limit ``key`` for ``country``, or None when the data has none."""
    row = _row(country, key)
    if row is None:
        return None
    try:
        value = Decimal(str(row["value"]))
    except (KeyError, ArithmeticError, ValueError):
        return None
    return Limit(value=value, source=str(row.get("source", "")), confidence=str(row.get("confidence", "M")))


def _in_hours(span: str, at: time) -> bool:
    start_s, end_s = span.split("-")
    start = time.fromisoformat(start_s)
    end = time.fromisoformat(end_s)
    return start <= at < end


def _noise_zone_limit(country: str | None, zone: str | None, night: bool) -> Limit | None:
    """The day or night figure of a noise zone (``noise_zones`` in the data), the country's default zone when blank."""
    data = (_data().get("countries") or {}).get((country or "").upper(), {})
    zones = data.get("noise_zones")
    if not isinstance(zones, dict):
        return None
    key = (zone or "").lower() or str(data.get("noise_zone_default", ""))
    row = zones.get(key)
    if not isinstance(row, dict):
        return None
    try:
        value = Decimal(str(row["night" if night else "day"]))
    except (KeyError, ArithmeticError, ValueError):
        return None
    source = f"{row.get('source', '')}, {'night' if night else 'day'}"
    return Limit(value=value, source=source, confidence=str(row.get("confidence", "H")))


#: Lower edge of each DIN 4150-3 frequency band, used when a reading carries no frequency.
FREQUENCY_BANDS: dict[str, float] = {"lt10": 1.0, "10_50": 10.0, "50_100": 50.0, "gt100": 100.0}


def _interpolate(points: list[list[float]], f: float) -> float:
    pts = sorted((float(x), float(y)) for x, y in points)
    if f <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        if f <= x1:
            return y0 + (y1 - y0) * (f - x0) / (x1 - x0)
    return pts[-1][1]


def _vibration_limit(
    country: str | None, building_class: str | None, frequency_hz: float | None, band: str | None
) -> Limit | None:
    """PPV limit from a frequency-dependent table (``vibration_by_frequency``), interpolated within a band."""
    data = (_data().get("countries") or {}).get((country or "").upper(), {})
    table = data.get("vibration_by_frequency")
    if not isinstance(table, dict):
        return None
    lines = table.get("lines") or {}
    line_key = (building_class or "") or str(table.get("default_line", ""))
    line = lines.get(line_key)
    if not isinstance(line, dict):
        return None
    f = frequency_hz if frequency_hz is not None and frequency_hz > 0 else FREQUENCY_BANDS.get(band or "", 1.0)
    value = _interpolate(line["points"], f)
    source = f"{table.get('source', '')} line {line_key} ({line.get('label', '')}), {f:g} Hz"
    return Limit(value=Decimal(str(round(value, 2))), source=source, confidence=str(table.get("confidence", "H")))


def limit_grading(country: str | None) -> dict[str, Any]:
    """How the country grades noise and vibration limits, for device forms.

    ``noise_zones`` and ``building_classes`` list the keys the country data grades by (empty where it
    does not); ``noise_source`` and ``vibration_source`` name the text the ungraded limit comes from.
    """
    data = (_data().get("countries") or {}).get((country or "").upper(), {})
    zones = data.get("noise_zones")
    table = data.get("vibration_by_frequency")
    lines = table.get("lines") if isinstance(table, dict) else None
    noise = sensor_limit(country, "noise")
    vibration = sensor_limit(country, "vibration")
    return {
        "noise_zones": sorted(zones) if isinstance(zones, dict) else [],
        "building_classes": sorted(lines) if isinstance(lines, dict) else [],
        "noise_source": noise.source if noise else "",
        "vibration_source": vibration.source if vibration else "",
    }


def night_noise_by_ordinance(country: str | None) -> bool:
    """True where the data says a local ordinance, not a national figure, sets the night noise limit."""
    row = _row(country, "noise_dba_night")
    return bool(row and row.get("ordinance"))


def sensor_limit(
    country: str | None,
    kind: str,
    at: time | None = None,
    *,
    zone: str | None = None,
    building_class: str | None = None,
    frequency_hz: float | None = None,
    band: str | None = None,
) -> Limit | None:
    """The limit for a sensor kind.

    Noise uses the device's zone where the country grades limits by zone, and
    the night figure outside working hours. Vibration uses the country's
    frequency-dependent table where it has one, for the device's building
    class and the reading's dominant frequency (else the lower edge of the
    device's band).
    """
    key = _SENSOR_KEYS.get(kind)
    if key is None:
        return None
    if kind == "noise":
        night = False
        if at is not None:
            span = working_hours(country)
            night = bool(span and not _in_hours(span, at))
        zoned = _noise_zone_limit(country, zone, night)
        if zoned is not None:
            return zoned
        if night:
            lim = limit_for(country, "noise_dba_night")
            if lim is not None:
                return lim
    if kind == "vibration":
        graded = _vibration_limit(country, building_class, frequency_hz, band)
        if graded is not None:
            return graded
    return limit_for(country, key)


def working_hours(country: str | None) -> str | None:
    """Permitted working hours as ``HH:MM-HH:MM``, or None when unknown."""
    row = _row(country, "working_hours")
    return str(row["value"]) if row and "value" in row else None


def inspection_interval_days(country: str | None, category: str) -> int | None:
    """Statutory inspection interval in days for an equipment category (``crane`` today)."""
    lim = limit_for(country, f"{category}_inspection_days")
    return int(lim.value) if lim is not None else None


def emission_class_meets(country: str | None, emission_class: str | None) -> bool | None:
    """True when the class meets the country minimum, None when either side is unknown."""
    row = _row(country, "emission_class_min")
    if row is None or not emission_class:
        return None
    have = EMISSION_CLASS_RANK.get(emission_class)
    need = EMISSION_CLASS_RANK.get(str(row.get("value")))
    if have is None or need is None:
        return None
    if have[0] == "any":
        return True
    if have[0] != need[0]:
        return None
    return have[1] >= need[1]


def fuel_co2_kg_per_l(fuel: str = "diesel") -> Decimal:
    """Combustion CO2 factor for a fuel in kg per litre (diesel when the fuel is unknown)."""
    table = _data().get("fuel_co2_kg_per_l") or {}
    row = table.get(fuel) or table["diesel"]
    return Decimal(str(row["value"]))
