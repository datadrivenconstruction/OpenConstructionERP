# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A project's cost position: committed, invoiced and paid, read from the records.

The finance dashboard used to take committed and actual from two columns on
``ProjectBudget`` that event handlers keep up to date. That cache could not
carry the figures a contractor needs:

* an order approved before any budget row existed was never committed at all
  (the handler found no row to add it to and moved on);
* it committed an order at its gross, VAT included, against a net budget;
* subcontract agreements and payment applications have no writer into it, so
  the largest commitments on a typical job never reached finance.

So the dashboard reads them here instead, from the rows that are the record:
purchase orders, supplier invoices and their payments, subcontract agreements
and their payment applications. Every figure is computed per currency and the
caller converts to the project currency, the same as every other dashboard sum.

Basis of each figure
--------------------
``committed`` (net of VAT)
    Each purchase order from approval on, at its net value, and each live
    subcontract agreement at its value. A supplier invoice with no order behind
    it counts at its own net: money spent without an order is committed on the
    day it is invoiced. An order and the invoices raised against it are ONE
    commitment, worth the larger of the two, never their sum. A payment
    application draws down its agreement and never adds to it; an agreement
    that was terminated keeps only what was approved against it.
``invoiced`` (net of VAT)
    Supplier invoices from ``pending`` on, at their subtotal, and payment
    applications finance has approved, at the approved gross. Retention is
    part of the gross: it is owed, only later.
``paid`` (cash, VAT included)
    Payments on supplier invoices, refunds netted out, and the cash paid on
    payment applications (the approved net, retention withheld).
``paid_net`` (net of VAT)
    The same payments with the VAT share taken out, pro rata to the invoice's
    subtotal over its total, so it compares with a net budget.

Receivable (client) invoices are outside all four; this is the cost side.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.models import Invoice, Payment
from app.modules.finance.po_link import invoice_po_link

ZERO = Decimal("0")

#: Order statuses that commit money. Approval is the commitment moment, the
#: same one ``procurement.po.approved`` marks, and an order stays committed
#: through delivery and completion.
COMMITTING_ORDER_STATUSES: frozenset[str] = frozenset({"approved", "issued", "partially_received", "completed"})

#: Supplier invoice statuses that count as invoiced. A draft is still being
#: typed in; a cancelled or credited invoice charges nothing.
INVOICED_STATUSES: frozenset[str] = frozenset({"pending", "approved", "sent", "paid"})

#: Agreement statuses whose full value is committed.
LIVE_AGREEMENT_STATUSES: frozenset[str] = frozenset({"active", "completed"})

#: Payment application statuses finance has approved to pay.
APPROVED_PAY_APP_STATUSES: frozenset[str] = frozenset({"finance_approved", "paid"})


