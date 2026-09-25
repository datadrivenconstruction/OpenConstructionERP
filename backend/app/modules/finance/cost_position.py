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
Committed and actual are two halves of one outturn: ``actual`` is what has
been incurred, ``committed`` is what is promised and not yet incurred, and
``committed + actual`` is what the project will finish at. Each is computed
per source (an order, a subcontract, a supplier invoice with neither behind
it), and ``sources`` carries them one by one so the budget rows can be kept
to exactly the same figures (``FinanceService.sync_project_budget``).

``actual`` (net of VAT)
    An order: the larger of what its confirmed goods receipts are worth and
    what has been settled on its invoices. A subcontract: what has been
    settled on the invoices billing it. Any other supplier invoice: what has
    been settled on it. "Settled" is the invoice's net once it is paid, and
    before that the payments on it (retention withheld included, since that
    money is owed and only paid later) with the VAT share taken out.
``committed`` (net of VAT, the open part)
    Each source's full commitment less its actual, never below zero. The full
    commitment of an order is the larger of its net value and the invoices
    raised against it, never their sum. That of a live subcontract (an
    agreement, or a contract with a subcontractor that no agreement already
    carries) is the larger of its value and what has been approved against
    it; a terminated one keeps only what was approved. A supplier invoice with
    no order or subcontract behind it is committed at its own net on the day
    it is invoiced: money spent without an order.
``over_commitment`` (net of VAT)
    What a source has incurred beyond its full commitment: received beyond an
    order that nobody invoiced, or settled beyond a subcontract's value. Its
    committed stays at zero rather than going negative, and the excess is
    reported here instead of vanishing into that zero.
``invoiced`` (net of VAT)
    Supplier invoices from ``pending`` on, at their subtotal, and payment
    applications finance has approved, at the approved gross. Retention is
    part of the gross: it is owed, only later.
``paid`` (cash, VAT included)
    Payments on supplier invoices, refunds netted out, and the cash paid on
    payment applications (the approved net, retention withheld). An invoice
    marked paid with no payment recorded counts at its full total.
``paid_net`` (net of VAT)
    The same payments with the VAT share taken out, pro rata to the invoice's
    subtotal over its total, so it compares with a net budget.

Receivable (client) invoices are outside all of them; this is the cost side.
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

#: The budget category subcontract figures are booked under.
SUBCONTRACT_CATEGORY = "subcontractor"


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
    #: The subcontract this invoice bills (a subcontract agreement or a
    #: contract with a subcontractor), read from its metadata.
    commitment_id: uuid.UUID | None = None
    #: The payment application this invoice was raised for, if any.
    pay_app_id: uuid.UUID | None = None


@dataclass(frozen=True)
class PaymentRow:
    """A payment on a payable invoice."""

    invoice_id: uuid.UUID
    currency: str
    amount: Decimal
    is_refund: bool
    #: Retention held back from this payment: owed, so settled for the cost.
    withheld: Decimal = ZERO


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
    id: uuid.UUID | None = None


@dataclass(frozen=True)
class SourceFigure:
    """One source's committed (open) and actual, and where in the budget it belongs.

    ``kind`` is ``po``, ``subcontract``, ``invoice`` or ``pay_app``; ``ref`` is
    that record's id. A supplier invoice split over several lines yields one
    figure per line, all with the same kind and ref.
    """

    kind: str
    ref: uuid.UUID
    currency: str
    wbs_id: str | None
    category: str | None
    committed: Decimal
    actual: Decimal

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.ref}"


@dataclass
class CostPosition:
    """Per-currency cost figures for one project or a set of projects."""

    committed: dict[str, Decimal] = field(default_factory=dict)
    actual: dict[str, Decimal] = field(default_factory=dict)
    invoiced: dict[str, Decimal] = field(default_factory=dict)
    paid: dict[str, Decimal] = field(default_factory=dict)
    paid_net: dict[str, Decimal] = field(default_factory=dict)
    #: Incurred beyond the full commitment, per source, summed (never hidden by the zero floor).
    over_commitment: dict[str, Decimal] = field(default_factory=dict)
    #: The committed part that is owed to subcontractors (see ``subcontract_open_commitment``).
    subcontract_open: dict[str, Decimal] = field(default_factory=dict)
    sources: list[SourceFigure] = field(default_factory=list)

    def currencies(self) -> set[str]:
        """Every currency code carrying a figure (blank excluded)."""
        return {c for grp in (self.committed, self.actual, self.invoiced, self.paid, self.paid_net) for c in grp if c}


