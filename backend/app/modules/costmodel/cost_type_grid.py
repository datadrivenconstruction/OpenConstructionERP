# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Budget, committed, actual and forecast per cost code x cost type.

One row per budget line, grouped under its cost code: the code of its cost
line, else the ordinal of the bill position it came from, else no code. Per
row:

* **budget**: the line's planned amount;
* **committed**: what the 5D dashboard counts on the line (orders and
  subcontracts booked to it, its share of the documents on its cost line, or
  the typed value), so the grid adds up to the dashboard;
* **actual**: invoices booked to the line;
* **forecast**: the line's forecast final cost, the one figure a person edits;
* **EAC**: the forecast, but never below what is already committed or spent,
  because a line cannot finish below money already bound. ``eac_basis`` names
  the figure that set it;
* **variance**: budget less EAC, negative when the line is heading over.

Subtotals come per cost code and per cost type, all in the project currency.
A line kept in another currency converts through the project's FX table and is
read-only here (its forecast is typed in its own currency on the line itself).

``assemble_grid`` is pure and holds all the arithmetic, so the worked examples
in the tests run without a database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, PlainSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.code_lists import code_sort_key
from app.core.cost_types import COST_TYPES, LEGACY_BUDGET_CATEGORIES, is_budget_category
from app.modules.costmodel.cost_type_rules import PAYLOAD_KEY, RULE_SET
from app.modules.costmodel.schemas import _serialise_money

ZERO = Decimal("0")
UNTYPED = "untyped"
_TYPE_ORDER = {name: idx for idx, name in enumerate(COST_TYPES + LEGACY_BUDGET_CATEGORIES)}

Money = Annotated[Decimal, PlainSerializer(_serialise_money, return_type=str, when_used="json")]
EacBasis = Literal["forecast", "committed", "actual"]


@dataclass(frozen=True)
class GridLine:
    """One budget line, every amount already in the project currency."""

    id: str
    cost_code: str
    cost_code_title: str
    category: str
    description: str
    currency: str
    budget: Decimal
    committed: Decimal
    actual: Decimal
    forecast: Decimal
    committed_from_documents: bool = False
    split_basis: str | None = None
    unpriced: list[str] = field(default_factory=list)
    editable: bool = True


class GridTotals(BaseModel):
    budget: Money = ZERO
    committed: Money = ZERO
    actual: Money = ZERO
    forecast: Money = ZERO
    eac: Money = ZERO
    variance: Money = ZERO


class GridRow(GridTotals):
    line_id: str
    cost_code: str
    cost_code_title: str = ""
    cost_type: str | None = Field(None, description="A stored budget category, or null when outside the vocabulary.")
    category: str
    description: str = ""
    currency: str = ""
    eac_basis: EacBasis = "forecast"
    committed_from_documents: bool = False
    split_basis: str | None = None
    editable: bool = True


class CostCodeGroup(BaseModel):
    cost_code: str
    cost_code_title: str = ""
    rows: list[GridRow]
    subtotal: GridTotals


class CostTypeSubtotal(BaseModel):
    cost_type: str = Field(..., description="A budget category, or 'untyped'.")
    line_count: int
    totals: GridTotals


class GridFinding(BaseModel):
    rule_id: str
    severity: Literal["error", "warning", "info"]
    message: str
    suggestion: str = ""
    element_ref: str | None = None


class CostTypeGridResponse(BaseModel):
    project_id: str
    currency: str
    cost_types: list[str] = Field(default_factory=lambda: list(COST_TYPES))
    groups: list[CostCodeGroup]
    by_type: list[CostTypeSubtotal]
    total: GridTotals
    line_count: int
    findings: list[GridFinding] = Field(default_factory=list)


def type_key(category: str) -> str:
    """The cost-type bucket of a stored category: the category itself, or ``untyped``."""
    value = (category or "").strip().lower()
    return value if is_budget_category(value) else UNTYPED


