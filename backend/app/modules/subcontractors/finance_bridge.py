# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Where subcontract money meets the payables ledger.

Each payment application is a bill from the subcontractor, so approving one
raises a payable, and paying it books the gross as spent. The retention on it
is held from what we pay, so the payment holds it back and the payables
retention ledger shows it held.

Everything here writes through the caller's session. Nothing commits, so the
subcontract, its invoice and the budget move in one transaction or not at all.

The budget is finance's: ``FinanceService.sync_project_budget`` works out what
a subcontract has committed and spent from the agreement, the contract and
their invoices, so nothing here writes a budget row. This module only tells it
when one of those moved.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.models import Invoice, InvoiceLineItem

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
    invoice paid. Finance brings the budget along on each step. Each step is
    skipped when it has already happened, so paying again is a no-op.
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

    The invoice is written through the repository, not finance's create path,
    so the budget is brought up to it here.
    """
    from app.modules.finance.repository import InvoiceRepository  # noqa: PLC0415
    from app.modules.finance.service import FinanceService  # noqa: PLC0415
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
            # Finance lands it on the project's subcontractor row, or on the
            # project-level row when there is none.
            cost_category="subcontractor",
            sort_order=0,
        )
    )
    md["payable_invoice_id"] = str(invoice.id)
    payment.metadata_ = md
    await session.flush()
    await FinanceService(session).sync_project_budget(agreement.project_id)
    return invoice
