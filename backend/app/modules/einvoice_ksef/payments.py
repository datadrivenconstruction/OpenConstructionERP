# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The KSeF number of an invoice, and the KSeF number in a payment title.

Where the number lives
======================
For an invoice the platform issued, it is the ``authority_identifier`` of the
invoice's cleared Polish clearance document. It is not copied onto the finance
invoice, because a copy is a second place for the number to be wrong. For an
invoice the company received, there is no clearance document, and the number is
entered on the invoice as ``metadata["ksef_number"]``. Outgoing and incoming
invoices are disjoint, so :func:`ksef_number_for_invoice` reads one or the other.

The payment title
=================
From 2027-01-01 a transfer paying a structured invoice between VAT payers
carries the KSeF number in its title (split payment transfers included). In
2026 it is recommended. :func:`payment_title_finding` answers per payment, with
the severity the date calls for.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.modules.einvoice_ksef import ksef_number
from app.modules.einvoice_ksef.facts import KSEF_NUMBER_IN_PAYMENT_TITLE, on_or_after

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_NONE = ""


def number_from_metadata(metadata: dict[str, Any] | None) -> str:
    """The KSeF number entered on an invoice, if it is a valid one."""
    value = str((metadata or {}).get("ksef_number") or "").strip()
    return value if ksef_number.is_valid(value) else ""


async def ksef_number_for_invoice(session: Any, invoice: Any) -> str:
    """The KSeF number of a finance invoice, or ``""`` when it has none.

    Reads the cleared clearance document for an issued invoice and the entered
    number for a received one.
    """
    entered = number_from_metadata(getattr(invoice, "metadata_", None))
    if entered:
        return entered
    from sqlalchemy import select

    from app.modules.einvoice_clearance.models import STATUS_CLEARED, EInvoiceDocument

    invoice_id = invoice.id if isinstance(invoice.id, uuid.UUID) else uuid.UUID(str(invoice.id))
    rows = (
        (
            await session.execute(
                select(EInvoiceDocument.authority_identifier)
                .where(
                    EInvoiceDocument.invoice_id == invoice_id,
                    EInvoiceDocument.country == "PL",
                    EInvoiceDocument.status == STATUS_CLEARED,
                )
                .order_by(EInvoiceDocument.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return next((value for value in rows if ksef_number.is_valid(value)), "")


@dataclass(frozen=True)
class PaymentTitleFinding:
    severity: str
    message: str

    @property
    def passed(self) -> bool:
        return self.severity == SEVERITY_NONE


def payment_title_finding(
    *,
    payment_date: date,
    title: str,
    invoice_ksef_number: str,
    between_vat_payers: bool = True,
) -> PaymentTitleFinding:
    """Whether a payment's title carries the KSeF number it should.

    Args:
        payment_date: The day of the transfer.
        title: The transfer title (the payment's reference).
        invoice_ksef_number: The KSeF number of the invoice paid, ``""`` if it has none.
        between_vat_payers: False for a payment to or from a consumer, which the rule does not reach.
    """
    if not invoice_ksef_number or not between_vat_payers:
        return PaymentTitleFinding(SEVERITY_NONE, "The invoice has no KSeF number to quote.")
    if invoice_ksef_number in (title or ""):
        return PaymentTitleFinding(SEVERITY_NONE, "The payment title carries the invoice's KSeF number.")
    if on_or_after(payment_date, KSEF_NUMBER_IN_PAYMENT_TITLE):
        return PaymentTitleFinding(
            SEVERITY_ERROR,
            f"From {KSEF_NUMBER_IN_PAYMENT_TITLE.effective_date} the title of a transfer paying a KSeF invoice must "
            f"carry its KSeF number {invoice_ksef_number}.",
        )
    return PaymentTitleFinding(
        SEVERITY_WARNING,
        f"Put the KSeF number {invoice_ksef_number} in the payment title. It is recommended now and required "
        f"from {KSEF_NUMBER_IN_PAYMENT_TITLE.effective_date}.",
    )


def suggested_title(invoice_number: str, invoice_ksef_number: str) -> str:
    """A payment title that satisfies the rule: the KSeF number first, then the invoice number."""
    parts = [p for p in ((invoice_ksef_number or "").strip(), (invoice_number or "").strip()) if p]
    return " ".join(parts)


__all__ = [
    "SEVERITY_ERROR",
    "SEVERITY_NONE",
    "SEVERITY_WARNING",
    "PaymentTitleFinding",
    "ksef_number_for_invoice",
    "number_from_metadata",
    "payment_title_finding",
    "suggested_title",
]