def eac_of(forecast: Decimal, committed: Decimal, actual: Decimal) -> tuple[Decimal, EacBasis]:
    """EAC is the forecast, floored by committed and actual; the basis names the figure that won."""
    best: tuple[Decimal, EacBasis] = (forecast, "forecast")
    for value, basis in ((committed, "committed"), (actual, "actual")):
        if value > best[0]:
            best = (value, basis)
    return best


def _add(totals: GridTotals, row: GridTotals) -> None:
    for name in ("budget", "committed", "actual", "forecast", "eac", "variance"):
        setattr(totals, name, getattr(totals, name) + getattr(row, name))


def _row(line: GridLine) -> GridRow:
    eac, basis = eac_of(line.forecast, line.committed, line.actual)
    key = type_key(line.category)
    return GridRow(
        line_id=line.id,
        cost_code=line.cost_code,
        cost_code_title=line.cost_code_title,
        cost_type=None if key == UNTYPED else key,
        category=line.category,
        description=line.description,
        currency=line.currency,
        budget=line.budget,
        committed=line.committed,
        actual=line.actual,
        forecast=line.forecast,
        eac=eac,
        eac_basis=basis,
        variance=line.budget - eac,
        committed_from_documents=line.committed_from_documents,
        split_basis=line.split_basis,
        editable=line.editable,
    )


def _code_order(code: str) -> tuple[int, Any]:
    return (1, ()) if not code else (0, code_sort_key(code))


def assemble_grid(
    lines: list[GridLine],
    *,
    project_id: str,
    currency: str,
    cost_type: str | None = None,
    cost_code: str | None = None,
) -> CostTypeGridResponse:
    """Group budget lines by cost code, total them per code and per type.

    Args:
        lines: Every budget line of the project, amounts in the project currency.
        project_id: Echoed back.
        currency: The project currency the amounts are in.
        cost_type: Keep only lines of this budget category (``untyped`` for the rest).
        cost_code: Keep only lines whose cost code starts with this text.

    Returns:
        The grid: groups in cost-code order, rows in cost-type order (L, M, E,
        S, O, then legacy categories, then untyped), subtotals and the total.
    """
    wanted_type = (cost_type or "").strip().lower() or None
    wanted_code = (cost_code or "").strip()
    kept = [
        line
        for line in lines
        if (wanted_type is None or type_key(line.category) == wanted_type)
        and (not wanted_code or line.cost_code.startswith(wanted_code))
    ]
    by_code: dict[str, list[GridRow]] = {}
    titles: dict[str, str] = {}
    by_type: dict[str, tuple[int, GridTotals]] = {}
    total = GridTotals()
    for line in kept:
        row = _row(line)
        by_code.setdefault(line.cost_code, []).append(row)
        titles.setdefault(line.cost_code, line.cost_code_title)
        key = type_key(line.category)
        count, sub = by_type.get(key, (0, GridTotals()))
        _add(sub, row)
        by_type[key] = (count + 1, sub)
        _add(total, row)

    groups: list[CostCodeGroup] = []
    for code in sorted(by_code, key=_code_order):
        rows = sorted(by_code[code], key=lambda r: (_TYPE_ORDER.get(type_key(r.category), len(_TYPE_ORDER)), r.line_id))
        subtotal = GridTotals()
        for row in rows:
            _add(subtotal, row)
        groups.append(CostCodeGroup(cost_code=code, cost_code_title=titles.get(code, ""), rows=rows, subtotal=subtotal))

    type_rows = [
        CostTypeSubtotal(cost_type=key, line_count=count, totals=sub)
        for key, (count, sub) in sorted(by_type.items(), key=lambda kv: _TYPE_ORDER.get(kv[0], len(_TYPE_ORDER)))
    ]
    return CostTypeGridResponse(
        project_id=project_id,
        currency=currency,
        groups=groups,
        by_type=type_rows,
        total=total,
        line_count=len(kept),
    )


def _line_label(cost_code: str, description: str) -> str:
    """Code and description for a finding; a description that already opens with the code is not prefixed twice."""
    code, text = (cost_code or "").strip(), (description or "").strip()
    if code and text.startswith(code):
        return text
    return " ".join(part for part in (code, text) if part)


