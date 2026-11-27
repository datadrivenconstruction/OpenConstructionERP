# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What a supplier or subcontractor invoice bills against, and what is still open on it.

A commitment is a purchase order (procurement) or a subcontract agreement
(subcontractors). Both modules are optional, so everything here imports them
lazily and answers ``None`` when the module is absent.

The figures are net of VAT and in the commitment's own currency:

* ``original``: the order's net, or the agreement value before approved changes.
* ``approved_changes``: on an order, the approved change orders that name this
  order and only this order (a change order linked to several orders says
  nothing about how it splits, so it is counted as shared and left out); on an
  agreement, the approved subcontract changes, which approval already added to
  the agreement value.
* ``invoiced``: every other payable linked to it that the dashboard counts as
  invoiced, in the commitment's currency. Invoices in another currency are
  counted, not converted.
* ``remaining`` = ``original + approved_changes - invoiced``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.changeorders.allocations import allocated_to, allocations_of
from app.modules.finance.po_link import invoice_po_link

KIND_PURCHASE_ORDER = "purchase_order"
KIND_SUBCONTRACT = "subcontract"

#: Change-order statuses that have authorised the money (changeorders FSM).
APPROVED_CHANGE_ORDER_STATUSES = frozenset({"approved", "executed"})
#: Order states an invoice cannot be linked to.
UNLINKABLE_PO_STATUSES = frozenset({"draft", "cancelled"})
#: Agreement states an invoice cannot be linked to.
UNLINKABLE_AGREEMENT_STATUSES = frozenset({"draft"})

_ZERO = Decimal("0")


def _dec(value: object) -> Decimal:
    try:
        parsed = Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, ValueError, TypeError):
        return _ZERO
    return parsed if parsed.is_finite() else _ZERO


def _uuid(raw: object) -> uuid.UUID | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _currency(raw: object) -> str:
    return str(raw or "").strip().upper()


def invoice_agreement_link(subcontract_agreement_id: object, metadata: object) -> uuid.UUID | None:
    """Return the subcontract agreement an invoice bills against, or ``None``.

    The column wins. A payable raised from a payment application before the
    column existed carries the agreement as ``metadata_["agreement_id"]``.
    """
    linked = _uuid(subcontract_agreement_id)
    if linked is not None:
        return linked
    return _uuid(metadata.get("agreement_id")) if isinstance(metadata, dict) else None


@dataclass
class Commitment:
    """One purchase order or subcontract agreement, as the invoice checks read it."""

    kind: str
    id: uuid.UUID
    ref: str
    project_id: uuid.UUID
    status: str
    vendor_contact_id: str | None
    currency_code: str
    original: Decimal
    approved_changes: Decimal = _ZERO
    retention_percent: Decimal = _ZERO
    retain_on_receipt: bool = False
    tolerance_pct: str | None = None
    tolerance_abs: str | None = None
    shared_change_orders: int = 0
    invoiced: Decimal = _ZERO
    retained: Decimal = _ZERO
    paid: Decimal = _ZERO
    invoices_in_other_currency: int = 0
    invoice_ids: list[uuid.UUID] = field(default_factory=list)
    #: Share of each counted invoice already paid, 0..1, for the line statement.
    paid_share: dict[uuid.UUID, Decimal] = field(default_factory=dict)

    @property
    def revised(self) -> Decimal:
        return self.original + self.approved_changes

    @property
    def remaining(self) -> Decimal:
        return self.revised - self.invoiced

    def tolerance(self) -> Decimal:
        """The overrun an invoice may carry before it is refused, from the order's own tolerance."""
        if self.kind != KIND_PURCHASE_ORDER:
            return Decimal("0.01")
        from app.modules.procurement.validators import _allowance

        return _allowance(
            {"invoice_tolerance_pct": self.tolerance_pct, "invoice_tolerance_abs": self.tolerance_abs},
            self.revised,
        )

    def pay_summary(self, current_net: object, current_retention: object) -> dict[str, str]:
        """The certificate summary with this invoice added, net of VAT, in the commitment's currency.

        A, completed to date, is everything invoiced before plus this invoice.
        B, retention, is A times the agreed share; without an agreed share it
        is what the invoices actually hold. C, previously certified, is what
        earlier invoices billed less what they held. Current due is A - B - C.
        """
        net = _dec(current_net)
        completed = self.invoiced + net
        if self.retention_percent > 0 and not self.retain_on_receipt:
            retention = (completed * self.retention_percent / Decimal(100)).quantize(Decimal("0.01"))
        else:
            retention = self.retained + _dec(current_retention)
        previous = self.invoiced - self.retained
        earned = completed - retention
        return {
            "completed_to_date": str(completed),
            "retention": str(retention),
            "earned_less_retention": str(earned),
            "previously_certified": str(previous),
            "current_due": str(earned - previous),
            "balance_to_finish": str(self.revised - completed),
        }

    def as_dict(self) -> dict[str, Any]:
        """The API shape (:class:`CommitmentResponse`)."""
        return {
            "kind": self.kind,
            "id": self.id,
            "ref": self.ref,
            "status": self.status,
            "currency_code": self.currency_code,
            "original": str(self.original),
            "approved_changes": str(self.approved_changes),
            "revised": str(self.revised),
            "invoiced": str(self.invoiced),
            "remaining": str(self.remaining),
            "paid": str(self.paid),
            "retention_percent": str(self.retention_percent),
            "invoices_in_other_currency": self.invoices_in_other_currency,
            "shared_change_orders": self.shared_change_orders,
        }


