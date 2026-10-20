# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Read element identity, properties and quantities from the RVT converter's ``native_graph.ifc``.

``RVTconverter.exe --ifc`` writes, per element, a ``Revit_Identity`` property
set (ElementId, CategoryId, CategoryName, FamilyName, TypeName, LevelName,
PhaseCreated), stored parameters already in metres (``Revit_Parameters``),
``Qto_*BaseQuantities`` and ``RVT_TessellationQuantities`` in m / m2 / m3.

Only that small part of the STEP file is read, line by line: property and
quantity values, the sets that hold them, the relations that attach the sets
to elements, and storey containment. Geometry records are skipped by their
type name without being parsed, so a large file costs one text pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Property sets whose values become columns. Family and formula caches are
#: converter bookkeeping, not element data.
_SKIP_SETS = ("Revit_Parameters_FamilyCache", "Revit_Parameters_FormulaCache")

_WANTED = re.compile(
    r"^#(\d+)=(IFCPROPERTYSINGLEVALUE|IFCQUANTITY(?:LENGTH|AREA|VOLUME|COUNT|WEIGHT)|IFCPROPERTYSET|"
    r"IFCELEMENTQUANTITY|IFCRELDEFINESBYPROPERTIES|IFCRELCONTAINEDINSPATIALSTRUCTURE|IFCBUILDINGSTOREY)\("
)


@dataclass(frozen=True)
class _Ref:
    id: int


@dataclass
class RvtIfcElement:
    """What the IFC says about one Revit element."""

    identity: dict[str, Any] = field(default_factory=dict)
    #: ``"[Set] Prop" -> value`` for every property and quantity set except identity.
    values: dict[str, Any] = field(default_factory=dict)
    storey: str | None = None