def validation_payload(lines: list[GridLine]) -> dict[str, Any]:
    """The ``cost_types`` rule-set payload for a project's budget lines."""
    return {
        PAYLOAD_KEY: {
            "lines": [
                {
                    "line_id": line.id,
                    "label": _line_label(line.cost_code, line.description),
                    "category": line.category,
                    "split_basis": line.split_basis,
                    "unpriced": line.unpriced,
                }
                for line in lines
            ]
        }
    }


async def load_grid_lines(session: AsyncSession, project_id: uuid.UUID) -> tuple[str, list[GridLine]]:
    """Every budget line of a project as grid input, in the project currency.

    Returns:
        ``(project currency, lines)``.
    """
    from app.modules.boq.models import Position
    from app.modules.costmodel.models import CostLine
    from app.modules.costmodel.repository import BudgetLineRepository, _amount_in_base

    repo = BudgetLineRepository(session)
    lines = await repo._list_lines_for_rollup(project_id)
    base, fx = await repo._project_fx_context(project_id)
    committed, _unbudgeted, from_documents = await repo._committed_in_base(project_id, lines, base, fx)

    cost_line_ids = {line.cost_line_id for line in lines if line.cost_line_id is not None}
    position_ids = {line.boq_position_id for line in lines if line.boq_position_id is not None}
    codes: dict[uuid.UUID, tuple[str, str]] = {}
    if cost_line_ids:
        rows = await session.execute(
            select(CostLine.id, CostLine.code, CostLine.description).where(CostLine.id.in_(cost_line_ids))
        )
        codes.update({row_id: (code or "", desc or "") for row_id, code, desc in rows.all()})
    ordinals: dict[uuid.UUID, tuple[str, str]] = {}
    if position_ids:
        rows = await session.execute(
            select(Position.id, Position.ordinal, Position.description).where(Position.id.in_(position_ids))
        )
        ordinals.update({row_id: (ordinal or "", desc or "") for row_id, ordinal, desc in rows.all()})

    out: list[GridLine] = []
    for idx, line in enumerate(lines):
        ccy = (line.currency or "").strip().upper()
        code, title = "", ""
        if line.cost_line_id in codes:
            code, title = codes[line.cost_line_id]
        elif line.boq_position_id in ordinals:
            code, title = ordinals[line.boq_position_id]
        meta = line.metadata_ if isinstance(line.metadata_, dict) else {}
        split = meta.get("cost_type_split")
        out.append(
            GridLine(
                id=str(line.id),
                cost_code=code,
                cost_code_title=title[:200],
                category=line.category or "",
                description=line.description or "",
                currency=ccy or base,
                budget=_amount_in_base(line.planned_amount, ccy, base, fx),
                committed=committed[idx],
                actual=_amount_in_base(line.actual_amount, ccy, base, fx),
                forecast=_amount_in_base(line.forecast_amount, ccy, base, fx),
                committed_from_documents=idx in from_documents,
                split_basis=split.get("basis") if isinstance(split, dict) else None,
                unpriced=[str(x) for x in split.get("unpriced_resources") or []] if isinstance(split, dict) else [],
                editable=not ccy or ccy == base,
            )
        )
    return base, out


async def build_cost_type_grid(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    cost_type: str | None = None,
    cost_code: str | None = None,
    locale: str = "en",
) -> CostTypeGridResponse:
    """The grid for one project, with the ``cost_types`` findings in the caller's language."""
    from app.core.validation.engine import validation_engine

    currency, lines = await load_grid_lines(session, project_id)
    grid = assemble_grid(lines, project_id=str(project_id), currency=currency, cost_type=cost_type, cost_code=cost_code)
    report = await validation_engine.validate(
        data=validation_payload(lines),
        rule_sets=[RULE_SET],
        target_type="cost_type_grid",
        target_id=str(project_id),
        project_id=str(project_id),
        metadata={"locale": locale},
    )
    grid.findings = [
        GridFinding(
            rule_id=result.rule_id,
            severity=result.severity.value,
            message=result.message,
            suggestion=result.suggestion or "",
            element_ref=result.element_ref,
        )
        for result in report.results
        if not result.passed
    ]
    return grid
