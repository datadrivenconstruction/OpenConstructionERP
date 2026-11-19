# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost code catalogues from ``country_data/central_purchasing.json``.

The module is neutral; a market only contributes the labels of its cost code standard
(DIN 276, MasterFormat, NRM 1). A country no entry names contributes nothing, and the
buyer types the code free-hand.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FILE = Path(__file__).resolve().parents[2] / "core" / "country_data" / "central_purchasing.json"


@lru_cache(maxsize=1)
def _markets() -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("central_purchasing: %s unreadable, no cost code catalogues", _FILE.name)
        return {}
    return {str(k).upper(): v for k, v in (raw.get("markets") or {}).items() if isinstance(v, dict)}


def catalogue_for(country: str | None) -> dict[str, Any] | None:
    """The catalogue a country contributes, ``{"standard", "label", "codes"}``, or ``None``."""
    data = _markets()
    entry = data.get(str(country or "").strip().upper())
    if entry is None:
        return None
    codes = entry.get("codes")
    if codes is None and entry.get("inherit"):
        codes = (data.get(str(entry["inherit"]).upper()) or {}).get("codes")
    return {"standard": entry.get("standard"), "label": entry.get("label"), "codes": list(codes or [])}


def catalogues_for(countries: list[str | None]) -> list[dict[str, Any]]:
    """One catalogue per standard the given countries use, in the order first met."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for country in countries:
        cat = catalogue_for(country)
        if cat is None or cat["standard"] in seen:
            continue
        seen.add(str(cat["standard"]))
        out.append({**cat, "countries": [str(country).upper()]})
    return out