CENT = Decimal("0.01")


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT)


def build_cost_position(
    orders: Iterable[OrderRow],
    invoices: Iterable[InvoiceRow],
    payments: Iterable[PaymentRow],
    agreements: Iterable[AgreementRow],
    pay_apps: Iterable[PayAppRow],
    *,
    received_by_po: dict[uuid.UUID, Decimal] | None = None,
    order_wbs: dict[uuid.UUID, str] | None = None,
    invoice_lines: dict[uuid.UUID, list[tuple[str | None, str | None, Decimal]]] | None = None,
    contract_to_agreement: dict[uuid.UUID, uuid.UUID] | None = None,
) -> CostPosition:
    """Fold the records into committed, actual, invoiced and paid (see module docstring).

    ``received_by_po`` is the confirmed goods receipt value per order, net.
    ``order_wbs`` is the WBS an order's first line is booked to, and
    ``invoice_lines`` the ``(wbs_id, cost_category, amount)`` lines of each
    supplier invoice: both only say which budget line a figure belongs on.
    ``contract_to_agreement`` maps a contract that a subcontract agreement
    carries to that agreement; such a contract is not a second commitment, and
    an invoice naming it bills the agreement.
    """
    out = CostPosition()
    invoices = list(invoices)
    payments = list(payments)
    received_by_po = received_by_po or {}
    order_wbs = order_wbs or {}
    invoice_lines = invoice_lines or {}
    contract_to_agreement = contract_to_agreement or {}
    committing = {o.id: o for o in orders if o.status in COMMITTING_ORDER_STATUSES}
    agreements = {a.id: a for a in agreements if a.id not in contract_to_agreement}

    # Settled per invoice, gross: payments less refunds, retention withheld
    # included (it is owed, only later).
    settled_gross: dict[uuid.UUID, Decimal] = {}
    for pay in payments:
        signed = -(pay.amount + pay.withheld) if pay.is_refund else pay.amount + pay.withheld
        settled_gross[pay.invoice_id] = settled_gross.get(pay.invoice_id, ZERO) + signed

    def settled_net(inv: InvoiceRow) -> Decimal:
        if inv.status == "paid":
            return inv.net
        gross_settled = settled_gross.get(inv.id, ZERO)
        if gross_settled <= 0:
            return ZERO
        share = gross_settled * inv.net / inv.gross if inv.gross > 0 else gross_settled
        return _cents(min(share, inv.net))

    def emit(
        kind: str, ref: uuid.UUID, currency: str, wbs: str | None, cat: str | None, full: Decimal, act: Decimal
    ) -> None:
        figure = SourceFigure(kind, ref, currency, wbs, cat, _cents(max(full - act, ZERO)), _cents(act))
        if figure.committed == 0 and figure.actual == 0:
            return
        if act > full:
            _add(out.over_commitment, currency, _cents(act - full))
        out.sources.append(figure)
        _add(out.committed, currency, figure.committed)
        _add(out.actual, currency, figure.actual)
        if kind == "subcontract":
            _add(out.subcontract_open, currency, figure.committed)

    invoiced_on_order: dict[uuid.UUID, Decimal] = {}
    settled_on_order: dict[uuid.UUID, Decimal] = {}
    approved_on_agreement: dict[uuid.UUID, Decimal] = {}
    settled_on_agreement: dict[uuid.UUID, Decimal] = {}
    for inv in invoices:
        if inv.status not in INVOICED_STATUSES:
            continue
        _add(out.invoiced, inv.currency, inv.net)
        order = committing.get(inv.po_id) if inv.po_id is not None else None
        agreement_id = (
            contract_to_agreement.get(inv.commitment_id, inv.commitment_id) if inv.commitment_id is not None else None
        )
        agreement = agreements.get(agreement_id) if agreement_id is not None else None
        if order is not None and order.currency == inv.currency:
            invoiced_on_order[order.id] = invoiced_on_order.get(order.id, ZERO) + inv.net
            settled_on_order[order.id] = settled_on_order.get(order.id, ZERO) + settled_net(inv)
        elif agreement is not None and agreement.currency == inv.currency:
            # A subcontract's payable invoice draws down its agreement, the
            # same way a payment application does.
            approved_on_agreement[agreement.id] = approved_on_agreement.get(agreement.id, ZERO) + inv.net
            settled_on_agreement[agreement.id] = settled_on_agreement.get(agreement.id, ZERO) + settled_net(inv)
        else:
            # No live order or subcontract stands behind it (or it bills in
            # another currency than its order, where "the larger of the two"
            # has no meaning): committed at its own net, line by line.
            _emit_invoice(emit, inv, settled_net(inv), invoice_lines.get(inv.id) or [])
    for order in committing.values():
        full = max(order.net, invoiced_on_order.get(order.id, ZERO))
        incurred = max(received_by_po.get(order.id, ZERO), settled_on_order.get(order.id, ZERO))
        emit("po", order.id, order.currency, order_wbs.get(order.id), None, full, incurred)

    # A payment application finance has turned into a payable invoice is that
    # invoice from then on; counting both would bill the work twice.
    invoiced_apps = {inv.pay_app_id for inv in invoices if inv.pay_app_id is not None}
    for app in pay_apps:
        if app.status not in APPROVED_PAY_APP_STATUSES or (app.id is not None and app.id in invoiced_apps):
            continue
        _add(out.invoiced, app.currency, app.gross)
        paid = app.status == "paid"
        if paid:
            _add(out.paid, app.currency, app.cash)
            _add(out.paid_net, app.currency, app.cash)
        agreement = agreements.get(app.agreement_id)
        if agreement is not None and agreement.currency == app.currency:
            approved_on_agreement[agreement.id] = approved_on_agreement.get(agreement.id, ZERO) + app.gross
            if paid:
                settled_on_agreement[agreement.id] = settled_on_agreement.get(agreement.id, ZERO) + app.gross
        elif app.id is not None:
            emit("pay_app", app.id, app.currency, None, SUBCONTRACT_CATEGORY, app.gross, app.gross if paid else ZERO)
    for agreement in agreements.values():
        approved = approved_on_agreement.get(agreement.id, ZERO)
        full = max(agreement.value, approved) if agreement.status in LIVE_AGREEMENT_STATUSES else approved
        emit(
            "subcontract",
            agreement.id,
            agreement.currency,
            None,
            SUBCONTRACT_CATEGORY,
            full,
            settled_on_agreement.get(agreement.id, ZERO),
        )

    net_share = {inv.id: (inv.net / inv.gross if inv.gross > 0 else Decimal("1")) for inv in invoices}
    with_payments: set[uuid.UUID] = set()
    for pay in payments:
        with_payments.add(pay.invoice_id)
        signed = -pay.amount if pay.is_refund else pay.amount
        _add(out.paid, pay.currency, signed)
        _add(out.paid_net, pay.currency, signed * net_share.get(pay.invoice_id, Decimal("1")))
    # An invoice marked paid with no payment recorded against it. Until the
    # invoice screen's "Mark Paid" recorded one, every invoice paid from it
    # ended up this way; its money was still paid, in full.
    for inv in invoices:
        if inv.status == "paid" and inv.id not in with_payments:
            _add(out.paid, inv.currency, inv.gross)
            _add(out.paid_net, inv.currency, inv.net)
    return out


