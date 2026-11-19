# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mine reconciliation arithmetic (no database, no I/O).

The actual volume is computed by the surfaces_volumes engine and read from a
Volumes calculation; this module turns plan, actual, density and truck loads
into compliance, survey tonnes and the truck factor. Results are Decimal so a
course number such as 94.96 % or +4.47 % is exact.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

UNIT_TYPES = ("pit", "bench", "block", "stope", "drive")
#: Units worked underground: only these show drive advance metres.
UNDERGROUND = frozenset({"stope", "drive"})

_M3 = Decimal("0.001")
_T = Decimal("0.01")
_PCT = Decimal("0.01")


def dec(value: float | int | str | Decimal) -> Decimal:
    """Decimal from a float without binary noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(repr(value)) if isinstance(value, float) else Decimal(value)


def compliance_pct(actual_m3: Decimal | float | None, plan_m3: Decimal | float | None) -> Decimal | None:
    """``actual / plan`` in percent, 2 places; None without a positive plan or an actual."""
    if actual_m3 is None or plan_m3 is None or dec(plan_m3) <= 0:
        return None
    return (dec(actual_m3) / dec(plan_m3) * 100).quantize(_PCT, ROUND_HALF_UP)


def survey_tonnes(actual_m3: Decimal | float | None, density_t_m3: Decimal | float | None) -> Decimal | None:
    """Survey volume times density, to 0.01 t."""
    if actual_m3 is None or density_t_m3 is None:
        return None
    return (dec(actual_m3).quantize(_M3, ROUND_HALF_UP) * dec(density_t_m3)).quantize(_T, ROUND_HALF_UP)


def truck_factor_pct(truck_t: Decimal | float | None, survey_t: Decimal | float | None) -> Decimal | None:
    """``(truck - survey) / survey`` in percent; positive means the trucks counted more."""
    if truck_t is None or survey_t is None or dec(survey_t) <= 0:
        return None
    return ((dec(truck_t) - dec(survey_t)) / dec(survey_t) * 100).quantize(_PCT, ROUND_HALF_UP)


def advance_pct(actual_m: Decimal | float | None, plan_m: Decimal | float | None) -> Decimal | None:
    """Drive advance against plan in percent."""
    return compliance_pct(actual_m, plan_m)


def outside_band(pct: Decimal | float | None, lo: Decimal | float | None, hi: Decimal | float | None) -> bool | None:
    """True when ``pct`` is outside ``lo..hi``; None when there is no value or no band to judge by."""
    if pct is None or lo is None or hi is None:
        return None
    return not (dec(lo) <= dec(pct) <= dec(hi))


@dataclass(frozen=True)
class TruckImport:
    """What a truck-load file adds up to."""

    loads: int
    tonnes: Decimal
    rows: int
    problems: list[str] = field(default_factory=list)


def _number(text: str | None) -> Decimal | None:
    try:
        return Decimal((text or "").strip().replace(",", "."))
    except InvalidOperation:
        return None


def _rows(text: str) -> list[dict[str, str]]:
    body = text.lstrip("﻿")
    delim = ";" if body[:2048].count(";") > body[:2048].count(",") else ","
    reader = csv.DictReader(io.StringIO(body), delimiter=delim)
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()} for row in reader]


def parse_truck_loads(text: str, unit_name: str | None = None) -> TruckImport:
    """Sum ``loads x payload_t`` over a CSV with ``loads`` and ``payload_t`` columns.

    A ``unit`` column, when present and filled, limits the sum to rows of ``unit_name``.
    A bad row is reported and skipped, never guessed.
    """
    loads = 0
    tonnes = Decimal(0)
    rows = 0
    problems: list[str] = []
    for i, row in enumerate(_rows(text), start=2):
        unit = row.get("unit", "")
        if unit and unit_name and unit.casefold() != unit_name.casefold():
            continue
        n, payload = _number(row.get("loads")), _number(row.get("payload_t"))
        if n is None or payload is None or n < 0 or payload <= 0 or n != n.to_integral_value():
            problems.append(f"line {i}")
            continue
        loads += int(n)
        tonnes += n * payload
        rows += 1
    return TruckImport(loads, tonnes.quantize(_T, ROUND_HALF_UP), rows, problems)


@dataclass(frozen=True)
class PlanRow:
    """One line of a plan file."""

    unit: str
    unit_type: str
    plan_m3: Decimal
    plan_t: Decimal | None
    plan_advance_m: Decimal | None
    density_t_m3: Decimal | None


def parse_plan(text: str) -> tuple[list[PlanRow], list[str]]:
    """Read a plan CSV: ``unit,type,plan_m3,plan_t,plan_advance_m,density_t_m3`` (``unit`` and ``plan_m3`` are required)."""
    out: list[PlanRow] = []
    problems: list[str] = []
    for i, row in enumerate(_rows(text), start=2):
        name = row.get("unit", "")
        plan = _number(row.get("plan_m3"))
        if not name or plan is None or plan < 0:
            problems.append(f"line {i}")
            continue
        kind = row.get("type", "").lower() or "bench"
        out.append(
            PlanRow(
                unit=name,
                unit_type=kind if kind in UNIT_TYPES else "bench",
                plan_m3=plan,
                plan_t=_number(row.get("plan_t")),
                plan_advance_m=_number(row.get("plan_advance_m")),
                density_t_m3=_number(row.get("density_t_m3")),
            )
        )
    return out, problems


# ── Material split (ore / waste / low grade) ───────────────────────────────

MATERIALS = ("ore", "waste", "low_grade", "other")


@dataclass(frozen=True)
class MaterialPart:
    """The share of a unit's actual that falls inside one material polygon."""

    material: str
    name: str
    volume_m3: Decimal
    density_t_m3: Decimal | None
    tonnes: Decimal | None


