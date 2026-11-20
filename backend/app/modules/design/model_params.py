"""In-ERP quick modelling: the brief values `ddc gen` really takes, with their ranges. Pure Python.

Ranges, defaults and the brief->spec mapping mirror the editor at link/int 878262bf8:
crates/gen/src/project/limits.rs (ParamDef), spec.rs (defaults(), read_footprint, MAX_APARTMENTS_PER_FLOOR)
and crates/app/src/link/gen.rs (map_brief). A value outside them is refused here, never clamped.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .brief_doc import _MISSING, BriefError, resolve, schema_errors

GENERATOR_REF = "editor link/int 878262bf8: crates/gen/src/project/limits.rs, spec.rs; crates/app/src/link/gen.rs"

# typology -> (max floors, floor height m, room band depth m, corridor m)   spec.rs defaults(), limits.rs max_floors()
TYPOLOGY = {
    "house": (3, 3.0, 4.8, 1.4),
    "apartment_section": (40, 3.0, 6.4, 1.6),
    "office": (40, 3.6, 6.0, 1.8),
    "school": (5, 3.6, 7.2, 2.6),
}
CATEGORY = {
    "residential_single": "house",
    "residential_multi": "apartment_section",
    "office": "office",
    "school": "school",
    "kindergarten": "school",
}
BAND_MIN, HALL_MAX = 3.0, 120.0
MAX_APARTMENTS_PER_FLOOR = 12
DWELLING_TYPOLOGIES = ("house", "apartment_section")


@dataclass(frozen=True)
class Param:
    id: str
    pointer: str
    kind: str  # int | number | bool | choice
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: tuple | None = None
    spec_key: str = ""  # top-level key of the generator spec this value becomes
    nullable: bool = True


def typology_of(doc: dict) -> str | None:
    t = (doc.get("generator") or {}).get("template")
    if t:
        return t if t in TYPOLOGY else None
    return CATEGORY.get((doc.get("use") or {}).get("category"))


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def params_for(doc: dict, typ: str) -> list[Param]:
    max_floors, _, band, corridor = TYPOLOGY[typ]
    over = (doc.get("generator") or {}).get("spec_overrides") or {}
    band = _num(over.get("band_depth")) or band
    corridor = _num(over.get("corridor")) or corridor
    return [
        Param("floors", "/massing/floors_above", "int", "storeys", 1, max_floors, 1, spec_key="floors", nullable=False),
        Param("floor_height", "/massing/floor_height_m", "number", "m", 2.7, 6.0, 0.05, spec_key="floor_height"),
        Param(
            "width", "/massing/footprint/width_m", "number", "m", 6.0, 200.0, 0.1, spec_key="footprint", nullable=False
        ),
        # two room bands and the corridor; past them an open bay of up to HALL_MAX (spec.rs read_footprint)
        Param(
            "depth",
            "/massing/footprint/depth_m",
            "number",
            "m",
            round(2 * BAND_MIN + corridor, 2),
            round(band + corridor + HALL_MAX, 2),
            0.1,
            spec_key="footprint",
            nullable=False,
        ),
        Param("grid", "/structure/grid_m", "number", "m", 3.0, 12.0, 0.1, spec_key="grid"),
        Param("lift", "/massing/lift", "bool", spec_key="lift"),
        # piles are not built by the generator: not offered
        Param("foundation", "/structure/foundation", "choice", options=("raft", "strip", None), spec_key="foundation"),
        Param("roof", "/envelope/roof", "choice", options=("flat", "gable", "hip", "shed"), spec_key="roof"),
        Param("roof_slope", "/envelope/roof_slope_deg", "number", "deg", 5.0, 60.0, 1, spec_key="roof"),
    ]


def defaults_for(typ: str, floors: int) -> dict[str, Any]:
    """What the generator uses when the brief leaves a value out (None: the builder sizes it)."""
    _, height, _, _ = TYPOLOGY[typ]
    lift = floors > 1 and typ != "house" and (floors >= 5 or typ != "apartment_section")
    return {
        "/massing/floor_height_m": height,
        "/structure/grid_m": 7.2,
        "/envelope/roof_slope_deg": 30.0,
        "/massing/lift": lift,
        "/structure/foundation": None,
        "/envelope/roof": "gable" if typ == "house" else "flat",
    }


def _value(doc: dict, pointer: str) -> Any:
    v = resolve(doc, pointer)
    return None if v is _MISSING else v


def _units(doc: dict) -> list[dict]:
    units = (doc.get("programme") or {}).get("units")
    return [u for u in units if isinstance(u, dict)] if isinstance(units, list) else []


def per_floor(count: int, floors: int) -> int:
    """gen.rs: the brief counts units of the building, the spec those of one floor."""
    return max(1, math.ceil(count / max(1, floors)))


def view(doc: dict) -> dict[str, Any]:
    """The panel: parameters with unit, range, current value and the generator default; unit mix; presets."""
    typ = typology_of(doc)
    if typ is None:
        return {
            "typology": None,
            "brief_version": doc.get("version"),
            "params": [],
            "units": [],
            "presets": [],
            "reason": "The brief names no use the generator builds (house, apartment block, office, school).",
            "source": GENERATOR_REF,
        }
    over = (doc.get("generator") or {}).get("spec_overrides") or {}
    floors = int(_value(doc, "/massing/floors_above") or 1)
    dflt = defaults_for(typ, floors)
    params = [
        {
            "id": p.id,
            "pointer": p.pointer,
            "kind": p.kind,
            "unit": p.unit,
            "min": p.min,
            "max": p.max,
            "step": p.step,
            "options": list(p.options) if p.options else None,
            "nullable": p.nullable,
            "value": _value(doc, p.pointer),
            "default": dflt.get(p.pointer),
            "overridden": p.spec_key in over,
        }
        for p in params_for(doc, typ)
    ]
    units = []
    if typ in DWELLING_TYPOLOGIES:
        for i, u in enumerate(_units(doc)):
            count = int(u.get("count") or 1)
            units.append(
                {
                    "index": i,
                    "pointer": f"/programme/units/{i}/count",
                    "name": u.get("name"),
                    "value": count,
                    "min": 1,
                    "max": MAX_APARTMENTS_PER_FLOOR * TYPOLOGY[typ][0],
                    "per_floor": per_floor(count, floors),
                    "overridden": "apartments" in over,
                }
            )
    return {
        "typology": typ,
        "brief_version": doc.get("version"),
        "params": params,
        "units": units,
        "max_units_per_floor": MAX_APARTMENTS_PER_FLOOR if units else None,
        "presets": presets(doc, typ),
        "reason": None,
        "source": GENERATOR_REF,
    }


def _floors_preset(doc: dict, typ: str, target: int) -> dict[str, Any] | None:
    floors = int(_value(doc, "/massing/floors_above") or 1)
    if target == floors or not 1 <= target <= TYPOLOGY[typ][0]:
        return None
    values: dict[str, Any] = {"/massing/floors_above": target}
    if typ in DWELLING_TYPOLOGIES:  # same flats on every floor
        for i, u in enumerate(_units(doc)):
            values[f"/programme/units/{i}/count"] = per_floor(int(u.get("count") or 1), floors) * target
    return values


def presets(doc: dict, typ: str) -> list[dict[str, Any]]:
    """Quick choices computed from the brief's own numbers: one storey more or less, the site's limit."""
    floors = int(_value(doc, "/massing/floors_above") or 1)
    out = []
    for pid, target in (("floor_up", floors + 1), ("floor_down", floors - 1)):
        v = _floors_preset(doc, typ, target)
        if v:
            out.append({"id": pid, "values": v})
    site = doc.get("site") or {}
    caps = []
    if isinstance(site.get("max_floors"), int):
        caps.append(site["max_floors"])
    height = _num(site.get("max_height_m"))
    if height:
        storey = _num(_value(doc, "/massing/floor_height_m")) or TYPOLOGY[typ][1]
        caps.append(int(height // storey))
    if caps:
        v = _floors_preset(doc, typ, min(min(caps), TYPOLOGY[typ][0]))
        if v:
            out.append({"id": "site_limit", "values": v})
    return out


def _set(doc: dict, pointer: str, value: Any) -> None:
    parts = pointer[1:].split("/")
    node: Any = doc
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node.setdefault(part, {})
    last = parts[-1]
    if isinstance(node, list):
        node[int(last)] = value
    elif value is None:
        node.pop(last, None)
    else:
        node[last] = value


def _check(p: Param, value: Any) -> str | None:
    if value is None:
        return None if p.nullable else "is required"
    if p.kind == "bool":
        return None if isinstance(value, bool) else "must be true or false"
    if p.kind == "choice":
        return None if value in p.options else f"one of {', '.join(str(o) for o in p.options if o)}"
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return "must be a number"
    if p.kind == "int" and int(value) != value:
        return "must be a whole number"
    if not p.min <= value <= p.max:
        return f"must be in {p.min:g}..{p.max:g} {p.unit or ''}".rstrip()
    return None


def apply(doc: dict, values: dict[str, Any], *, user_id: str, at: datetime) -> tuple[dict, list[str]]:
    """A copy of ``doc`` with ``values`` (pointer -> value) set and confirmed by the person who set them.

    The person typing a value in the panel is the confirmation (named, timed), as with the confirm action.
    Returns (document, changed pointers); raises BriefError with every problem at once."""
    typ = typology_of(doc)
    if typ is None:
        raise BriefError([{"pointer": "/use/category", "message": "no generator builds this use"}])
    over = (doc.get("generator") or {}).get("spec_overrides") or {}
    known = {p.pointer: p for p in params_for(doc, typ)}
    errors: list[dict] = []
    out = copy.deepcopy(doc)
    changed: list[str] = []
    unit_ptrs = (
        {f"/programme/units/{i}/count" for i in range(len(_units(doc)))} if typ in DWELLING_TYPOLOGIES else set()
    )
    for pointer, value in values.items():
        p = known.get(pointer)
        if pointer in unit_ptrs:
            p = Param(
                "units",
                pointer,
                "int",
                "units",
                1,
                MAX_APARTMENTS_PER_FLOOR * TYPOLOGY[typ][0],
                1,
                spec_key="apartments",
                nullable=False,
            )
        if p is None:
            errors.append({"pointer": pointer, "message": "is not a value the generator takes"})
            continue
        if p.spec_key in over:
            errors.append(
                {
                    "pointer": pointer,
                    "message": f"generator.spec_overrides.{p.spec_key} sets this; change it in the brief",
                }
            )
            continue
        problem = _check(p, value)
        if problem:
            errors.append({"pointer": pointer, "message": problem})
            continue
        if p.kind == "int":
            value = int(value)
        if _value(doc, pointer) != value:
            _set(out, pointer, value)
            changed.append(pointer)
    floors = int(_value(out, "/massing/floors_above") or 1)
    if typ in DWELLING_TYPOLOGIES and _units(out):
        total = sum(per_floor(int(u.get("count") or 1), floors) for u in _units(out))
        if total > MAX_APARTMENTS_PER_FLOOR:
            errors.append(
                {
                    "pointer": "/programme/units",
                    "message": f"{total} units on one floor; the generator places at most {MAX_APARTMENTS_PER_FLOOR}",
                }
            )
    if errors:
        raise BriefError(errors)
    if not changed:
        return out, []
    prov = out.setdefault("provenance", {})
    stamp = at.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    for pointer in changed:
        if _value(out, pointer) is None:
            prov.pop(pointer, None)
        else:
            prov[pointer] = {
                "status": "confirmed",
                "confirmed_by": user_id,
                "confirmed_at": stamp,
                "sources": [{"kind": "user"}],
                "note": "Set in the model panel",
            }
    if out.get("questions"):
        out["questions"] = [q for q in out["questions"] if q.get("pointer") not in set(changed)]
    errs = schema_errors(out)
    if errs:
        raise BriefError(errs)
    return out, changed