def _emit_invoice(
    emit: Any,
    inv: InvoiceRow,
    settled: Decimal,
    lines: list[tuple[str | None, str | None, Decimal]],
) -> None:
    """Split a standalone supplier invoice over its lines, pro rata to their amounts."""
    total = sum((amount for _, _, amount in lines), ZERO)
    if not lines or total <= 0:
        emit("invoice", inv.id, inv.currency, None, None, inv.net, settled)
        return
    full_left, act_left = inv.net, settled
    for index, (wbs, cat, amount) in enumerate(lines):
        if index == len(lines) - 1:
            full, act = full_left, act_left
        else:
            full = _cents(inv.net * amount / total)
            act = _cents(settled * amount / total)
            full_left -= full
            act_left -= act
        emit("invoice", inv.id, inv.currency, wbs, cat, full, act)


#: Invoice metadata keys naming the subcontract an invoice bills, and the
#: payment application it was raised for.
_COMMITMENT_KEYS: tuple[str, ...] = ("agreement_id", "subcontract_agreement_id", "contract_id")
_PAY_APP_KEYS: tuple[str, ...] = ("pay_app_id", "payment_application_id")


def _meta_uuid(metadata: object, keys: tuple[str, ...]) -> uuid.UUID | None:
    if not isinstance(metadata, dict):
        return None
    for key in keys:
        raw = metadata.get(key)
        if raw:
            try:
                return uuid.UUID(str(raw))
            except ValueError:
                continue
    return None


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
        select(Payment.invoice_id, Payment.currency_code, Payment.amount, Payment.is_refund, Payment.withholding_amount)
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
            commitment_id=_meta_uuid(row[6], _COMMITMENT_KEYS),
            pay_app_id=_meta_uuid(row[6], _PAY_APP_KEYS),
        )
        for row in (await session.execute(inv_stmt)).all()
    ]
    payments = [
        PaymentRow(
            invoice_id=row[0],
            currency=_ccy(row[1]),
            amount=_dec(row[2]),
            is_refund=bool(row[3]),
            withheld=_dec(row[4]),
        )
        for row in (await session.execute(pay_stmt)).all()
    ]
    invoice_lines = await _invoice_lines(session, [inv.id for inv in invoices])

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
    order_ids = [o.id for o in orders]
    received = await received_net_by_po(session, order_ids) if order_ids else {}
    order_wbs = await _order_wbs(session, order_ids) if order_ids else {}

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
            PaymentApplication.id,
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
                id=row[0],
                agreement_id=row[1],
                status=row[2] or "",
                currency=_ccy(row[3]),
                # What finance approved, once it has; the claim until then.
                gross=_dec(row[5] if row[5] is not None else row[4]),
                cash=_dec(row[7] if row[7] is not None else row[6]),
            )
            for row in (await session.execute(app_stmt)).all()
        ]

    contract_to_agreement: dict[uuid.UUID, uuid.UUID] = {}
    # ``contract_id`` links an agreement to the contract written for the same
    # subcontract; on an install without it no pair can be told apart.
    link_col = getattr(SubcontractAgreement, "contract_id", None) if SubcontractAgreement is not None else None
    if link_col is not None:
        link_stmt = select(link_col, SubcontractAgreement.id).where(link_col.isnot(None))
        if ag_filter is not None:
            link_stmt = link_stmt.where(ag_filter)
        contract_to_agreement = {row[0]: row[1] for row in (await session.execute(link_stmt)).all()}

    agreements.extend(await _subcontract_contracts(session, project_id, project_ids))
    return build_cost_position(
        orders,
        invoices,
        payments,
        agreements,
        pay_apps,
        received_by_po=received,
        order_wbs=order_wbs,
        invoice_lines=invoice_lines,
        contract_to_agreement=contract_to_agreement,
    )


