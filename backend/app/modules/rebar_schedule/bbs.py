# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bar bending schedule arithmetic: shape-code cut lengths, unit weight, totals.

Shape codes and their cut-length formulas are data (``data/shape_codes.json``),
one block per standard, so another national table is a data file rather than
code. Formulas run through the measurement library's safe evaluator with the
dimensions A to E, the bar diameter ``dia`` and the minimum bend radius ``r``.
Pure and ORM-free, so it can be unit tested on any interpreter.
"""

from __future__ import annotations

import csv
import io
import json
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.modules.measurement.formula import MeasurementError, safe_eval

DATA_FILE = Path(__file__).parent / "data" / "shape_codes.json"

#: Unit weight of a round steel bar in kg/m is d squared over 162.2; the trade rounds it to 162.
UNIT_WEIGHT_DIVISOR = Decimal("162")

DIMENSIONS = ("A", "B", "C", "D", "E")


class BbsError(ValueError):
    """A shape code, a dimension or a formula cannot produce a cut length."""


@lru_cache(maxsize=1)
def load_standards() -> dict[str, Any]:
    """The shape-code standards from the data file."""
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))["standards"]


def shape_codes() -> list[dict[str, Any]]:
    """Every shape code of every standard, flat, for a picker."""
    return [{"standard": std, **shape} for std, block in load_standards().items() for shape in block["shapes"]]


def find_shape(standard: str, code: str) -> dict[str, Any]:
    block = load_standards().get(standard)
    if block is None:
        raise BbsError(f"Unknown shape standard {standard!r}")
    for shape in block["shapes"]:
        if shape["code"] == code:
            return shape
    raise BbsError(f"Shape code {code!r} is not in {standard}")


def unit_weight(diameter_mm: Decimal) -> Decimal:
    """Mass per metre of a bar, d squared over 162, in kg/m."""
    return (Decimal(diameter_mm) ** 2 / UNIT_WEIGHT_DIVISOR).quantize(Decimal("0.0001"), ROUND_HALF_UP)


def bend_radius(standard: str, diameter_mm: Decimal) -> Decimal:
    """Minimum bend radius for the diameter, from the standard's table."""
    dia = Decimal(diameter_mm)
    for band in load_standards()[standard]["bend_radius"]:
        if dia <= Decimal(str(band["max_dia"])):
            return dia * Decimal(str(band["factor"]))
    return dia * Decimal("2")


def cut_length(standard: str, code: str, diameter_mm: Decimal, dims: dict[str, Decimal | None]) -> Decimal:
    """Cut length of one bar in mm, rounded to the nearest 5 mm as schedules quote it."""
    shape = find_shape(standard, code)
    missing = [d for d in shape["dimensions"] if dims.get(d) is None]
    if missing:
        raise BbsError(f"Shape {code} needs dimension(s) {', '.join(missing)}")
    variables: dict[str, Any] = {d: dims.get(d) or Decimal("0") for d in DIMENSIONS}
    variables["dia"] = Decimal(diameter_mm)
    variables["r"] = bend_radius(standard, diameter_mm)
    try:
        value = safe_eval(shape["formula"], variables)
    except MeasurementError as exc:
        raise BbsError(f"Shape {code} formula cannot be evaluated: {exc}") from exc
    if value <= 0:
        raise BbsError(f"Shape {code} gives a cut length of {value} mm; check the dimensions")
    return (value / 5).quantize(Decimal("1"), ROUND_HALF_UP) * 5


def compute_row(
    *,
    standard: str,
    code: str,
    diameter_mm: Decimal,
    dims: dict[str, Decimal | None],
    members_count: int,
    bars_per_member: int,
) -> dict[str, Decimal]:
    """Cut length, unit weight, total length and weight of one schedule row."""
    length = cut_length(standard, code, diameter_mm, dims)
    uw = unit_weight(diameter_mm)
    total_m = (length * members_count * bars_per_member / 1000).quantize(Decimal("0.001"))
    return {
        "cut_length_mm": length,
        "unit_weight_kg_m": uw,
        "total_length_m": total_m,
        "weight_kg": (total_m * uw).quantize(Decimal("0.001"), ROUND_HALF_UP),
    }


def totals_by_diameter(rows: list[Any]) -> list[dict[str, Any]]:
    """Bars, length and weight per diameter, smallest diameter first."""
    acc: dict[Decimal, dict[str, Any]] = {}
    for row in rows:
        key = Decimal(row.diameter_mm).normalize()
        t = acc.setdefault(
            key, {"diameter_mm": key, "bar_count": 0, "total_length_m": Decimal("0"), "weight_kg": Decimal("0")}
        )
        t["bar_count"] += row.members_count * row.bars_per_member
        t["total_length_m"] += Decimal(row.total_length_m)
        t["weight_kg"] += Decimal(row.weight_kg)
    return [acc[k] for k in sorted(acc)]


CSV_COLUMNS = (
    "member",
    "bar_mark",
    "shape_standard",
    "shape_code",
    "diameter_mm",
    "dim_a",
    "dim_b",
    "dim_c",
    "dim_d",
    "dim_e",
    "members_count",
    "bars_per_member",
    "cut_length_mm",
    "total_length_m",
    "unit_weight_kg_m",
    "weight_kg",
    "steel_grade",
    "lap_length_mm",
    "notes",
)


def render_csv(rows: list[Any]) -> str:
    """The schedule as CSV, one row per bar mark, totals per diameter below."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow(["" if getattr(row, c) is None else getattr(row, c) for c in CSV_COLUMNS])
    writer.writerow([])
    writer.writerow(["diameter_mm", "bar_count", "total_length_m", "weight_kg"])
    for t in totals_by_diameter(rows):
        writer.writerow([t["diameter_mm"], t["bar_count"], t["total_length_m"], t["weight_kg"]])
    return buf.getvalue()