@dataclass(frozen=True)
class MaterialSplit:
    """A unit's actual split by material polygon, each part at its own density."""

    parts: list[MaterialPart]
    total_m3: Decimal
    assigned_m3: Decimal
    unassigned_m3: Decimal
    coverage_pct: Decimal | None
    tonnes: Decimal | None


def material_split(
    parts: list[tuple[str, str, Decimal | float, Decimal | float | None]], total_m3: Decimal | float
) -> MaterialSplit:
    """Tonnes per material and the share of the unit the polygons cover.

    ``parts`` are ``(material, name, volume_m3, density_t_m3)``; ``total_m3`` is the
    unit's whole actual. A part without a density has no tonnes, and then neither has
    the total: a sum that silently skips a part would read as a complete figure.
    """
    out = [
        MaterialPart(mat, name, dec(v).quantize(_M3, ROUND_HALF_UP), None if d is None else dec(d), survey_tonnes(v, d))
        for mat, name, v, d in parts
    ]
    total = dec(total_m3).quantize(_M3, ROUND_HALF_UP)
    assigned = sum((p.volume_m3 for p in out), Decimal(0))
    unassigned = max(total - assigned, Decimal(0))
    coverage = (assigned / total * 100).quantize(_PCT, ROUND_HALF_UP) if total > 0 else None
    tonnes = None if not out or any(p.tonnes is None for p in out) else sum((p.tonnes or 0 for p in out), Decimal(0))
    return MaterialSplit(out, total, assigned, unassigned, coverage, tonnes)


def truck_ratio_pct(truck_t: Decimal | float | None, survey_t: Decimal | float | None) -> Decimal | None:
    """Truck-count tonnes as a percentage of survey tonnes (100 % means they agree)."""
    if truck_t is None or survey_t is None or dec(survey_t) <= 0:
        return None
    return (dec(truck_t) / dec(survey_t) * 100).quantize(_PCT, ROUND_HALF_UP)


# ── Drive advance and profiles ─────────────────────────────────────────────


def drive_advance(chainages: list[Decimal | float]) -> Decimal | None:
    """Metres advanced between the first and the last face pickup of a period."""
    if len(chainages) < 2:
        return None
    values = [dec(c) for c in chainages]
    return (max(values) - min(values)).quantize(Decimal("0.01"), ROUND_HALF_UP)


def section_area(ring: list[tuple[float, float]]) -> Decimal:
    """Shoelace area of a measured profile, given as (offset, height) pairs, m2."""
    if len(ring) < 3:
        return Decimal(0)
    s = Decimal(0)
    pts = [(dec(x), dec(y)) for x, y in ring]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1], strict=True):
        s += x1 * y2 - x2 * y1
    return (abs(s) / 2).quantize(Decimal("0.001"), ROUND_HALF_UP)


