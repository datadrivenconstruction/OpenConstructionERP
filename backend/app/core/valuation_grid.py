"""Submitted / assessed / certified grid of one valuation document.

A valuation document is a client progress claim or a subcontractor payment
application. Both store three quantities per line; this module lays them out
side by side with their amounts and says where every figure comes from:
``stored`` (a field on the line), ``computed`` (quantity times a named rate)
or ``missing`` (nothing to price it with). No I/O, so both modules and the
tests share it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

STAGES = ("submitted", "assessed", "certified")
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class GridLine:
    """One line as the owning module reads it."""

    id: str
    label: str
    submitted_qty: Decimal
    assessed_qty: Decimal
    certified_qty: Decimal
    unit: str | None = None
    #: Unit rate the computed amounts use, and the field it was read from.
    rate: Decimal | None = None
    rate_source: str | None = None
    #: Amounts stored on the line per stage, with the field name; they win over a computed amount.
    submitted_amount: Decimal | None = None
    submitted_amount_field: str | None = None
    assessed_amount: Decimal | None = None
    assessed_amount_field: str | None = None
    certified_amount: Decimal | None = None
    certified_amount_field: str | None = None
    #: Certified quantity of this line on earlier documents that were not rejected.
    prior_certified_qty: Decimal = Decimal("0")
    #: Running total before and after this document, and the field it is read from.
    prior_cumulative: Decimal | None = None
    cumulative: Decimal | None = None
    cumulative_field: str | None = None


def _figure(value: Decimal | None, source: str, field: str | None) -> dict[str, Any]:
    return {"value": None if value is None else format(value, "f"), "source": source, "field": field}


def _amount(line: GridLine, stage: str, qty: Decimal) -> tuple[Decimal | None, dict[str, Any]]:
    stored = getattr(line, f"{stage}_amount")
    if stored is not None:
        return stored, _figure(stored, "stored", getattr(line, f"{stage}_amount_field"))
    if line.rate is not None and line.rate > 0:
        value = (qty * line.rate).quantize(_CENT)
        return value, _figure(value, "computed", line.rate_source)
    return None, _figure(None, "missing", None)


def build_grid(lines: list[GridLine]) -> dict[str, Any]:
    """Rows with quantity and amount per stage, plus priced totals per stage."""
    rows: list[dict[str, Any]] = []
    totals: dict[str, Decimal | None] = dict.fromkeys(STAGES)
    for line in lines:
        stages: dict[str, Any] = {}
        for stage in STAGES:
            qty: Decimal = getattr(line, f"{stage}_qty")
            value, amount = _amount(line, stage, qty)
            if value is not None:
                totals[stage] = (totals[stage] or Decimal("0")) + value
            stages[stage] = {"qty": _figure(qty, "stored", f"{stage}_qty"), "amount": amount}
        rows.append(
            {
                "id": line.id,
                "label": line.label,
                "unit": line.unit,
                "rate": None if line.rate is None else format(line.rate, "f"),
                "rate_source": line.rate_source,
                "stages": stages,
                "cumulative_certified_qty": format(line.prior_certified_qty + line.certified_qty, "f"),
                "prior_cumulative": None if line.prior_cumulative is None else format(line.prior_cumulative, "f"),
                "cumulative": None if line.cumulative is None else format(line.cumulative, "f"),
                "cumulative_field": line.cumulative_field,
                "findings": [],
            }
        )
    return {"rows": rows, "totals": {k: None if v is None else format(v, "f") for k, v in totals.items()}}


def findings_payload(lines: list[GridLine], note: str) -> dict[str, Any]:
    """The ``valuation_lines`` block the commercial control rules read."""
    return {
        "valuation_lines": [
            {
                "id": ln.id,
                "label": ln.label,
                "submitted": str(ln.submitted_qty),
                "assessed": str(ln.assessed_qty),
                "certified": str(ln.certified_qty),
                "prior_cumulative": None if ln.prior_cumulative is None else str(ln.prior_cumulative),
                "cumulative": None if ln.cumulative is None else str(ln.cumulative),
                "note": note,
            }
            for ln in lines
        ]
    }


async def grid_with_findings(lines: list[GridLine], *, note: str, target_type: str, target_id: str) -> dict[str, Any]:
    """The grid with each row's ``valuation.*`` findings attached."""
    from app.core.validation.rules.commercial_control import evaluate

    grid = build_grid(lines)
    findings = await evaluate(findings_payload(lines, note), target_type=target_type, target_id=target_id)
    by_line: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        if str(f.get("rule_id", "")).startswith("valuation."):
            by_line.setdefault(str(f.get("element_ref") or ""), []).append(f)
    for row in grid["rows"]:
        row["findings"] = by_line.get(row["id"], [])
    return grid


class ValuationNote(BaseModel):
    """Why a running total went down, or any other remark on the valuation."""

    note: str = Field(default="", max_length=2000)


class ValuationGridResponse(BaseModel):
    """Side-by-side grid of one claim or payment application."""

    source_kind: str
    source_id: str
    document_number: str
    status: str
    currency: str
    note: str
    rows: list[dict[str, Any]]
    totals: dict[str, str | None]
