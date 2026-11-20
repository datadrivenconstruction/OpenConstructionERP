"""Field catalogue of ``ddc-brief/1`` that extraction may propose, with per-field coercion.

Pure Python, no ERP imports. ``contract/tests/test_brief_extract.py`` checks every spec here
against ``contract/schemas/brief.schema.json`` so the two cannot drift apart.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

COUNTRIES = ("DE", "US", "GB", "RU", "FR", "ES", "UA", "BR", "CN", "IN")
USE_CATEGORIES = (
    "residential_single",
    "residential_multi",
    "office",
    "school",
    "kindergarten",
    "retail",
    "hotel",
    "healthcare",
    "industrial",
    "warehouse",
    "parking",
    "mixed_use",
    "infrastructure",
    "other",
)
DEPTH_LEVELS = ("D1", "D2", "D3", "D4", "D5")
STRUCTURE_SYSTEMS = ("masonry", "concrete_frame", "concrete_walls", "timber", "steel", "hybrid")
FOUNDATIONS = ("strip", "raft", "piles")
ROOFS = ("flat", "gable", "hip", "shed")
QUALITY_LEVELS = ("basic", "standard", "high")
UNIT_ROOM_KINDS = (
    "living",
    "bedroom",
    "kitchen",
    "bath",
    "wc",
    "hall",
    "storage",
    "office",
    "meeting",
    "classroom",
    "lab",
    "staff",
    "lobby",
    "technical",
    "parking",
    "retail",
    "dining",
    "workshop",
    "ward",
    "gym",
)


class FieldError(ValueError):
    """A proposed or answered value does not fit its field."""

    def __init__(self, pointer: str, message: str, *, out_of_range: bool = False):
        super().__init__(f"{pointer}: {message}")
        self.pointer = pointer
        self.message = message
        self.out_of_range = out_of_range


@dataclass(frozen=True)
class Field:
    pointer: str
    kind: str  # integer | number | enum | bool | string | country | locale | currency | units
    required: bool = False
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: float | None = None
    enum: tuple[str, ...] | None = None
    max_len: int | None = None
    unit: str | None = None  # for numeric fields: m, m2, deg, ratio


FIELDS: dict[str, Field] = {
    f.pointer: f
    for f in (
        Field("/name", "string", max_len=200),
        Field("/country", "country", required=True),
        Field("/locale", "locale", required=True),
        Field("/depth_level", "enum", required=True, enum=DEPTH_LEVELS),
        Field("/use/category", "enum", required=True, enum=USE_CATEGORIES),
        Field("/use/detail", "string", max_len=500),
        Field("/site/address", "string", max_len=300),
        Field("/site/max_height_m", "number", minimum=0, unit="m"),
        Field("/site/max_floors", "integer", minimum=1),
        Field("/site/floor_area_ratio_max", "number", exclusive_minimum=0, unit="ratio"),
        Field("/site/site_coverage_max", "number", exclusive_minimum=0, maximum=1, unit="ratio"),
        Field("/massing/floors_above", "integer", required=True, minimum=1, maximum=200),
        Field("/massing/floors_below", "integer", minimum=0, maximum=10),
        Field("/massing/floor_height_m", "number", minimum=2.2, maximum=12, unit="m"),
        Field("/massing/ground_floor_height_m", "number", minimum=2.2, maximum=12, unit="m"),
        Field("/massing/footprint/width_m", "number", minimum=0, unit="m"),
        Field("/massing/footprint/depth_m", "number", minimum=0, unit="m"),
        Field("/massing/gross_floor_area_m2", "number", exclusive_minimum=0, unit="m2"),
        Field("/massing/lift", "bool"),
        Field("/programme/units", "units"),
        Field("/programme/parking_spaces", "integer", minimum=0),
        Field("/structure/system", "enum", enum=STRUCTURE_SYSTEMS),
        Field("/structure/foundation", "enum", enum=FOUNDATIONS),
        Field("/envelope/roof", "enum", enum=ROOFS),
        Field("/envelope/roof_slope_deg", "number", minimum=0, maximum=75, unit="deg"),
        Field("/envelope/facade", "string", max_len=100),
        Field("/envelope/energy_standard", "string", max_len=100),
        Field("/quality_level", "enum", enum=QUALITY_LEVELS),
        Field("/budget/amount", "number", exclusive_minimum=0),
        Field("/budget/currency", "currency"),
        Field("/budget/includes_vat", "bool"),
        Field("/budget/cost_groups", "string"),
    )
}
REQUIRED = tuple(p for p, f in FIELDS.items() if f.required)
_LOCALE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


def _number(pointer: str, raw: Any, *, integer: bool) -> int | float:
    if isinstance(raw, bool):
        raise FieldError(pointer, "must be a number")
    if isinstance(raw, str):
        text = raw.strip().replace(",", ".")
        try:
            raw = float(text)
        except ValueError as exc:
            raise FieldError(pointer, f"'{raw}' is not a number") from exc
    if not isinstance(raw, (int, float)) or raw != raw or raw in (float("inf"), float("-inf")):
        raise FieldError(pointer, "must be a finite number")
    if integer:
        if int(raw) != raw:
            raise FieldError(pointer, "must be a whole number")
        return int(raw)
    return float(raw) if not isinstance(raw, int) else raw


def _check_units(pointer: str, raw: Any) -> list[dict]:
    if not isinstance(raw, list) or not raw:
        raise FieldError(pointer, "must be a non-empty list of units")
    allowed_unit = {"name", "count", "area_m2", "rooms"}
    allowed_room = {"kind", "name", "count", "area_m2", "floors", "adjacent_to"}
    out = []
    for i, unit in enumerate(raw):
        at = f"{pointer}/{i}"
        if not isinstance(unit, dict) or set(unit) - allowed_unit:
            raise FieldError(at, "unit has unknown keys or is not an object")
        name = unit.get("name")
        if not isinstance(name, str) or not name.strip():
            raise FieldError(at + "/name", "is required")
        count = _number(at + "/count", unit.get("count"), integer=True)
        if count < 1:
            raise FieldError(at + "/count", "must be at least 1", out_of_range=True)
        clean: dict[str, Any] = {"name": name.strip(), "count": count}
        if "area_m2" in unit:
            area = _number(at + "/area_m2", unit["area_m2"], integer=False)
            if area <= 0:
                raise FieldError(at + "/area_m2", "must be above 0", out_of_range=True)
            clean["area_m2"] = area
        rooms = unit.get("rooms")
        if not isinstance(rooms, list) or not rooms:
            raise FieldError(at + "/rooms", "at least one room is required")
        clean["rooms"] = []
        for j, room in enumerate(rooms):
            rat = f"{at}/rooms/{j}"
            if not isinstance(room, dict) or set(room) - allowed_room:
                raise FieldError(rat, "room has unknown keys or is not an object")
            kind = room.get("kind")
            if not isinstance(kind, str) or not kind.strip():
                raise FieldError(rat + "/kind", "is required")
            r: dict[str, Any] = {"kind": kind.strip()}
            if "name" in room:
                r["name"] = str(room["name"])
            if "count" in room:
                n = _number(rat + "/count", room["count"], integer=True)
                if n < 1:
                    raise FieldError(rat + "/count", "must be at least 1", out_of_range=True)
                r["count"] = n
            if "area_m2" in room:
                a = _number(rat + "/area_m2", room["area_m2"], integer=False)
                if a <= 0:
                    raise FieldError(rat + "/area_m2", "must be above 0", out_of_range=True)
                r["area_m2"] = a
            clean["rooms"].append(r)
        out.append(clean)
    return out


def coerce(pointer: str, raw: Any) -> Any:
    """Validated value for ``pointer``; raises :class:`FieldError`."""
    spec = FIELDS.get(pointer)
    if spec is None:
        raise FieldError(pointer, "is not a field extraction can fill")
    kind = spec.kind
    if kind in ("integer", "number"):
        value = _number(pointer, raw, integer=kind == "integer")
        if spec.minimum is not None and value < spec.minimum:
            raise FieldError(pointer, f"{value} is below the minimum {spec.minimum}", out_of_range=True)
        if spec.maximum is not None and value > spec.maximum:
            raise FieldError(pointer, f"{value} is above the maximum {spec.maximum}", out_of_range=True)
        if spec.exclusive_minimum is not None and value <= spec.exclusive_minimum:
            raise FieldError(pointer, f"{value} must be above {spec.exclusive_minimum}", out_of_range=True)
        return value
    if kind == "enum":
        if raw not in (spec.enum or ()):
            raise FieldError(pointer, f"'{raw}' is not one of {', '.join(spec.enum or ())}")
        return raw
    if kind == "bool":
        if not isinstance(raw, bool):
            raise FieldError(pointer, "must be true or false")
        return raw
    if kind == "string":
        if not isinstance(raw, str) or not raw.strip():
            raise FieldError(pointer, "must be a non-empty text")
        text = " ".join(raw.split())
        if spec.max_len and len(text) > spec.max_len:
            raise FieldError(pointer, f"is longer than {spec.max_len} characters", out_of_range=True)
        return text
    if kind == "country":
        code = raw.strip().upper() if isinstance(raw, str) else ""
        if not re.fullmatch(r"[A-Z]{2}", code):
            raise FieldError(pointer, "must be a two-letter country code")
        return code
    if kind == "locale":
        if not isinstance(raw, str) or not _LOCALE.match(raw.strip()):
            raise FieldError(pointer, "must be a locale such as 'de' or 'pt-BR'")
        return raw.strip()
    if kind == "currency":
        code = raw.strip().upper() if isinstance(raw, str) else ""
        if not _CURRENCY.match(code):
            raise FieldError(pointer, "must be a three-letter currency code")
        return code
    if kind == "units":
        return _check_units(pointer, raw)
    raise FieldError(pointer, f"unsupported kind {kind}")  # pragma: no cover


def options_for(pointer: str) -> list[Any]:
    """Closed answer set of a field (empty when the answer is free-form)."""
    spec = FIELDS[pointer]
    if spec.kind == "enum":
        return list(spec.enum or ())
    if spec.kind == "country":
        return list(COUNTRIES)
    if spec.kind == "bool":
        return [True, False]
    return []


def pointer_parts(pointer: str) -> list[str]:
    return [p.replace("~1", "/").replace("~0", "~") for p in pointer[1:].split("/")]


def get_at(doc: dict, pointer: str, default: Any = None) -> Any:
    node: Any = doc
    for part in pointer_parts(pointer):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return default
    return node


def set_at(doc: dict, pointer: str, value: Any) -> None:
    parts = pointer_parts(pointer)
    node = doc
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = node[part] = {}
        node = nxt
    node[parts[-1]] = copy.deepcopy(value)


def drop_at(doc: dict, pointer: str) -> None:
    parts = pointer_parts(pointer)
    chain = [doc]
    for part in parts[:-1]:
        nxt = chain[-1].get(part)
        if not isinstance(nxt, dict):
            return
        chain.append(nxt)
    chain[-1].pop(parts[-1], None)
    for i in range(len(parts) - 2, -1, -1):  # prune containers left empty
        if chain[i + 1] == {}:
            chain[i].pop(parts[i], None)