@dataclass(frozen=True)
class DriveProfiles:
    """Design section against the measured profiles of one drive stretch."""

    count: int
    design_area_m2: Decimal
    mean_actual_m2: Decimal
    overbreak_pct: Decimal
    length_m: Decimal
    excess_m3: Decimal
    excess_t: Decimal | None
    under_count: int


def drive_profiles(
    design_area_m2: Decimal | float,
    actual_areas_m2: list[Decimal | float],
    length_m: Decimal | float,
    density_t_m3: Decimal | float | None = None,
    under_tol_pct: Decimal | float | None = None,
) -> DriveProfiles | None:
    """Mean overbreak in percent of the design section, the excess volume and its tonnes.

    A negative overbreak is underbreak. ``under_count`` counts the profiles that are
    smaller than the design by more than ``under_tol_pct``; without a tolerance it
    counts every profile below the design.
    """
    if not actual_areas_m2 or dec(design_area_m2) <= 0:
        return None
    design = dec(design_area_m2)
    areas = [dec(a) for a in actual_areas_m2]
    mean = sum(areas, Decimal(0)) / len(areas)
    over = ((mean - design) / design * 100).quantize(_PCT, ROUND_HALF_UP)
    length = dec(length_m)
    excess = ((mean - design) * length).quantize(_M3, ROUND_HALF_UP)
    tol = dec(under_tol_pct) if under_tol_pct is not None else Decimal(0)
    under = sum(1 for a in areas if (design - a) / design * 100 > tol)
    return DriveProfiles(
        count=len(areas),
        design_area_m2=design,
        mean_actual_m2=mean.quantize(Decimal("0.001"), ROUND_HALF_UP),
        overbreak_pct=over,
        length_m=length,
        excess_m3=excess,
        excess_t=survey_tonnes(excess, density_t_m3),
        under_count=under,
    )


# ── Blast holes ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HoleCheck:
    """One drilled hole against its design collar and depth."""

    collar_offset_m: Decimal | None
    depth_diff_m: Decimal | None
    collar_ok: bool | None
    depth_ok: bool | None


def hole_check(
    design_e: Decimal | float,
    design_n: Decimal | float,
    design_depth_m: Decimal | float | None,
    drilled_e: Decimal | float | None,
    drilled_n: Decimal | float | None,
    drilled_depth_m: Decimal | float | None,
    collar_tol_m: Decimal | float | None,
    depth_tol_m: Decimal | float | None,
) -> HoleCheck:
    """Horizontal collar offset and depth difference (drilled minus design), judged by the pattern tolerances.

    A verdict is None when there is nothing to judge: no as-drilled value or no tolerance.
    """
    offset = None
    if drilled_e is not None and drilled_n is not None:
        de, dn = dec(drilled_e) - dec(design_e), dec(drilled_n) - dec(design_n)
        offset = (de * de + dn * dn).sqrt().quantize(_M3, ROUND_HALF_UP)
    diff = None
    if drilled_depth_m is not None and design_depth_m is not None:
        diff = (dec(drilled_depth_m) - dec(design_depth_m)).quantize(_M3, ROUND_HALF_UP)
    collar_ok = None if offset is None or collar_tol_m is None else offset <= dec(collar_tol_m)
    depth_ok = None if diff is None or depth_tol_m is None else abs(diff) <= dec(depth_tol_m)
    return HoleCheck(offset, diff, collar_ok, depth_ok)


@dataclass(frozen=True)
class HoleRow:
    """One line of a blast hole file."""

    hole: str
    e: Decimal
    n: Decimal
    z: Decimal | None
    depth_m: Decimal | None


def parse_holes(text: str) -> tuple[list[HoleRow], list[str]]:
    """Read ``hole,e,n,z,depth`` rows (``z`` and ``depth`` may be empty); bad rows are reported, never guessed."""
    out: list[HoleRow] = []
    problems: list[str] = []
    for i, row in enumerate(_rows(text), start=2):
        hole = row.get("hole") or row.get("id") or ""
        e, n = _number(row.get("e")), _number(row.get("n"))
        if not hole or e is None or n is None:
            problems.append(f"line {i}")
            continue
        z = _number(row.get("z")) if row.get("z") else None
        depth = _number(row.get("depth") or row.get("depth_m")) if (row.get("depth") or row.get("depth_m")) else None
        out.append(HoleRow(hole, e, n, z, depth))
    return out, problems
