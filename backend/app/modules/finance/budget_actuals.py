# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Which budget line each source's committed and actual lands on, and how much.

``finance.cost_position`` works out committed (the open part) and actual per
source: an order, a subcontract, a supplier invoice with neither behind it.
The finance dashboard sums them. ``FinanceService.sync_project_budget`` keeps
the ``ProjectBudget`` rows to the same figures, so the Budgets table adds up
to the dashboard. The rules it applies live here, pure, so each can be pinned
without a database:

* A source lands on exactly ONE budget line per invoice line: the line with
  the same WBS, category and currency, else the line with that WBS in that
  currency, else the project-level line of that currency (no WBS, no
  category), else the oldest line in that currency. Never on every line, and
  never on a line priced in another currency.
* An order already moves money on the rows itself: its approval commits the
  order's net on one row (``committed_from_po:<po>``) and each confirmed goods
  receipt moves its value from committed to actual (``received_from_gr:<gr>``).
  The plan for an order is therefore only the difference between its figures
  and what those markers already put there, on the row that carries them.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from app.modules.finance.cost_position import SourceFigure

ZERO = Decimal("0")

#: ``ProjectBudget.metadata_`` key prefix of what the sync put on a row for one
#: source, as ``"<committed>|<actual>"``, so the next sync applies only the
#: difference and leaves anything typed onto the row alone.
SYNC_PREFIX = "sync:"
#: The prefix the order approval handler stamps (``finance/events.py``).
COMMITTED_FROM_PO_PREFIX = "committed_from_po:"
#: The prefix the goods receipt handler stamps (``finance/events.py``).
RECEIVED_FROM_GR_PREFIX = "received_from_gr:"


@dataclass(frozen=True)
class BudgetLineRow:
    """A ProjectBudget row, in the order the rows were created."""

    id: uuid.UUID
    wbs_id: str | None
    category: str | None
    currency: str


@dataclass
class BudgetPlan:
    """What the sync should have put on each row, per source."""

    #: Row id -> source key -> (committed, actual) the sync contributes.
    per_row: dict[uuid.UUID, dict[str, tuple[Decimal, Decimal]]] = field(default_factory=dict)
    #: Currency -> (committed, actual) that found no line in its currency.
    unplaced: dict[str, tuple[Decimal, Decimal]] = field(default_factory=dict)


def _norm(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def pick_line(
    rows: Sequence[BudgetLineRow], wbs_id: str | None, category: str | None, currency: str
) -> uuid.UUID | None:
    """The one budget line a figure lands on (see the module docstring)."""
    same_ccy = [r for r in rows if r.currency == currency]
    if not same_ccy:
        return None
    wbs, cat = _norm(wbs_id), _norm(category)
    for row in same_ccy:
        if _norm(row.wbs_id) == wbs and _norm(row.category) == cat:
            return row.id
    if wbs is not None:
        for row in same_ccy:
            if _norm(row.wbs_id) == wbs:
                return row.id
    for row in same_ccy:
        if _norm(row.wbs_id) is None and _norm(row.category) is None:
            return row.id
    return same_ccy[0].id


def plan_budget(
    rows: Sequence[BudgetLineRow],
    sources: Iterable[SourceFigure],
    *,
    order_rows: dict[uuid.UUID, uuid.UUID],
    order_handled: dict[uuid.UUID, tuple[Decimal, Decimal]],
) -> BudgetPlan:
    """Place each source's committed and actual on a budget row.

    ``order_rows`` maps an order to the row carrying its approval or receipt
    markers; ``order_handled`` to the (committed, actual) those markers put on
    the rows.
    """
    plan = BudgetPlan()
    for src in sources:
        committed, actual = src.committed, src.actual
        row_id: uuid.UUID | None = None
        if src.kind == "po":
            row_id = order_rows.get(src.ref)
            handled_c, handled_a = order_handled.get(src.ref, (ZERO, ZERO))
            committed -= handled_c
            actual -= handled_a
        if row_id is None:
            row_id = pick_line(rows, src.wbs_id, src.category, src.currency)
        if row_id is None:
            c, a = plan.unplaced.get(src.currency, (ZERO, ZERO))
            plan.unplaced[src.currency] = (c + src.committed, a + src.actual)
            continue
        bucket = plan.per_row.setdefault(row_id, {})
        c, a = bucket.get(src.key, (ZERO, ZERO))
        bucket[src.key] = (c + committed, a + actual)
    return plan


def parse_sync_marker(value: object) -> tuple[Decimal, Decimal]:
    """Read a ``"<committed>|<actual>"`` marker, zero for anything unreadable."""
    parts = str(value or "").split("|")
    out: list[Decimal] = []
    for part in (parts + ["0", "0"])[:2]:
        try:
            out.append(Decimal(part.strip() or "0"))
        except ArithmeticError:
            out.append(ZERO)
    return out[0], out[1]