async def _invoice_lines(
    session: AsyncSession, invoice_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[str | None, str | None, Decimal]]]:
    """``(wbs_id, cost_category, amount)`` of each invoice's lines, in their order."""
    if not invoice_ids:
        return {}
    from app.modules.finance.models import InvoiceLineItem

    out: dict[uuid.UUID, list[tuple[str | None, str | None, Decimal]]] = {}
    for start in range(0, len(invoice_ids), 500):
        stmt = (
            select(
                InvoiceLineItem.invoice_id,
                InvoiceLineItem.wbs_id,
                InvoiceLineItem.cost_category,
                InvoiceLineItem.amount,
            )
            .where(InvoiceLineItem.invoice_id.in_(invoice_ids[start : start + 500]))
            .order_by(InvoiceLineItem.sort_order)
        )
        for inv_id, wbs, cat, amount in (await session.execute(stmt)).all():
            out.setdefault(inv_id, []).append(((wbs or "").strip() or None, (cat or "").strip() or None, _dec(amount)))
    return out


async def _order_wbs(session: AsyncSession, order_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """The WBS each order's first booked line points at (the same rule the order events use)."""
    from app.modules.procurement.models import PurchaseOrderItem

    out: dict[uuid.UUID, str] = {}
    for start in range(0, len(order_ids), 500):
        stmt = (
            select(PurchaseOrderItem.po_id, PurchaseOrderItem.wbs_id)
            .where(PurchaseOrderItem.po_id.in_(order_ids[start : start + 500]), PurchaseOrderItem.wbs_id.isnot(None))
            .order_by(PurchaseOrderItem.sort_order)
        )
        for po_id, wbs in (await session.execute(stmt)).all():
            if po_id not in out and (wbs or "").strip():
                out[po_id] = wbs.strip()
    return out


#: Contract statuses whose value is committed. A suspended contract is still
#: owed; a terminated one keeps only what was invoiced against it.
_LIVE_CONTRACT_STATUSES: frozenset[str] = frozenset({"active", "suspended", "completed"})


async def _subcontract_contracts(
    session: AsyncSession, project_id: uuid.UUID | None, project_ids: set[uuid.UUID] | None
) -> list[AgreementRow]:
    """Contracts signed with a subcontractor, read as commitments like agreements."""
    try:
        from app.modules.contracts.models import Contract
    except ImportError:
        return []
    stmt = select(Contract.id, Contract.status, Contract.currency, Contract.total_value).where(
        Contract.counterparty_type == "subcontractor"
    )
    scope = _scope(Contract.project_id, project_id, project_ids)
    if scope is not None:
        stmt = stmt.where(scope)
    return [
        AgreementRow(
            id=row[0],
            status="active" if (row[1] or "") in _LIVE_CONTRACT_STATUSES else (row[1] or ""),
            currency=_ccy(row[2]),
            value=_dec(row[3]),
        )
        for row in (await session.execute(stmt)).all()
    ]


async def subcontract_open_commitment(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Decimal]:
    """What the project still owes its subcontractors, per currency, net.

    For each signed subcontract (an active or completed subcontract agreement,
    or a live contract with a subcontractor that no agreement carries through
    ``contract_id``): the larger of its value and what has been approved
    against it, less what has been settled on the invoices billing it, never
    below zero. It is the open part of the subcontract, so it plus the settled
    part (the actual) is the subcontract's outturn. The invoices billing a
    subcontract are the payable invoices naming it in their metadata
    (``agreement_id`` or ``contract_id``; a contract an agreement carries
    resolves to that agreement).

    This is the one reader of subcontract commitment. Callers must not write
    it into ``ProjectBudget``: ``FinanceService.sync_project_budget`` keeps the
    budget rows to the same figures.
    """
    position = await load_cost_position(session, project_id=project_id)
    return dict(position.subcontract_open)


async def received_net_by_po(session: AsyncSession, order_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    """Confirmed goods receipts per purchase order, valued at the order's unit rates (net).

    The same value ``procurement.gr.confirmed`` carries when it moves a receipt
    into actual. Empty when procurement is not installed.
    """
    try:
        from app.modules.procurement.models import GoodsReceipt, GoodsReceiptItem, PurchaseOrderItem
    except ImportError:
        return {}
    out: dict[uuid.UUID, Decimal] = {}
    for start in range(0, len(order_ids), 500):
        stmt = (
            select(GoodsReceipt.po_id, GoodsReceiptItem.quantity_received, PurchaseOrderItem.unit_rate)
            .join(GoodsReceiptItem, GoodsReceiptItem.receipt_id == GoodsReceipt.id)
            .join(PurchaseOrderItem, PurchaseOrderItem.id == GoodsReceiptItem.po_item_id)
            .where(GoodsReceipt.po_id.in_(order_ids[start : start + 500]), GoodsReceipt.status == "confirmed")
        )
        for po_id, qty, rate in (await session.execute(stmt)).all():
            out[po_id] = out.get(po_id, ZERO) + _dec(qty) * _dec(rate)
    return out
