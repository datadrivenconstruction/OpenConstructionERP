# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Where subcontract money meets the project budget and the payables ledger.

A subcontract is spend we have agreed to, so signing it commits the budget.
Each payment application is a bill from the subcontractor, so approving one
raises a payable, and paying it moves the gross from committed to actual. The
retention on it is held from what we pay, so the payment holds it back and the
payables retention ledger shows it held.

Everything here writes through the caller's session. Nothing commits, so the
subcontract, its invoice and the budget move in one transaction or not at all.

Commitments are tracked on the absorbing ``ProjectBudget`` row in its metadata,
the same way purchase orders are (``committed_from_po:<id>`` in
``finance.events``):

* ``committed_from_subcontract:<source>`` holds what that subcontract still
  has committed. ``<source>`` is ``contract:<id>`` for a subcontract written in
  the contracts module and ``agreement:<id>`` for an agreement written here.
* ``drawn_by_invoice:<id>`` records what one paid invoice took off it.

Drawing down is capped at what the subcontract itself still has committed, so a
subcontract that was never signed cannot eat a purchase order's commitment,
and the per-invoice marker makes a second delivery of the same payment a no-op.
Actual is left to finance, which recomputes it from paid invoices; posting it
here as well would count the same money twice.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.models import Invoice, InvoiceLineItem, ProjectBudget

logger = logging.getLogger(__name__)

COMMITTED_PREFIX = "committed_from_subcontract:"
DRAWN_PREFIX = "drawn_by_invoice:"
#: ``Invoice.metadata_["source"]`` for a payable raised from a pay application.
PAY_APP_SOURCE = "subcontract_payment_application"
_ZERO = Decimal("0")


def _dec(value: object) -> Decimal:
    try:
        parsed = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError, TypeError):
        return _ZERO
    return parsed if parsed.is_finite() else _ZERO


def _actor_uuid(actor_id: str | None) -> uuid.UUID | None:
    """The acting user as the invoice's ``created_by``, or None when it is not a user id."""
    try:
        return uuid.UUID(str(actor_id)) if actor_id else None
    except ValueError:
        return None


def contract_source(contract_id: uuid.UUID | str) -> str:
    """Commitment key of a subcontract written in the contracts module."""
    return f"contract:{contract_id}"


def agreement_source(agreement_id: uuid.UUID | str) -> str:
    """Commitment key of a subcontract agreement written in this module."""
    return f"agreement:{agreement_id}"