def _dec(value: object) -> Decimal:
    """Parse a money value, reading anything unparseable as zero."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip() or "0")
    except (InvalidOperation, ValueError, TypeError):
        return ZERO


def _ccy(value: object) -> str:
    return str(value or "").strip().upper()


def _add(bucket: dict[str, Decimal], currency: str, amount: Decimal) -> None:
    bucket[currency] = bucket.get(currency, ZERO) + amount


@dataclass(frozen=True)
class OrderRow:
    """A purchase order as the roll-up needs it."""

    id: uuid.UUID
    status: str
    currency: str
    net: Decimal


@dataclass(frozen=True)
class InvoiceRow:
    """A payable invoice as the roll-up needs it."""

    id: uuid.UUID
    status: str
    currency: str
    net: Decimal
    gross: Decimal
    po_id: uuid.UUID | None


@dataclass(frozen=True)
class PaymentRow:
    """A payment on a payable invoice."""

    invoice_id: uuid.UUID
    currency: str
    amount: Decimal
    is_refund: bool


@dataclass(frozen=True)
class AgreementRow:
    """A subcontract agreement."""

    id: uuid.UUID
    status: str
    currency: str
    value: Decimal


@dataclass(frozen=True)
class PayAppRow:
    """A subcontract payment application."""

    agreement_id: uuid.UUID
    status: str
    currency: str
    gross: Decimal
    cash: Decimal


@dataclass
class CostPosition:
    """Per-currency cost figures for one project or a set of projects."""

    committed: dict[str, Decimal] = field(default_factory=dict)
    invoiced: dict[str, Decimal] = field(default_factory=dict)
    paid: dict[str, Decimal] = field(default_factory=dict)
    paid_net: dict[str, Decimal] = field(default_factory=dict)

    def currencies(self) -> set[str]:
        """Every currency code carrying a figure (blank excluded)."""
        return {c for grp in (self.committed, self.invoiced, self.paid, self.paid_net) for c in grp if c}


def build_cost_position(
    orders: Iterable[OrderRow],
    invoices: Iterable[InvoiceRow],
    payments: Iterable[PaymentRow],
    agreements: Iterable[AgreementRow],
    pay_apps: Iterable[PayAppRow],
) -> CostPosition:
    """Fold the records into committed, invoiced and paid (see module docstring)."""
    out = CostPosition()
    invoices = list(invoices)
    committing = {o.id: o for o in orders if o.status in COMMITTING_ORDER_STATUSES}

    invoiced_on_order: dict[uuid.UUID, Decimal] = {}
    for inv in invoices:
        if inv.status not in INVOICED_STATUSES:
            continue
        _add(out.invoiced, inv.currency, inv.net)
        order = committing.get(inv.po_id) if inv.po_id is not None else None
        if order is not None and order.currency == inv.currency:
            invoiced_on_order[order.id] = invoiced_on_order.get(order.id, ZERO) + inv.net
        else:
            # No live order stands behind it (or it bills in another currency
            # than its order, where "the larger of the two" has no meaning).
            _add(out.committed, inv.currency, inv.net)
    for order in committing.values():
        _add(out.committed, order.currency, max(order.net, invoiced_on_order.get(order.id, ZERO)))

    agreements = {a.id: a for a in agreements}
    approved_on_agreement: dict[uuid.UUID, Decimal] = {}
    for app in pay_apps:
        if app.status not in APPROVED_PAY_APP_STATUSES:
            continue
        _add(out.invoiced, app.currency, app.gross)
        if app.status == "paid":
            _add(out.paid, app.currency, app.cash)
            _add(out.paid_net, app.currency, app.cash)
        agreement = agreements.get(app.agreement_id)
        if agreement is not None and agreement.currency == app.currency:
            approved_on_agreement[agreement.id] = approved_on_agreement.get(agreement.id, ZERO) + app.gross
        else:
            _add(out.committed, app.currency, app.gross)
    for agreement in agreements.values():
        approved = approved_on_agreement.get(agreement.id, ZERO)
        if agreement.status in LIVE_AGREEMENT_STATUSES:
            _add(out.committed, agreement.currency, max(agreement.value, approved))
        elif approved:
            _add(out.committed, agreement.currency, approved)

    net_share = {inv.id: (inv.net / inv.gross if inv.gross > 0 else Decimal("1")) for inv in invoices}
    for pay in payments:
        signed = -pay.amount if pay.is_refund else pay.amount
        _add(out.paid, pay.currency, signed)
        _add(out.paid_net, pay.currency, signed * net_share.get(pay.invoice_id, Decimal("1")))
    return out


def _scope(column: Any, project_id: uuid.UUID | None, project_ids: set[uuid.UUID] | None) -> Any:
    if project_id is not None:
        return column == project_id
    if project_ids is not None:
        return column.in_(project_ids)
    return None


async def load_cost_position(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    project_ids: set[uuid.UUID] | None = None,
) -> CostPosition:
    """Read the records for one project (or a set of them) and fold them.

    ``project_ids`` is the accessible-projects scope of a portfolio view; an
    empty set reads nothing. Procurement and subcontractors are optional
    modules: when one is not installed its figures are simply absent.
    """
    if project_ids is not None and not project_ids and project_id is None:
        return CostPosition()

    inv_stmt = select(
        Invoice.id,
        Invoice.status,
        Invoice.currency_code,
        Invoice.amount_subtotal,
        Invoice.amount_total,
        Invoice.purchase_order_id,
        Invoice.metadata_,
    ).where(Invoice.invoice_direction == "payable")
    pay_stmt = (
        select(Payment.invoice_id, Payment.currency_code, Payment.amount, Payment.is_refund)
        .join(Invoice, Payment.invoice_id == Invoice.id)
        .where(Invoice.invoice_direction == "payable")
    )
    inv_filter = _scope(Invoice.project_id, project_id, project_ids)
    if inv_filter is not None:
        inv_stmt = inv_stmt.where(inv_filter)
        pay_stmt = pay_stmt.where(inv_filter)

    invoices = [
        InvoiceRow(
            id=row[0],
            status=row[1] or "",
            currency=_ccy(row[2]),
            net=_dec(row[3]),
            gross=_dec(row[4]),
            po_id=invoice_po_link(row[5], row[6]),
        )
        for row in (await session.execute(inv_stmt)).all()
    ]
    payments = [
        PaymentRow(invoice_id=row[0], currency=_ccy(row[1]), amount=_dec(row[2]), is_refund=bool(row[3]))
        for row in (await session.execute(pay_stmt)).all()
    ]

    orders: list[OrderRow] = []
    try:
        from app.modules.procurement.models import PurchaseOrder
    except ImportError:
        PurchaseOrder = None  # noqa: N806
    if PurchaseOrder is not None:
        po_stmt = select(
            PurchaseOrder.id, PurchaseOrder.status, PurchaseOrder.currency_code, PurchaseOrder.amount_subtotal
        )
        po_filter = _scope(PurchaseOrder.project_id, project_id, project_ids)
        if po_filter is not None:
            po_stmt = po_stmt.where(po_filter)
        orders = [
            OrderRow(id=row[0], status=row[1] or "", currency=_ccy(row[2]), net=_dec(row[3]))
            for row in (await session.execute(po_stmt)).all()
        ]

    agreements: list[AgreementRow] = []
    pay_apps: list[PayAppRow] = []
    try:
        from app.modules.subcontractors.models import PaymentApplication, SubcontractAgreement
    except ImportError:
        SubcontractAgreement = None  # noqa: N806
    if SubcontractAgreement is not None:
        ag_stmt = select(
            SubcontractAgreement.id,
            SubcontractAgreement.status,
            SubcontractAgreement.currency,
            SubcontractAgreement.total_value,
        )
        app_stmt = select(
            PaymentApplication.agreement_id,
            PaymentApplication.status,
            PaymentApplication.currency,
            PaymentApplication.gross_amount,
            PaymentApplication.approved_gross_amount,
            PaymentApplication.net_amount,
            PaymentApplication.approved_net_amount,
        ).join(SubcontractAgreement, PaymentApplication.agreement_id == SubcontractAgreement.id)
        ag_filter = _scope(SubcontractAgreement.project_id, project_id, project_ids)
        if ag_filter is not None:
            ag_stmt = ag_stmt.where(ag_filter)
            app_stmt = app_stmt.where(ag_filter)
        agreements = [
            AgreementRow(id=row[0], status=row[1] or "", currency=_ccy(row[2]), value=_dec(row[3]))
            for row in (await session.execute(ag_stmt)).all()
        ]
        pay_apps = [
            PayAppRow(
                agreement_id=row[0],
                status=row[1] or "",
                currency=_ccy(row[2]),
                # What finance approved, once it has; the claim until then.
                gross=_dec(row[4] if row[4] is not None else row[3]),
                cash=_dec(row[6] if row[6] is not None else row[5]),
            )
            for row in (await session.execute(app_stmt)).all()
        ]

    return build_cost_position(orders, invoices, payments, agreements, pay_apps)
