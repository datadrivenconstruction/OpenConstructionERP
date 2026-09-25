# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Which budget line a paid supplier invoice lands on, and how much.

``FinanceService.pay_invoice`` recomputes ``ProjectBudget.actual`` from the
project's paid invoices each time one is paid. The rules it applies live here,
pure, so each can be pinned without a database:

* Only payable (supplier) invoices are cost. A client invoice being paid is
  income and never enters a budget line.
* Everything is net of VAT, the basis the budget was set on. An invoice with
  lines contributes each line's amount; one without contributes its subtotal,
  never its gross total.
* A paid amount lands on exactly ONE budget line: the line with the same WBS,
  category and currency, else the project-level line of that currency (no WBS,
  no category), else the line with that WBS in that currency, else the oldest
  line in that currency. Never on every line, and never on a line priced in
  another currency.
* An invoice against a purchase order is the same money the goods receipts of
  that order already moved into actual. So for each order only what has been
  paid beyond what was received is added, on the line that carries the order's
  commitment, and the same amount is released from that commitment. After
  receipt and payment the order is in actual once, at the larger of the two.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

ZERO = Decimal("0")

#: ``ProjectBudget.metadata_`` key prefix recording how much of an order's
#: commitment its paid invoices have released, so a recompute applies only
#: the difference.
RELEASED_BY_PAYMENT_PREFIX = "released_by_payment:"
#: The prefix the order approval handler stamps (``finance/events.py``).
COMMITTED_FROM_PO_PREFIX = "committed_from_po:"


@dataclass(frozen=True)
class BudgetLineRow:
    """A ProjectBudget row, in the order the rows were created."""

    id: uuid.UUID
    wbs_id: str | None
    category: str | None
    currency: str


@dataclass(frozen=True)
class PaidLine:
    """One net amount of a paid invoice, with the bucket it belongs to."""

    wbs_id: str | None
    category: str | None
    amount: Decimal


@dataclass(frozen=True)
class PaidInvoice:
    """A paid payable invoice, reduced to its net amounts."""

    currency: str
    po_id: uuid.UUID | None
    lines: Sequence[PaidLine]


@dataclass
class ActualsPlan:
    """What each budget line's actual should be, and what to release."""

    #: Invoice-sourced actual per budget line (receipt-sourced actual is kept
    #: by the caller from the row's ``actual_from_receipts`` marker).
    actual: dict[uuid.UUID, Decimal] = field(default_factory=dict)
    #: Per budget line, per order: the commitment its payments release in total.
    released: dict[uuid.UUID, dict[uuid.UUID, Decimal]] = field(default_factory=dict)
    #: Currency -> amount that found no line in its currency.
    unplaced: dict[str, Decimal] = field(default_factory=dict)


def _norm(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def pick_line(
    rows: Sequence[BudgetLineRow], wbs_id: str | None, category: str | None, currency: str
) -> uuid.UUID | None:
    """The one budget line a bucket lands on (see the module docstring)."""
    same_ccy = [r for r in rows if r.currency == currency]
    if not same_ccy:
        return None
    wbs, cat = _norm(wbs_id), _norm(category)
    for row in same_ccy:
        if _norm(row.wbs_id) == wbs and _norm(row.category) == cat:
            return row.id
    for row in same_ccy:
        if _norm(row.wbs_id) is None and _norm(row.category) is None:
            return row.id
    if wbs is not None:
        for row in same_ccy:
            if _norm(row.wbs_id) == wbs:
                return row.id
    return same_ccy[0].id


def plan_actuals(
    rows: Sequence[BudgetLineRow],
    invoices: Iterable[PaidInvoice],
    *,
    received_by_po: dict[uuid.UUID, Decimal],
    committed_by_po: dict[uuid.UUID, tuple[uuid.UUID, Decimal]],
) -> ActualsPlan:
    """Attribute paid invoices to budget lines.

    ``received_by_po`` is the confirmed goods receipt value per order, net.
    ``committed_by_po`` maps an order to the line carrying its commitment
    marker and the amount it committed.
    """
    plan = ActualsPlan()

    def _land(line_id: uuid.UUID | None, currency: str, amount: Decimal) -> None:
        if amount == 0:
            return
        if line_id is None:
            plan.unplaced[currency] = plan.unplaced.get(currency, ZERO) + amount
            return
        plan.actual[line_id] = plan.actual.get(line_id, ZERO) + amount

    paid_on_po: dict[uuid.UUID, tuple[str, Decimal, list[PaidLine]]] = {}
    for inv in invoices:
        if inv.po_id is not None:
            ccy, total, lines = paid_on_po.get(inv.po_id, (inv.currency, ZERO, []))
            paid_on_po[inv.po_id] = (ccy, total + sum((ln.amount for ln in inv.lines), ZERO), [*lines, *inv.lines])
            continue
        for ln in inv.lines:
            _land(pick_line(rows, ln.wbs_id, ln.category, inv.currency), inv.currency, ln.amount)

    for po_id, (currency, paid, lines) in paid_on_po.items():
        received = received_by_po.get(po_id, ZERO)
        beyond = max(paid - received, ZERO)
        carrier = committed_by_po.get(po_id)
        if carrier is not None:
            line_id, committed = carrier
            _land(line_id, currency, beyond)
            release = max(min(committed, paid) - received, ZERO)
            if release > 0:
                plan.released.setdefault(line_id, {})[po_id] = release
        else:
            # The order committed nothing on any line (approved before the
            # budget existed): land what was paid beyond receipt where its
            # first invoice line points.
            first = lines[0] if lines else PaidLine(None, None, ZERO)
            _land(pick_line(rows, first.wbs_id, first.category, currency), currency, beyond)
    return plan
