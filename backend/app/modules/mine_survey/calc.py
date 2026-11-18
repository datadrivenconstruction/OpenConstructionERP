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