async def _budget_row(session: AsyncSession, project_id: uuid.UUID) -> ProjectBudget | None:
    """The project's budget row that carries subcontract commitments.

    The oldest row, which is where a purchase order with no WBS hint lands as
    well, so both kinds of commitment sit on one row. Locked for the rest of
    the transaction, so a concurrent payment of the same invoice reads the
    marker this one writes instead of a copy from before it.
    """
    stmt = (
        select(ProjectBudget)
        .where(ProjectBudget.project_id == project_id)
        .order_by(ProjectBudget.created_at.asc())
        .limit(1)
        .with_for_update()
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def commit_subcontract(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    source: str,
    amount: object,
) -> bool:
    """Commit a signed subcontract's value to the budget, once.

    Returns True when the commitment was written, False when there is no budget
    row, no value, or the subcontract is already committed.
    """
    value = _dec(amount)
    if value <= 0:
        return False
    budget = await _budget_row(session, project_id)
    if budget is None:
        logger.info("subcontract %s signed on project %s with no budget row, nothing committed", source, project_id)
        return False
    md = dict(budget.metadata_ or {})
    key = f"{COMMITTED_PREFIX}{source}"
    if key in md:
        return False
    budget.committed = _dec(budget.committed) + value
    md[key] = str(value)
    budget.metadata_ = md
    await session.flush()
    return True


async def draw_down(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    source: str,
    invoice_id: uuid.UUID,
    amount: object,
) -> Decimal:
    """Take a paid invoice's gross off its subcontract's commitment, once.

    Returns the amount taken, which is zero on a replay, on a subcontract with
    nothing committed, and on a project with no budget row.
    """
    budget = await _budget_row(session, project_id)
    if budget is None:
        return _ZERO
    md = dict(budget.metadata_ or {})
    drawn_key = f"{DRAWN_PREFIX}{invoice_id}"
    commit_key = f"{COMMITTED_PREFIX}{source}"
    if drawn_key in md or commit_key not in md:
        return _ZERO
    remaining = _dec(md[commit_key])
    take = min(_dec(amount), remaining)
    if take <= 0:
        return _ZERO
    md[commit_key] = str(remaining - take)
    md[drawn_key] = str(take)
    budget.committed = max(_dec(budget.committed) - take, _ZERO)
    budget.metadata_ = md
    await session.flush()
    return take


async def subcontract_source_of(session: AsyncSession, invoice: Invoice) -> str | None:
    """The subcontract a payable invoice bills, as a commitment key, or None."""
    if invoice.invoice_direction != "payable":
        return None
    md = dict(invoice.metadata_ or {})
    if md.get("source") == PAY_APP_SOURCE and md.get("agreement_id"):
        return agreement_source(md["agreement_id"])
    if invoice.source_claim_id is not None and md.get("contract_id"):
        from app.modules.contracts.models import Contract  # noqa: PLC0415

        try:
            contract = await session.get(Contract, uuid.UUID(str(md["contract_id"])))
        except (ValueError, TypeError):
            return None
        if contract is not None and contract.counterparty_type == "subcontractor":
            return contract_source(contract.id)
    return None


async def draw_down_for_invoice(session: AsyncSession, invoice: Invoice) -> Decimal:
    """Draw down the commitment behind a paid payable, when it bills a subcontract."""
    source = await subcontract_source_of(session, invoice)
    if source is None:
        return _ZERO
    return await draw_down(
        session,
        project_id=invoice.project_id,
        source=source,
        invoice_id=invoice.id,
        amount=invoice.amount_subtotal,
    )


async def settle_payable(
    session: AsyncSession,
    invoice_id: uuid.UUID,
    *,
    actor_id: str | None = None,
    payment_date: str | None = None,
) -> Invoice:
    """Pay a subcontractor's payable the way finance books it.

    Approves a draft, records the payment with the retention held back (so the
    payables retention ledger shows it held rather than zero), marks the
    invoice paid (which recomputes actual), and draws the commitment down by
    the gross. Each step is skipped when it has already happened, so paying
    again is a no-op.
    """
    from app.modules.finance.schemas import RecordClaimPaymentRequest  # noqa: PLC0415
    from app.modules.finance.service import FinanceService  # noqa: PLC0415

    finance = FinanceService(session)
    invoice = await finance.get_invoice(invoice_id)
    if invoice.status in ("draft", "pending"):
        invoice = await finance.approve_invoice(invoice_id, actor_id=actor_id, reason="Subcontract payment")
    if invoice.status != "paid":
        await finance.record_payment_with_withholding(
            invoice_id,
            RecordClaimPaymentRequest(
                payment_date=payment_date or datetime.now(UTC).date().isoformat(),
                idempotency_key=f"subcontract-pay:{invoice_id}",
                reference=invoice.invoice_number,
            ),
            actor_id=actor_id,
        )
        invoice = await finance.pay_invoice(invoice_id, actor_id=actor_id, reason="Subcontract payment")
    await draw_down_for_invoice(session, invoice)
    return invoice


async def raise_payable_for_pay_app(
    session: AsyncSession,
    payment: Any,
    agreement: Any,
    *,
    actor_id: str | None = None,
) -> Invoice:
    """Raise the payable a finance-approved pay application is paid on, once.

    The invoice carries the approved gross with the retention broken out, the
    same money model a claim invoice uses: ``amount_total`` is the gross and
    ``retention_amount`` is held from it, so the net paid is the difference and
    retention is deducted exactly once. The pay application remembers its
    invoice, so approving it again returns the same one.
    """
    from app.modules.finance.repository import InvoiceRepository  # noqa: PLC0415
    from app.modules.subcontractors.models import Subcontractor  # noqa: PLC0415

    md = dict(payment.metadata_ or {})
    existing_id = md.get("payable_invoice_id")
    if existing_id:
        existing = await session.get(Invoice, uuid.UUID(str(existing_id)))
        if existing is not None:
            return existing

    gross = _dec(payment.approved_gross_amount if payment.approved_gross_amount is not None else payment.gross_amount)
    retention = _dec(
        payment.approved_retention_amount if payment.approved_retention_amount is not None else payment.retention_amount
    )
    sub = await session.get(Subcontractor, agreement.subcontractor_id)
    contact_id = str(sub.contact_id) if sub is not None and sub.contact_id else None
    invoices = InvoiceRepository(session)
    invoice = Invoice(
        project_id=agreement.project_id,
        contact_id=contact_id,
        invoice_direction="payable",
        invoice_number=await invoices.next_invoice_number(agreement.project_id, "payable"),
        invoice_date=(payment.period_end or datetime.now(UTC).date()).isoformat(),
        due_date=None,
        currency_code=(payment.currency or agreement.currency or "").strip().upper(),
        amount_subtotal=gross,
        tax_amount=_ZERO,
        retention_amount=retention,
        amount_total=gross,
        status="draft",
        notes=f"{agreement.title}, payment application {payment.application_number}",
        created_by=_actor_uuid(actor_id),
        metadata_={
            "source": PAY_APP_SOURCE,
            "payment_application_id": str(payment.id),
            "application_number": payment.application_number,
            "agreement_id": str(agreement.id),
            "subcontractor_id": str(agreement.subcontractor_id),
        },
    )
    await invoices.create(invoice)
    session.add(
        InvoiceLineItem(
            invoice_id=invoice.id,
            description=f"{agreement.title}, {payment.application_number}",
            quantity=Decimal("1"),
            unit="psch",
            unit_rate=gross,
            amount=gross,
            sort_order=0,
        )
    )
    md["payable_invoice_id"] = str(invoice.id)
    payment.metadata_ = md
    await session.flush()
    return invoice
