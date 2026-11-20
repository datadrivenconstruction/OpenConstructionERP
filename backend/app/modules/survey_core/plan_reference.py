# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan conventions and feature code libraries per country, and the code grammar.

Data lives in ``core/country_data/survey_plan.json`` (conventions, paper, code libraries)
and ``survey_reference.json`` (``angle_unit``, ``linear_unit``). Nothing here names a country.

The code grammar mirrors ``frontend/src/features/survey-plan/engine/linework.ts``: a point
code is a library code, an optional string number and an optional ``ST``/``CL``/``END``
control suffix (``EP1``, ``EP1 ST``, ``BLD2CL``). The longest library code wins.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA = Path(__file__).resolve().parents[2] / "core" / "country_data"
PLAN_PATH = _DATA / "survey_plan.json"
REFERENCE_PATH = _DATA / "survey_reference.json"

#: Allowed values per convention key; anything else is dropped (same lists as units/conventions.ts).
CONVENTION_VALUES: dict[str, tuple[Any, ...]] = {
    "angleUnit": ("dms", "deg", "gon"),
    "directionFormat": ("azimuth", "quadrant"),
    "azimuthZero": ("north", "south"),
    "axis": ("EN", "NE", "XY", "YX"),
    "linearUnit": ("m", "ft", "ftUS"),
    "areaUnit": ("m2", "ha", "acre", "ft2"),
    "precision": ("mm", "cm", "0.01ft", "0.001ft"),
    "chainage": ("metric", "imperial", "km"),
    "distanceInput": ("grid", "ground"),
    "angleDecimals": (0, 1, 2),
}

LINE_KINDS = ("none", "open", "closed")
_CONTROL = re.compile(r"(?:^|[\s_./-]?)(ST|CL|END)$", re.IGNORECASE)


@lru_cache(maxsize=1)
def _plan_data() -> dict[str, Any]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _reference() -> dict[str, Any]:
    return json.loads(REFERENCE_PATH.read_text(encoding="utf-8")).get("countries", {})


def clean_conventions(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only known keys with allowed values."""
    out: dict[str, Any] = {}
    for key, value in (raw or {}).items():
        allowed = CONVENTION_VALUES.get(key)
        if allowed is not None and value in allowed:
            out[key] = value
    return out


def country_conventions(country: str | None) -> tuple[dict[str, Any], str]:
    """Full conventions for a country and their source (``country`` or ``neutral``)."""
    data = _plan_data()
    conv = {"angleUnit": "dms", "linearUnit": "m", **data["neutral"]["conventions"]}
    code = (country or "").strip().upper()
    ref = _reference().get(code) or {}
    entry = data["countries"].get(code) or {}
    if not ref and not entry:
        return clean_conventions(conv), "neutral"
    if ref.get("angle_unit") in CONVENTION_VALUES["angleUnit"]:
        conv["angleUnit"] = ref["angle_unit"]
    if ref.get("linear_unit") in CONVENTION_VALUES["linearUnit"]:
        conv["linearUnit"] = ref["linear_unit"]
    conv.update(clean_conventions(entry.get("conventions")))
    if (
        conv["linearUnit"] != "m"
        and conv["precision"] in ("mm", "cm")
        and "precision" not in entry.get("conventions", {})
    ):
        conv["precision"] = "0.01ft"
    return conv, "country"


def country_codes(country: str | None) -> list[dict[str, Any]] | None:
    """A country's own code library, or ``None`` when the data has none for it."""
    entry = _plan_data()["countries"].get((country or "").strip().upper()) or {}
    codes = entry.get("codes")
    return [dict(c) for c in codes] if codes else None


def neutral_codes() -> list[dict[str, Any]]:
    return [dict(c) for c in _plan_data()["neutral"]["codes"]]


def library_countries() -> list[str]:
    """Countries that ship a code library."""
    return sorted(c for c, e in _plan_data()["countries"].items() if e.get("codes"))


def parse_code(raw: str, library: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str, str, str | None]:
    """``(entry, base, string, control)`` of a point code against a library."""
    text = (raw or "").strip().upper()
    control: str | None = None
    m = _CONTROL.search(text)
    if m and len(text) > len(m.group(1)):
        rest = text[: len(text) - len(m.group(0))].strip()
        if rest and any(rest.startswith(str(c["code"]).upper()) for c in library):
            control = m.group(1).upper()
            text = rest
    text = (text.split() or [""])[0]
    entry: dict[str, Any] | None = None
    for c in library:
        k = str(c["code"]).upper()
        tail = text[len(k) :]
        if text.startswith(k) and (tail == "" or tail.isdigit()) and (entry is None or len(k) > len(entry["code"])):
            entry = c
    base = str(entry["code"]).upper() if entry else re.sub(r"\d+$", "", text)
    return entry, base, text[len(base) :] or "1", control


def unknown_codes(codes: list[str], library: list[dict[str, Any]]) -> dict[str, int]:
    """Base code -> point count of codes the library does not know."""
    out: dict[str, int] = {}
    for raw in codes:
        if not raw:
            continue
        entry, base, _, _ = parse_code(raw, library)
        if entry is None:
            key = base or raw
            out[key] = out.get(key, 0) + 1
    return out


def short_strings(codes: list[str], library: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strings that cannot draw: one point, or a closed string with fewer than three."""
    counts: dict[str, dict[str, Any]] = {}
    for raw in codes:
        entry, base, string, control = parse_code(raw, library)
        if entry is None or entry.get("line") == "none":
            continue
        key = f"{base}{string}"
        cur = counts.setdefault(key, {"code": entry["code"], "count": 0, "closed": entry.get("line") == "closed"})
        cur["count"] += 1
        if control == "CL":
            cur["closed"] = True
    return [{"key": k, **v} for k, v in counts.items() if v["count"] < 2 or (v["closed"] and v["count"] < 3)]


def duplicate_codes(library: list[dict[str, Any]]) -> list[str]:
    """Codes listed more than once (case-insensitive)."""
    seen: set[str] = set()
    dups: list[str] = []
    for c in library:
        k = str(c.get("code") or "").strip().upper()
        if k in seen and k not in dups:
            dups.append(k)
        seen.add(k)
    return dups


__all__ = [
    "CONVENTION_VALUES",
    "LINE_KINDS",
    "clean_conventions",
    "country_codes",
    "country_conventions",
    "duplicate_codes",
    "library_countries",
    "neutral_codes",
    "parse_code",
    "short_strings",
    "unknown_codes",
]
