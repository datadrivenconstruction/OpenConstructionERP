# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Country cadastre conventions from ``country_data/cadastre.json``, and the boundary point register.

Core holds no country value: the JSON names, per country, the parcel number
format (PAR-006), the area tolerance against the register (PAR-001) and the
boundary mark types. At startup each entry becomes a :class:`ParcelProfile`;
a pack that registers its own profile for the same country replaces it.
"""

from __future__ import annotations

import json
import logging
import math
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.modules.land_parcels.profiles import (
    _PROFILES,
    NEUTRAL,
    MarkType,
    ParcelProfile,
    k_mt_sqrt_area,
    register_parcel_profile,
)

logger = logging.getLogger(__name__)

DATA_PATH = Path(__file__).resolve().parents[2] / "core" / "country_data" / "cadastre.json"
#: Two corners of neighbouring parcels closer than this are one boundary point in the register, m.
SAME_POINT_M = 0.005


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("land_parcels: cadastre.json unreadable; neutral parcel profile only")
        return {}


def neutral_marks() -> tuple[MarkType, ...]:
    """The mark list offered where no country gives one."""
    rows = _data().get("_neutral_marks") or []
    return tuple(MarkType(key=str(r["key"]), monumented=bool(r.get("monumented"))) for r in rows) or NEUTRAL.marks


def profile_from_entry(country: str, entry: dict[str, Any]) -> ParcelProfile:
    """One JSON entry as a profile; missing fields keep the neutral values."""
    tol = entry.get("area_tolerance") or {}
    tolerance = None
    if tol.get("formula") == "k_mt_sqrt_area":
        tolerance = k_mt_sqrt_area(Decimal(str(tol["k"])), Decimal(str(tol["mt"])))
    marks = tuple(MarkType(key=str(r["key"]), monumented=bool(r.get("monumented"))) for r in entry.get("marks") or [])
    return ParcelProfile(
        country=country,
        id_label_key=entry.get("id_label_key") or NEUTRAL.id_label_key,
        id_label_default=entry.get("id_label_default") or NEUTRAL.id_label_default,
        id_pattern=entry.get("id_pattern") or "",
        id_example=entry.get("id_example") or "",
        area_tolerance=tolerance,
        area_tolerance_source=entry.get("area_tolerance_source") or "",
        marks=marks or neutral_marks(),
    )


def register_country_profiles() -> int:
    """Register a profile per country in the JSON unless a pack already registered one."""
    count = 0
    for code, entry in _data().items():
        if code.startswith("_") or not isinstance(entry, dict):
            continue
        if code.upper() in _PROFILES:
            continue
        register_parcel_profile(profile_from_entry(code.upper(), entry))
        count += 1
    return count


def boundary_point_register(parcels: list[dict[str, Any]], marks: tuple[MarkType, ...]) -> list[dict[str, Any]]:
    """One row per boundary point shared across parcels: number, E/N, mark, whether it is monumented.

    ``parcels`` rows carry ``ref`` and ``points`` (``label``, ``e``, ``n``, ``mark``,
    ``accuracy_m``, ``corner_status``). Corners with the same label, or within
    :data:`SAME_POINT_M` of each other, are one point; a conflicting mark is reported.
    """
    monumented = {m.key: m.monumented for m in marks}
    rows: list[dict[str, Any]] = []
    by_label: dict[str, dict[str, Any]] = {}
    for p in parcels:
        for pt in p.get("points") or []:
            e, n = float(pt["e"]), float(pt["n"])
            label = str(pt.get("label") or "").strip()
            row = by_label.get(label) if label else None
            if row is None:
                row = next(
                    (r for r in rows if math.hypot(r["e"] - e, r["n"] - n) <= SAME_POINT_M),
                    None,
                )
            if row is None:
                row = {
                    "point_no": label,
                    "e": e,
                    "n": n,
                    "mark": str(pt.get("mark") or ""),
                    "accuracy_m": pt.get("accuracy_m"),
                    "corner_status": str(pt.get("corner_status") or ""),
                    "parcels": [],
                    "mark_conflict": False,
                    "position_spread_m": 0.0,
                }
                rows.append(row)
                if label:
                    by_label[label] = row
            else:
                mark = str(pt.get("mark") or "")
                if mark and row["mark"] and mark != row["mark"]:
                    row["mark_conflict"] = True
                row["mark"] = row["mark"] or mark
                row["position_spread_m"] = max(row["position_spread_m"], math.hypot(row["e"] - e, row["n"] - n))
                if not row["point_no"] and label:
                    row["point_no"] = label
                    by_label[label] = row
            if p.get("ref") not in row["parcels"]:
                row["parcels"].append(p.get("ref"))
    for i, row in enumerate(rows, start=1):
        row["point_no"] = row["point_no"] or f"#{i}"
        row["monumented"] = monumented.get(row["mark"]) if row["mark"] else None
        row["position_spread_m"] = round(row["position_spread_m"], 4)
    return rows


__all__ = [
    "SAME_POINT_M",
    "boundary_point_register",
    "neutral_marks",
    "profile_from_entry",
    "register_country_profiles",
]
