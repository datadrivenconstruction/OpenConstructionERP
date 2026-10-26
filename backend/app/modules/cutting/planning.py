# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bridge between stored jobs and the pure optimisers.

Converts millimetre Decimals into the optimisers' integer units (tenths of a
millimetre), runs the optimiser, and turns the result back into the plan
figures and the layout the UI, the PDF and the workbook draw from. Works on any
object with the job / piece / stock attributes, so it is tested without a
database.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.modules.cutting.linear import (
    LinearPiece,
    LinearSettings,
    LinearStock,
    optimise_linear,
    remnant,
    reusable_offcut,
    scrap,
)
from app.modules.cutting.sheet import (
    SheetPiece,
    SheetSettings,
    SheetStock,
    optimise_sheets,
    reusable_offcuts,
    sheet_scrap,
)

#: Optimiser units per millimetre.
SCALE = 10
_MM = Decimal("0.1")
_Q4 = Decimal("0.0001")
_PCT = Decimal("0.01")
_HUNDRED = Decimal("100")
LINEAR_ALGORITHM = "pattern-greedy+local-search"
LINEAR_EXACT_ALGORITHM = "pattern-greedy+branch-and-bound"
SHEET_ALGORITHM = "guillotine-best-area-fit"


def to_units(mm: Decimal | int | float | str | None) -> int:
    """Millimetres to integer optimiser units (0.1 mm), rounded half up."""
    if mm is None:
        return 0
    return int((Decimal(str(mm)) * SCALE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_mm(units: int) -> Decimal:
    """Integer optimiser units back to millimetres."""
    return (Decimal(units) / SCALE).quantize(_MM)


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    if whole <= 0:
        return Decimal("0.00")
    return (part / whole * _HUNDRED).quantize(_PCT, rounding=ROUND_HALF_UP)


@dataclass
class PlanFigures:
    """Everything a plan row stores, computed from one optimiser run."""

    kind: str
    algorithm: str
    stock_count: int = 0
    pieces_placed: int = 0
    pieces_unplaced: int = 0
    stock_total: Decimal = Decimal("0")
    pieces_total: Decimal = Decimal("0")
    offcut_total: Decimal = Decimal("0")
    scrap_total: Decimal = Decimal("0")
    yield_pct: Decimal = Decimal("0")
    waste_pct: Decimal = Decimal("0")
    cost: Decimal = Decimal("0")
    exact: bool = False
    proven_optimal: bool = False
    elapsed_ms: int = 0
    layout: dict[str, Any] = field(default_factory=dict)
    stock_usage: list[dict[str, Any]] = field(default_factory=list)
    offcuts: list[dict[str, Any]] = field(default_factory=list)
    unplaced: list[dict[str, Any]] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)

    @property
    def waste_factor(self) -> Decimal:
        """Gross-to-net multiplier the plan measured: (pieces + scrap) / pieces."""
        if self.pieces_total <= 0:
            return Decimal("1")
        return ((self.pieces_total + self.scrap_total) / self.pieces_total).quantize(_Q4, rounding=ROUND_HALF_UP)


def _settings_snapshot(job: Any) -> dict[str, Any]:
    return {
        "kerf_mm": str(job.kerf_mm),
        "trim_mm": str(job.trim_mm),
        "min_offcut_mm": str(job.min_offcut_mm),
        "yield_threshold_pct": str(job.yield_threshold_pct),
    }


def _stock_meta(stocks: Iterable[Any]) -> dict[str, Any]:
    return {s.ref: s for s in stocks}


def _usage(rows: list[tuple[Any, int]], *, sheet: bool) -> list[dict[str, Any]]:
    """Per stock entry: how many were cut and what they cost."""
    out = []
    for stock, count in rows:
        if count <= 0:
            continue
        unit_cost = Decimal("0") if stock.is_offcut else Decimal(str(stock.unit_cost or 0))
        out.append(
            {
                "ref": stock.ref,
                "label": stock.label or "",
                "length_mm": str(Decimal(str(stock.length_mm)).quantize(_MM)),
                "width_mm": str(Decimal(str(stock.width_mm)).quantize(_MM)) if sheet and stock.width_mm else None,
                "count": count,
                "unit_cost": str(unit_cost),
                "cost": str((unit_cost * count).quantize(_Q4)),
                "is_offcut": bool(stock.is_offcut),
                "inventory_item_id": str(stock.inventory_item_id) if stock.inventory_item_id else None,
            }
        )
    return out


def plan_linear(job: Any, *, time_limit_s: float = 2.0) -> PlanFigures:
    """Optimise a linear job and compute its plan figures."""
    stocks_by_ref = _stock_meta(job.stocks)
    labels = {p.ref: p.label or "" for p in job.pieces}
    settings = LinearSettings(
        kerf=to_units(job.kerf_mm),
        trim=to_units(job.trim_mm),
        min_offcut=to_units(job.min_offcut_mm),
        time_limit_s=time_limit_s,
    )
    pieces = [LinearPiece(p.ref, to_units(p.length_mm), int(p.quantity), p.label or "") for p in job.pieces]
    stocks = [
        LinearStock(
            s.ref,
            to_units(s.length_mm),
            Decimal("0") if s.is_offcut else Decimal(str(s.unit_cost or 0)),
            s.available,
            bool(s.is_offcut),
            s.label or "",
        )
        for s in job.stocks
    ]
    result = optimise_linear(pieces, stocks, settings)
    figures = PlanFigures(
        kind="linear",
        algorithm=LINEAR_EXACT_ALGORITHM if result.exact else LINEAR_ALGORITHM,
        exact=result.exact,
        proven_optimal=result.proven_optimal,
        elapsed_ms=result.elapsed_ms,
        settings=_settings_snapshot(job),
    )
    bars_out = []
    stock_units = piece_units = offcut_units = scrap_units = 0
    counts: dict[str, int] = {}
    offcut_groups: dict[int, int] = {}
    cost = Decimal("0")
    for idx, bar in enumerate(result.bars, start=1):
        offset = settings.trim
        cuts = []
        for n, (ref, length) in enumerate(bar.cuts):
            if n:
                offset += settings.kerf
            cuts.append(
                {
                    "ref": ref,
                    "label": labels.get(ref, ""),
                    "length_mm": str(to_mm(length)),
                    "offset_mm": str(to_mm(offset)),
                }
            )
            offset += length
        off = reusable_offcut(bar, settings)
        waste = scrap(bar, settings)
        stock = stocks_by_ref[bar.stock_ref]
        bars_out.append(
            {
                "index": idx,
                "stock_ref": bar.stock_ref,
                "stock_label": stock.label or "",
                "length_mm": str(to_mm(bar.stock_length)),
                "is_offcut": bar.is_offcut,
                "inventory_item_id": str(stock.inventory_item_id) if stock.inventory_item_id else None,
                "cost": str(bar.cost if not bar.is_offcut else Decimal("0")),
                "cuts": cuts,
                "remnant_mm": str(to_mm(remnant(bar, settings))),
                "offcut_mm": str(to_mm(off)),
                "scrap_mm": str(to_mm(waste)),
            }
        )
        counts[bar.stock_ref] = counts.get(bar.stock_ref, 0) + 1
        stock_units += bar.stock_length
        piece_units += bar.piece_length
        offcut_units += off
        scrap_units += waste
        if off:
            offcut_groups[off] = offcut_groups.get(off, 0) + 1
        if not bar.is_offcut:
            cost += bar.cost
    figures.layout = {
        "kind": "linear",
        "kerf_mm": str(job.kerf_mm),
        "trim_mm": str(job.trim_mm),
        "bars": bars_out,
    }
    figures.stock_count = len(result.bars)
    figures.pieces_placed = sum(len(b.cuts) for b in result.bars)
    figures.pieces_unplaced = sum(q for _, q in result.unplaced)
    figures.unplaced = [{"ref": ref, "label": labels.get(ref, ""), "quantity": q} for ref, q in result.unplaced]
    figures.offcuts = [
        {"length_mm": str(to_mm(length)), "width_mm": None, "quantity": q}
        for length, q in sorted(offcut_groups.items(), reverse=True)
    ]
    figures.stock_usage = _usage([(s, counts.get(s.ref, 0)) for s in job.stocks], sheet=False)
    m = Decimal(SCALE * 1000)
    figures.stock_total = (Decimal(stock_units) / m).quantize(_Q4)
    figures.pieces_total = (Decimal(piece_units) / m).quantize(_Q4)
    figures.offcut_total = (Decimal(offcut_units) / m).quantize(_Q4)
    figures.scrap_total = (Decimal(scrap_units) / m).quantize(_Q4)
    figures.yield_pct = _pct(Decimal(piece_units), Decimal(stock_units))
    figures.waste_pct = _pct(Decimal(scrap_units), Decimal(stock_units))
    figures.cost = cost.quantize(_Q4)
    return figures


def plan_sheet(job: Any, *, time_limit_s: float = 3.0) -> PlanFigures:
    """Optimise a sheet job and compute its plan figures."""
    stocks_by_ref = _stock_meta(job.stocks)
    labels = {p.ref: p.label or "" for p in job.pieces}
    settings = SheetSettings(
        kerf=to_units(job.kerf_mm),
        trim=to_units(job.trim_mm),
        min_offcut=to_units(job.min_offcut_mm),
        time_limit_s=time_limit_s,
    )
    pieces = [
        SheetPiece(
            p.ref, to_units(p.length_mm), to_units(p.width_mm), int(p.quantity), bool(p.rotatable), p.label or ""
        )
        for p in job.pieces
    ]
    stocks = [
        SheetStock(
            s.ref,
            to_units(s.length_mm),
            to_units(s.width_mm),
            Decimal("0") if s.is_offcut else Decimal(str(s.unit_cost or 0)),
            s.available,
            bool(s.is_offcut),
            s.label or "",
        )
        for s in job.stocks
    ]
    result = optimise_sheets(pieces, stocks, settings)
    figures = PlanFigures(
        kind="sheet",
        algorithm=SHEET_ALGORITHM,
        elapsed_ms=result.elapsed_ms,
        settings=_settings_snapshot(job),
    )
    sheets_out = []
    stock_area = piece_area = offcut_area = scrap_area = 0
    counts: dict[str, int] = {}
    offcut_groups: dict[tuple[int, int], int] = {}
    cost = Decimal("0")
    for idx, sh in enumerate(result.sheets, start=1):
        offs = reusable_offcuts(sh, settings)
        waste = sheet_scrap(sh, settings)
        stock = stocks_by_ref[sh.stock_ref]
        sheets_out.append(
            {
                "index": idx,
                "stock_ref": sh.stock_ref,
                "stock_label": stock.label or "",
                "length_mm": str(to_mm(sh.width)),
                "width_mm": str(to_mm(sh.height)),
                "is_offcut": sh.is_offcut,
                "inventory_item_id": str(stock.inventory_item_id) if stock.inventory_item_id else None,
                "cost": str(sh.cost if not sh.is_offcut else Decimal("0")),
                "placements": [
                    {
                        "ref": p.ref,
                        "label": labels.get(p.ref, ""),
                        "x_mm": str(to_mm(p.x)),
                        "y_mm": str(to_mm(p.y)),
                        "length_mm": str(to_mm(p.w)),
                        "width_mm": str(to_mm(p.h)),
                        "rotated": p.rotated,
                    }
                    for p in sh.placements
                ],
                "offcuts": [
                    {
                        "x_mm": str(to_mm(r.x)),
                        "y_mm": str(to_mm(r.y)),
                        "length_mm": str(to_mm(r.w)),
                        "width_mm": str(to_mm(r.h)),
                    }
                    for r in offs
                ],
                "scrap_m2": str((Decimal(waste) / Decimal(SCALE * SCALE * 1_000_000)).quantize(_Q4)),
            }
        )
        counts[sh.stock_ref] = counts.get(sh.stock_ref, 0) + 1
        stock_area += sh.area
        piece_area += sh.piece_area
        offcut_area += sum(r.area for r in offs)
        scrap_area += waste
        for r in offs:
            key = (max(r.w, r.h), min(r.w, r.h))
            offcut_groups[key] = offcut_groups.get(key, 0) + 1
        if not sh.is_offcut:
            cost += sh.cost
    figures.layout = {
        "kind": "sheet",
        "kerf_mm": str(job.kerf_mm),
        "trim_mm": str(job.trim_mm),
        "sheets": sheets_out,
    }
    figures.stock_count = len(result.sheets)
    figures.pieces_placed = sum(len(s.placements) for s in result.sheets)
    figures.pieces_unplaced = sum(q for _, q in result.unplaced)
    figures.unplaced = [{"ref": ref, "label": labels.get(ref, ""), "quantity": q} for ref, q in result.unplaced]
    figures.offcuts = [
        {"length_mm": str(to_mm(a)), "width_mm": str(to_mm(b)), "quantity": q}
        for (a, b), q in sorted(offcut_groups.items(), reverse=True)
    ]
    figures.stock_usage = _usage([(s, counts.get(s.ref, 0)) for s in job.stocks], sheet=True)
    m2 = Decimal(SCALE * SCALE * 1_000_000)
    figures.stock_total = (Decimal(stock_area) / m2).quantize(_Q4)
    figures.pieces_total = (Decimal(piece_area) / m2).quantize(_Q4)
    figures.offcut_total = (Decimal(offcut_area) / m2).quantize(_Q4)
    figures.scrap_total = (Decimal(scrap_area) / m2).quantize(_Q4)
    figures.yield_pct = _pct(Decimal(piece_area), Decimal(stock_area))
    figures.waste_pct = _pct(Decimal(scrap_area), Decimal(stock_area))
    figures.cost = cost.quantize(_Q4)
    return figures


def plan_job(job: Any) -> PlanFigures:
    """Optimise a job of either kind."""
    return plan_sheet(job) if job.kind == "sheet" else plan_linear(job)


def confidence(figures: PlanFigures, threshold_pct: Decimal) -> float:
    """How far the user can lean on the proposal.

    1.0 when the search proved the plan optimal; 0.9 for a complete heuristic
    plan that meets the yield threshold; 0.75 below it; 0.4 when pieces are
    left unplaced, because then the plan understates the material needed.
    """
    if figures.pieces_unplaced:
        return 0.4
    if figures.proven_optimal:
        return 1.0
    return 0.9 if figures.yield_pct >= threshold_pct else 0.75


__all__ = [
    "LINEAR_ALGORITHM",
    "LINEAR_EXACT_ALGORITHM",
    "SCALE",
    "SHEET_ALGORITHM",
    "PlanFigures",
    "confidence",
    "plan_job",
    "plan_linear",
    "plan_sheet",
    "to_mm",
    "to_units",
]