async def _purchase_order(session: AsyncSession, po_id: uuid.UUID) -> Commitment | None:
    try:
        from app.modules.procurement.models import PurchaseOrder
    except ImportError:  # pragma: no cover - procurement is optional for finance
        return None
    po = await session.get(PurchaseOrder, po_id)
    if po is None:
        return None
    commitment = Commitment(
        kind=KIND_PURCHASE_ORDER,
        id=po.id,
        ref=po.po_number or "",
        project_id=po.project_id,
        status=po.status or "",
        vendor_contact_id=str(po.vendor_contact_id) if po.vendor_contact_id else None,
        currency_code=_currency(po.currency_code),
        original=_dec(po.amount_subtotal),
        retention_percent=_dec(po.retention_percent),
        retain_on_receipt=bool(po.retain_on_receipt),
        tolerance_pct=po.invoice_tolerance_pct,
        tolerance_abs=po.invoice_tolerance_abs,
    )
    try:
        from app.modules.changeorders.models import ChangeOrder
    except ImportError:  # pragma: no cover - change orders are optional
        return commitment
    rows = (
        (
            await session.execute(
                select(ChangeOrder).where(
                    ChangeOrder.project_id == po.project_id,
                    ChangeOrder.status.in_(APPROVED_CHANGE_ORDER_STATUSES),
                )
            )
        )
        .scalars()
        .all()
    )
    for order in rows:
        currency = _currency(order.currency)
        if currency and commitment.currency_code and currency != commitment.currency_code:
            continue
        raw = getattr(order, "commitment_allocations", None)
        share = allocated_to(raw, KIND_PURCHASE_ORDER, po.id)
        if share is not None:
            commitment.approved_changes += share
            continue
        linked = {_uuid(x) for x in (order.linked_po_ids or [])} - {None}
        if po.id not in linked or allocations_of(raw):
            continue
        if len(linked) > 1:
            commitment.shared_change_orders += 1
            continue
        amount = order.approved_amount if order.approved_amount is not None else order.cost_impact
        commitment.approved_changes += _dec(amount)
    return commitment


async def _allocated_changes(
    session: AsyncSession, project_id: uuid.UUID, agreement_id: uuid.UUID, currency: str
) -> Decimal:
    """What approved change orders allocate to a subcontract agreement."""
    try:
        from app.modules.changeorders.models import ChangeOrder
    except ImportError:  # pragma: no cover - change orders are optional
        return _ZERO
    rows = (
        await session.execute(
            select(ChangeOrder.currency, ChangeOrder.commitment_allocations).where(
                ChangeOrder.project_id == project_id,
                ChangeOrder.status.in_(APPROVED_CHANGE_ORDER_STATUSES),
                ChangeOrder.commitment_allocations.is_not(None),
            )
        )
    ).all()
    total = _ZERO
    for order_currency, raw in rows:
        if currency and _currency(order_currency) and _currency(order_currency) != currency:
            continue
        total += allocated_to(raw, KIND_SUBCONTRACT, agreement_id) or _ZERO
    return total


