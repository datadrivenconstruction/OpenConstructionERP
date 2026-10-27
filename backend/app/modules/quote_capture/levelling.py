# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Levelling​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ maths: several quotes against one reference scope.

Each reference row (a BOQ position or tender package item) gets one cell per
quote. A quoted cell is levelled to the reference quantity (rate x reference
quantity), so a supplier who priced 95 m2 of a 100 m2 item is compared at 100. A
row a quote does not price is a scope gap: it is filled with a plug rate, taken
in this order from the supplier price list, the BOQ rate, and the median of the
other quotes' rates for the same row. The plug source is kept on the cell so
the reviewer sees why an adjusted total moved.

Quote lines that match no reference row are extras: they stay visible and are
added to the adjusted total at their quoted amount, because they are still
money the supplier asks for.

Pure functions, Decimal throughout, no database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from typing import Any

from app.modules.quote_capture.numbers import to_decimal

_CENT = Decimal("0.01")


def _d(value: Any) -> Decimal:
    return to_decimal(value) or Decimal("0")


def money(value: Decimal) -> str:
    return str(value.quantize(_CENT, rounding=ROUND_HALF_UP))


@dataclass
class RefRow:
    position_id: str
    ordinal: str
    description: str
    unit: str
    quantity: Decimal
    boq_rate: Decimal
    price_list_rate: Decimal | None = None


@dataclass
class QuoteInput:
    quote_id: str
    supplier: str
    currency: str
    lines: list[dict[str, Any]]
    exclusions: int = 0
    stated_total: Decimal | None = None


@dataclass
class QuoteSummary:
    quote_id: str
    supplier: str
    currency: str
    quoted_total: Decimal = Decimal("0")
    levelled_total: Decimal = Decimal("0")
    plug_total: Decimal = Decimal("0")
    extras_total: Decimal = Decimal("0")
    adjusted_total: Decimal = Decimal("0")
    priced_rows: int = 0
    gap_rows: int = 0
    extra_lines: int = 0
    exclusions: int = 0
    rank: int = 0
    extras: list[dict[str, Any]] = field(default_factory=list)


def _matched_pid(line: dict[str, Any]) -> str | None:
    match = line.get("match") or {}
    if match.get("status") in {"confirmed", "suggested"} and match.get("position_id"):
        return str(match["position_id"])
    return None


def plug_rate(row: RefRow, other_rates: list[Decimal]) -> tuple[Decimal, str]:
    """The rate a gap is filled with, and where it came from."""
    if row.price_list_rate is not None and row.price_list_rate > 0:
        return row.price_list_rate, "price_list"
    if row.boq_rate > 0:
        return row.boq_rate, "boq"
    if other_rates:
        return Decimal(str(median(other_rates))), "median_of_quotes"
    return Decimal("0"), "none"


def level(rows: list[RefRow], quotes: list[QuoteInput]) -> dict[str, Any]:
    """Return ``{"rows": [...], "quotes": [...]}`` with per-cell status and adjusted totals."""
    index: dict[str, dict[str, dict[str, Any]]] = {}
    for q in quotes:
        per: dict[str, dict[str, Any]] = {}
        for line in q.lines:
            pid = _matched_pid(line)
            if pid is None:
                continue
            if pid in per:  # two lines on one row: add them up
                prev = per[pid]
                prev["total"] = str(_d(prev["total"]) + _d(line.get("total")))
                prev["quantity"] = str(_d(prev["quantity"]) + _d(line.get("quantity")))
            else:
                per[pid] = {"total": line.get("total"), "quantity": line.get("quantity"), "rate": line.get("unit_rate")}
        index[q.quote_id] = per

    summaries = {q.quote_id: QuoteSummary(q.quote_id, q.supplier, q.currency, exclusions=q.exclusions) for q in quotes}
    out_rows: list[dict[str, Any]] = []
    for row in rows:
        rates = {qid: _d(per[row.position_id]["rate"]) for qid, per in index.items() if row.position_id in per}
        cells: list[dict[str, Any]] = []
        for q in quotes:
            s = summaries[q.quote_id]
            got = index[q.quote_id].get(row.position_id)
            if got is not None:
                rate = _d(got["rate"])
                quoted = _d(got["total"]) or rate * _d(got["quantity"])
                levelled = rate * row.quantity if row.quantity > 0 else quoted
                s.quoted_total += quoted
                s.levelled_total += levelled
                s.priced_rows += 1
                status = "quoted" if abs(levelled - quoted) <= _CENT else "levelled"
                cells.append(
                    {
                        "quote_id": q.quote_id,
                        "status": status,
                        "unit_rate": money(rate),
                        "quoted_total": money(quoted),
                        "adjusted_total": money(levelled),
                        "plug_source": None,
                    }
                )
            else:
                others = [r for qid, r in rates.items() if qid != q.quote_id and r > 0]
                rate, source = plug_rate(row, others)
                plug = rate * row.quantity
                s.plug_total += plug
                s.gap_rows += 1
                cells.append(
                    {
                        "quote_id": q.quote_id,
                        "status": "gap",
                        "unit_rate": money(rate),
                        "quoted_total": "0.00",
                        "adjusted_total": money(plug),
                        "plug_source": source,
                    }
                )
        priced = [Decimal(c["adjusted_total"]) for c in cells if c["status"] != "gap"]
        low = min(priced) if priced else None
        for c in cells:
            c["lowest"] = low is not None and c["status"] != "gap" and Decimal(c["adjusted_total"]) == low
        out_rows.append(
            {
                "position_id": row.position_id,
                "ordinal": row.ordinal,
                "description": row.description,
                "unit": row.unit,
                "quantity": str(row.quantity),
                "boq_rate": money(row.boq_rate),
                "price_list_rate": money(row.price_list_rate) if row.price_list_rate is not None else None,
                "cells": cells,
            }
        )

    ref_ids = {r.position_id for r in rows}
    for q in quotes:
        s = summaries[q.quote_id]
        for line in q.lines:
            pid = _matched_pid(line)
            if pid is None or pid not in ref_ids:
                amount = _d(line.get("total"))
                s.extras_total += amount
                s.extra_lines += 1
                s.extras.append(
                    {"line_id": line.get("id"), "description": line.get("description"), "total": money(amount)}
                )
        s.adjusted_total = s.levelled_total + s.plug_total + s.extras_total

    ranked = sorted(summaries.values(), key=lambda s: s.adjusted_total)
    for i, s in enumerate(ranked, start=1):
        s.rank = i
    return {
        "rows": out_rows,
        "quotes": [
            {
                "quote_id": s.quote_id,
                "supplier": s.supplier,
                "currency": s.currency,
                "quoted_total": money(s.quoted_total),
                "levelled_total": money(s.levelled_total),
                "plug_total": money(s.plug_total),
                "extras_total": money(s.extras_total),
                "adjusted_total": money(s.adjusted_total),
                "priced_rows": s.priced_rows,
                "gap_rows": s.gap_rows,
                "extra_lines": s.extra_lines,
                "exclusions": s.exclusions,
                "rank": s.rank,
                "extras": s.extras,
            }
            for s in summaries.values()
        ],
    }
