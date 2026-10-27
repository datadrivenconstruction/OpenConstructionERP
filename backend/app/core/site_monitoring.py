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
    "Limit",
    "emission_class_meets",
    "fuel_co2_kg_per_l",
    "inspection_interval_days",
    "limit_for",
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


def sensor_limit(country: str | None, kind: str, at: time | None = None) -> Limit | None:
    """The limit for a sensor kind, the night figure outside working hours where one exists."""
    key = _SENSOR_KEYS.get(kind)
    if key is None:
        return None
    if kind == "noise" and at is not None:
        span = working_hours(country)
        if span and not _in_hours(span, at):
            night = limit_for(country, "noise_dba_night")
            if night is not None:
                return night
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