async def _agreement(session: AsyncSession, agreement_id: uuid.UUID) -> Commitment | None:
    try:
        from app.modules.subcontractors.models import SubcontractAgreement, SubcontractChange, Subcontractor
    except ImportError:  # pragma: no cover - subcontractors is optional for finance
        return None
    agreement = await session.get(SubcontractAgreement, agreement_id)
    if agreement is None:
        return None
    sub = await session.get(Subcontractor, agreement.subcontractor_id)
    applied = (
        (
            await session.execute(
                select(SubcontractChange.applied_amount).where(
                    SubcontractChange.agreement_id == agreement.id,
                    SubcontractChange.status == "approved",
                    SubcontractChange.applied_amount.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    changes = sum((_dec(a) for a in applied), _ZERO)
    allocated = await _allocated_changes(session, agreement.project_id, agreement.id, _currency(agreement.currency))
    return Commitment(
        kind=KIND_SUBCONTRACT,
        id=agreement.id,
        ref=agreement.title or "",
        project_id=agreement.project_id,
        status=agreement.status or "",
        vendor_contact_id=str(sub.contact_id) if sub is not None and sub.contact_id else None,
        currency_code=_currency(agreement.currency),
        original=_dec(agreement.total_value) - changes,
        approved_changes=changes + allocated,
        retention_percent=_dec(agreement.retention_percent),
    )


async def _project_payables(session: AsyncSession, project_id: uuid.UUID) -> Sequence[Any]:
    """Every supplier invoice of the project, in one query."""
    from app.modules.finance.models import Invoice

    return (
        (
            await session.execute(
                select(Invoice).where(Invoice.project_id == project_id, Invoice.invoice_direction == "payable")
            )
        )
        .scalars()
        .all()
    )


def _links_to(invoice: Any, commitment: Commitment) -> bool:
    if commitment.kind == KIND_PURCHASE_ORDER:
        return invoice_po_link(invoice.purchase_order_id, invoice.metadata_) == commitment.id
    return invoice_agreement_link(invoice.subcontract_agreement_id, invoice.metadata_) == commitment.id


async def load_commitment(
    session: AsyncSession,
    *,
    purchase_order_id: uuid.UUID | None = None,
    subcontract_agreement_id: uuid.UUID | None = None,
    exclude_invoice_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    invoices: Sequence[Any] | None = None,
) -> Commitment | None:
    """The commitment an invoice names, with what the other invoices on it already billed and were paid.

    ``exclude_invoice_id`` leaves the invoice being checked out of the
    figures, so re-checking a saved invoice does not count it twice. Given
    ``project_id``, a commitment of another project reads as absent.
    ``invoices`` are the project's payables when the caller already loaded them.
    """
    if purchase_order_id is not None:
        commitment = await _purchase_order(session, purchase_order_id)
    elif subcontract_agreement_id is not None:
        commitment = await _agreement(session, subcontract_agreement_id)
    else:
        return None
    if commitment is None or (project_id is not None and commitment.project_id != project_id):
        return None

    from app.modules.finance.cost_position import INVOICED_STATUSES

    rows = invoices if invoices is not None else await _project_payables(session, commitment.project_id)
    for inv in rows:
        if inv.id == exclude_invoice_id or inv.status not in INVOICED_STATUSES or not _links_to(inv, commitment):
            continue
        if commitment.currency_code and _currency(inv.currency_code) != commitment.currency_code:
            commitment.invoices_in_other_currency += 1
            continue
        commitment.invoiced += _dec(inv.amount_subtotal)
        commitment.retained += _dec(inv.retention_amount)
        commitment.invoice_ids.append(inv.id)
        paid_here = _ZERO
        for pay in inv.payments or []:
            amount = _dec(pay.amount)
            paid_here += -amount if pay.is_refund else amount
        commitment.paid += paid_here
        gross = _dec(inv.amount_total)
        commitment.paid_share[inv.id] = min(max(paid_here / gross, _ZERO), Decimal(1)) if gross > 0 else _ZERO
    return commitment


async def po_line_owners(session: AsyncSession, line_ids: set[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    """The purchase order each of ``line_ids`` belongs to; unknown ids are absent."""
    if not line_ids:
        return {}
    try:
        from app.modules.procurement.models import PurchaseOrderItem
    except ImportError:  # pragma: no cover
        return {}
    rows = (
        await session.execute(
            select(PurchaseOrderItem.id, PurchaseOrderItem.po_id).where(PurchaseOrderItem.id.in_(line_ids))
        )
    ).all()
    return {line_id: po_id for line_id, po_id in rows}


async def po_line_statement(
    session: AsyncSession, commitment: Commitment, current_lines: list[dict[str, Any]]
) -> list[dict[str, str | None]]:
    """The order's lines as a schedule of values, with this invoice's lines laid over them.

    Per line: scheduled value, invoiced and paid on earlier counted invoices,
    this invoice, total, percent complete and balance to complete, all net in
    the order's currency. ``current_lines`` are ``{"po_line_id", "amount"}``.
    """
    if commitment.kind != KIND_PURCHASE_ORDER:
        return []
    try:
        from app.modules.procurement.models import PurchaseOrderItem
    except ImportError:  # pragma: no cover
        return []
    from app.modules.finance.models import InvoiceLineItem

    items = (
        (
            await session.execute(
                select(PurchaseOrderItem)
                .where(PurchaseOrderItem.po_id == commitment.id)
                .order_by(PurchaseOrderItem.sort_order)
            )
        )
        .scalars()
        .all()
    )
    if not items:
        return []
    previous: dict[uuid.UUID, Decimal] = {}
    paid: dict[uuid.UUID, Decimal] = {}
    if commitment.invoice_ids:
        rows = (
            await session.execute(
                select(InvoiceLineItem.po_line_id, InvoiceLineItem.amount, InvoiceLineItem.invoice_id).where(
                    InvoiceLineItem.invoice_id.in_(commitment.invoice_ids),
                    InvoiceLineItem.po_line_id.is_not(None),
                )
            )
        ).all()
        for line_id, amount, invoice_id in rows:
            value = _dec(amount)
            previous[line_id] = previous.get(line_id, _ZERO) + value
            share = commitment.paid_share.get(invoice_id, _ZERO)
            paid[line_id] = paid.get(line_id, _ZERO) + (value * share).quantize(Decimal("0.01"))
    current: dict[uuid.UUID, Decimal] = {}
    for line in current_lines:
        line_id = _uuid(line.get("po_line_id"))
        if line_id is not None:
            current[line_id] = current.get(line_id, _ZERO) + _dec(line.get("amount"))
    out: list[dict[str, str | None]] = []
    for item in items:
        scheduled = _dec(item.amount)
        before = previous.get(item.id, _ZERO)
        now = current.get(item.id, _ZERO)
        total = before + now
        out.append(
            {
                "po_line_id": str(item.id),
                "description": item.description,
                "scheduled": str(scheduled),
                "previously_invoiced": str(before),
                "previously_paid": str(paid.get(item.id, _ZERO)),
                "this_invoice": str(now),
                "total": str(total),
                "percent_complete": (
                    str((total * 100 / scheduled).quantize(Decimal("0.1"))) if scheduled > 0 else None
                ),
                "balance_to_complete": str(scheduled - total),
            }
        )
    return out


async def list_commitments(session: AsyncSession, project_id: uuid.UUID, contact_id: str | None) -> list[Commitment]:
    """The orders and agreements of this project an invoice from ``contact_id`` may be linked to.

    Same rule the link check applies: not a draft (or cancelled order), and
    placed with this supplier when both name one. Agreements come only when
    the subcontractors module is installed, so a market without it sees orders
    alone.
    """
    found: list[Commitment] = []
    # One read of the project's payables serves every commitment listed.
    invoices = await _project_payables(session, project_id)
    try:
        from app.modules.procurement.models import PurchaseOrder
    except ImportError:  # pragma: no cover
        PurchaseOrder = None  # noqa: N806
    if PurchaseOrder is not None:
        stmt = select(PurchaseOrder.id).where(
            PurchaseOrder.project_id == project_id,
            PurchaseOrder.status.notin_(UNLINKABLE_PO_STATUSES),
        )
        if contact_id:
            stmt = stmt.where(PurchaseOrder.vendor_contact_id == contact_id)
        for po_id in (await session.execute(stmt.order_by(PurchaseOrder.po_number))).scalars().all():
            loaded = await load_commitment(session, purchase_order_id=po_id, invoices=invoices)
            if loaded is not None:
                found.append(loaded)
    try:
        from app.modules.subcontractors.models import SubcontractAgreement, Subcontractor
    except ImportError:  # pragma: no cover
        return found
    stmt = (
        select(SubcontractAgreement.id)
        .join(Subcontractor, Subcontractor.id == SubcontractAgreement.subcontractor_id)
        .where(
            SubcontractAgreement.project_id == project_id,
            SubcontractAgreement.status.notin_(UNLINKABLE_AGREEMENT_STATUSES),
        )
    )
    if contact_id:
        stmt = stmt.where(Subcontractor.contact_id == _uuid(contact_id))
    for agreement_id in (await session.execute(stmt.order_by(SubcontractAgreement.title))).scalars().all():
        loaded = await load_commitment(session, subcontract_agreement_id=agreement_id, invoices=invoices)
        if loaded is not None:
            found.append(loaded)
    return found