def _decode_step_string(raw: str) -> str:
    """Undo STEP string encoding: ``''``, ``\\X2\\hhhh\\X0\\``, ``\\X\\hh``, ``\\S\\c``."""

    def x2(m: re.Match[str]) -> str:
        hexes = m.group(1)
        return "".join(chr(int(hexes[i : i + 4], 16)) for i in range(0, len(hexes), 4))

    s = raw.replace("''", "'")
    s = re.sub(r"\\X2\\([0-9A-Fa-f]*)\\X0\\", x2, s)
    s = re.sub(r"\\X\\([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), s)
    return re.sub(r"\\S\\(.)", lambda m: chr(ord(m.group(1)) + 128), s)


_TOKEN = re.compile(
    r"\s*(?:'((?:[^']|'')*)'|(#\d+)|(\$|\*)|(\.[A-Z_0-9]+\.)|([A-Z][A-Z0-9_]*)\(|"
    r"([-+]?\d+\.?\d*(?:[Ee][-+]?\d+)?)|(\()|(\))|(,))"
)


def _parse_args(text: str) -> list[Any]:
    """The argument list of one STEP record body (text between the outer parentheses)."""
    stack: list[list[Any]] = [[]]
    typed: list[str | None] = [None]
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None:
            break
        pos = m.end()
        string, ref, empty, enum, type_name, number, open_, close, _comma = m.groups()
        if string is not None:
            stack[-1].append(_decode_step_string(string))
        elif ref is not None:
            stack[-1].append(_Ref(int(ref[1:])))
        elif empty is not None:
            stack[-1].append(None)
        elif enum is not None:
            flag = enum.strip(".")
            stack[-1].append({"T": True, "F": False}.get(flag, flag))
        elif number is not None:
            stack[-1].append(float(number) if any(c in number for c in ".Ee") else int(number))
        elif type_name is not None or open_ is not None:
            stack.append([])
            typed.append(type_name)
        elif close is not None:
            if len(stack) == 1:
                break
            done = stack.pop()
            kind = typed.pop()
            # A typed value such as IFCLABEL('x') stands for its single argument.
            stack[-1].append(done[0] if kind and len(done) == 1 else done)
    return stack[0]


def _records(ifc_path: Path) -> Any:
    """``(id, type, args)`` for the record types this module reads."""
    pending = ""
    with ifc_path.open(encoding="ascii", errors="replace") as fh:
        for line in fh:
            if pending:
                pending += line.strip()
            elif line.startswith("#") and _WANTED.match(line):
                pending = line.strip()
            else:
                continue
            if not pending.endswith(";"):
                continue
            m = _WANTED.match(pending)
            body = pending[m.end() : pending.rfind(")")] if m else ""
            if m:
                yield int(m.group(1)), m.group(2), _parse_args(body)
            pending = ""


def read_rvt_ifc(ifc_path: Path) -> dict[int, RvtIfcElement]:
    """Revit element id -> identity, property/quantity values and storey, from ``native_graph.ifc``."""
    values: dict[int, tuple[str, Any]] = {}
    sets: dict[int, tuple[str, list[int]]] = {}
    links: list[tuple[list[int], int]] = []
    contained: list[tuple[list[int], int]] = []
    storeys: dict[int, str] = {}
    for rid, kind, args in _records(ifc_path):
        if kind == "IFCPROPERTYSINGLEVALUE":
            name, value = str(args[0]), args[2] if len(args) > 2 else None
            # The converter says so when a number kept Revit's internal unit (feet
            # and derived); the label keeps the take-off from summing it as metres.
            if isinstance(value, float) and "internal units" in str(args[1] or ""):
                name = f"{name} [internal units]"
            values[rid] = (name, value)
        elif kind.startswith("IFCQUANTITY"):
            values[rid] = (str(args[0]), args[3] if len(args) > 3 else None)
        elif kind in ("IFCPROPERTYSET", "IFCELEMENTQUANTITY"):
            members = args[5] if kind == "IFCELEMENTQUANTITY" else args[4]
            sets[rid] = (str(args[2]), [r.id for r in members or [] if isinstance(r, _Ref)])
        elif kind == "IFCRELDEFINESBYPROPERTIES":
            if isinstance(args[5], _Ref):
                links.append(([r.id for r in args[4] or [] if isinstance(r, _Ref)], args[5].id))
        elif kind == "IFCRELCONTAINEDINSPATIALSTRUCTURE":
            if isinstance(args[5], _Ref):
                contained.append(([r.id for r in args[4] or [] if isinstance(r, _Ref)], args[5].id))
        elif kind == "IFCBUILDINGSTOREY" and isinstance(args[2], str):
            storeys[rid] = args[2]

    per_product: dict[int, RvtIfcElement] = {}
    for products, set_id in links:
        name, members = sets.get(set_id, ("", []))
        if not name or name in _SKIP_SETS:
            continue
        for product in products:
            el = per_product.setdefault(product, RvtIfcElement())
            for vid in members:
                prop, value = values.get(vid, (None, None))
                if prop is None or value is None or isinstance(value, list):
                    continue
                if name == "Revit_Identity":
                    el.identity[prop] = value
                else:
                    el.values[f"[{name}] {prop}"] = value
    for products, storey_id in contained:
        storey = storeys.get(storey_id)
        for product in products:
            if storey and product in per_product:
                per_product[product].storey = storey

    out: dict[int, RvtIfcElement] = {}
    for el in per_product.values():
        eid = el.identity.get("ElementId")
        if isinstance(eid, int):
            out[eid] = el
    return out


#: Flat-table quantity column -> quantity names in preference order (lower case, no spaces).
_QUANTITY_PREFERENCE: dict[str, tuple[str, ...]] = {
    "Volume": ("netvolume", "grossvolume", "volume"),
    "Area": ("netsidearea", "netarea", "netfloorarea", "grosssidearea", "grossarea", "grossfloorarea"),
    "Length": ("length",),
    "Height": ("height",),
    "Surface Area": ("surfacearea",),
}


def element_quantities(el: RvtIfcElement) -> dict[str, float]:
    """Area / Volume / Length / Height / Surface Area from the element's quantity sets.

    Revit's base quantities (``Qto_*``) win over the converter's tessellation
    quantities, which win over nothing; values are already SI.
    """
    ranked: list[tuple[int, str, float]] = []
    for key, value in el.values.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not value:
            continue
        set_name, _, prop = key[1:].partition("] ")
        if set_name.startswith("Qto_"):
            rank = 0
        elif set_name == "RVT_TessellationQuantities":
            rank = 1
        else:
            continue
        ranked.append((rank, prop.replace(" ", "").replace("_", "").lower(), float(value)))
    ranked.sort(key=lambda t: t[0])
    out: dict[str, float] = {}
    for column, names in _QUANTITY_PREFERENCE.items():
        for name in names:
            hit = next((v for _r, n, v in ranked if n == name), None)
            if hit is not None:
                out[column] = hit
                break
    return out
