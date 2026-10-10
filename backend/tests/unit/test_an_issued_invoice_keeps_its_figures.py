# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An approved, sent or paid invoice keeps what it charges, to whom and in which currency.

``update_invoice`` checked only that a status change followed the invoice
lifecycle. It never looked at the status the invoice was already in, so the
same PATCH rewrote the subtotal, tax, total, currency, counterparty and every
line of an invoice that had been approved, sent to the customer or paid,
including a receivable raised from a certified claim. The status table itself
already says a paid invoice only moves on to a credit note.

The edit form in the finance page sends every field back on each save, so the
refusal is about real changes: the stored figures sent back unchanged, a note,
a due date or a legal status move still go through.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.finance.models import InvoiceLineItem
from app.modules.finance.schemas import InvoiceCreate, InvoiceLineItemCreate, InvoiceUpdate
from app.modules.finance.service import FinanceService
from tests.unit.test_finance_service import _make_service


async def _invoice(status: str) -> tuple[FinanceService, Any]:
    """A receivable of 1,000 plus 190 tax in EUR with one line, put in ``status``."""
    service = _make_service()
    invoice: Any = await service.create_invoice(
        InvoiceCreate(
            project_id=uuid.uuid4(),
            invoice_direction="receivable",
            invoice_date="2026-04-01",
            amount_subtotal="1000",
            tax_amount="190",
            currency_code="EUR",
        )
    )
    # A real (transient) line model: ``line_items`` is an instrumented relationship, and
    # assigning anything that is not a mapped instance fails on its backref.
    invoice.line_items = [InvoiceLineItem(description="Works", amount=Decimal("1000"))]
    invoice.status = status
    return service, invoice


def _line(amount: str) -> InvoiceLineItemCreate:
    return InvoiceLineItemCreate(description="Works", quantity="1", unit="lsum", unit_rate=amount, amount=amount)


# ── The guard that already held ─────────────────────────────────────────────


async def test_control_a_paid_invoice_cannot_go_back_to_draft() -> None:
    service, invoice = await _invoice("paid")
    with pytest.raises(HTTPException) as exc:
        await service.update_invoice(invoice.id, InvoiceUpdate(status="draft"))
    assert exc.value.status_code == 400


# ── Issued invoices ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["approved", "sent", "paid", "cancelled"])
@pytest.mark.parametrize(
    "change",
    [
        {"amount_subtotal": "2000", "tax_amount": "380"},
        {"amount_total": "1190", "amount_subtotal": "1190", "tax_amount": "0"},
        {"currency_code": "USD"},
        {"contact_id": "another-customer"},
    ],
)
async def test_an_issued_invoice_keeps_its_figures_and_parties(status: str, change: dict[str, str]) -> None:
    service, invoice = await _invoice(status)
    with pytest.raises(HTTPException) as exc:
        await service.update_invoice(invoice.id, InvoiceUpdate.model_validate(change))
    assert exc.value.status_code == 409
    assert Decimal(invoice.amount_total) == Decimal("1190")
    assert invoice.currency_code == "EUR"


async def test_an_issued_invoice_keeps_its_lines() -> None:
    service, invoice = await _invoice("sent")
    with pytest.raises(HTTPException) as exc:
        await service.update_invoice(
            invoice.id,
            InvoiceUpdate(amount_subtotal="1500", tax_amount="285", line_items=[_line("1500")]),
        )
    assert exc.value.status_code == 409


@pytest.mark.parametrize("status", ["approved", "sent", "paid", "cancelled"])
@pytest.mark.parametrize("field", ["amount_subtotal", "tax_amount", "retention_amount", "amount_total"])
async def test_an_issued_invoice_rejects_a_milliunit_header_change(status: str, field: str) -> None:
    """Transient fixtures isolate the guard from database storage rounding."""
    service, invoice = await _invoice(status)
    original = Decimal(str(getattr(invoice, field) or "0")) + Decimal("0.001")
    setattr(invoice, field, original)
    change = {field: str(original + Decimal("0.001"))}

    with pytest.raises(HTTPException) as exc:
        await service.update_invoice(invoice.id, InvoiceUpdate.model_validate(change))

    assert exc.value.status_code == 409
    assert field in exc.value.detail
    assert Decimal(str(getattr(invoice, field))) == original
    assert invoice.status == status


@pytest.mark.parametrize("status", ["approved", "sent", "paid", "cancelled"])
async def test_an_issued_invoice_rejects_a_milliunit_line_change(status: str) -> None:
    service, invoice = await _invoice(status)
    invoice.line_items[0].amount = Decimal("1000.001")

    with pytest.raises(HTTPException) as exc:
        await service.update_invoice(invoice.id, InvoiceUpdate(line_items=[_line("1000.002")]))

    assert exc.value.status_code == 409
    assert "line_items" in exc.value.detail
    assert invoice.line_items[0].amount == Decimal("1000.001")


async def test_an_issued_invoice_does_not_treat_an_infinite_line_as_zero() -> None:
    # Bypass request validation only to exercise the internal service guard.
    # It must reject nonfinite amounts before consistency checks or line writes.
    service, invoice = await _invoice("sent")
    invoice.line_items = [InvoiceLineItem(description="Zero allowance", amount=Decimal("0"))]

    invalid_line = InvoiceLineItemCreate.model_construct(
        description="Works", quantity="1", unit="lsum", unit_rate="Infinity", amount="Infinity"
    )
    request = InvoiceUpdate.model_construct(line_items=[invalid_line])
    with pytest.raises(HTTPException) as exc:
        await service.update_invoice(invoice.id, request)

    assert exc.value.status_code == 409
    assert "line_items" in exc.value.detail
    assert invoice.line_items[0].amount == Decimal("0")


async def test_exact_milliunit_echo_accepts_trailing_zeros_and_reordered_lines() -> None:
    service, invoice = await _invoice("sent")
    invoice.amount_subtotal = Decimal("1000.003")
    invoice.tax_amount = Decimal("190.001")
    invoice.retention_amount = Decimal("0.001")
    invoice.amount_total = Decimal("1190.004")
    invoice.line_items = [
        InvoiceLineItem(description="First", amount=Decimal("600.001")),
        InvoiceLineItem(description="Second", amount=Decimal("400.002")),
    ]
    updated = await service.update_invoice(
        invoice.id,
        InvoiceUpdate(
            amount_subtotal="1000.0030",
            tax_amount="190.0010",
            retention_amount="0.0010",
            amount_total="1190.0040",
            line_items=[_line("400.0020"), _line("600.0010")],
            notes="Equivalent figures, reordered descriptions",
        ),
    )

    assert Decimal(updated.amount_total) == Decimal("1190.004")
    assert Decimal(updated.retention_amount) == Decimal("0.001")
    assert updated.notes == "Equivalent figures, reordered descriptions"


# ── What still goes through ─────────────────────────────────────────────────


async def test_the_edit_form_sending_the_stored_figures_back_is_not_a_change() -> None:
    """The finance page resends subtotal, tax, total, currency and its one line on every save."""
    service, invoice = await _invoice("sent")
    updated = await service.update_invoice(
        invoice.id,
        InvoiceUpdate(
            amount_subtotal="1000.00",
            tax_amount="190.00",
            amount_total="1190.00",
            currency_code="EUR",
            invoice_direction="receivable",
            notes="Paid by bank transfer",
            due_date="2026-05-01",
            line_items=[_line("1000.00")],
            status="paid",
        ),
    )
    assert updated.status == "paid"
    assert updated.notes == "Paid by bank transfer"
    assert Decimal(updated.amount_total) == Decimal("1190")


async def test_a_draft_invoice_still_takes_new_figures() -> None:
    service, invoice = await _invoice("draft")
    updated = await service.update_invoice(
        invoice.id,
        InvoiceUpdate(amount_subtotal="2000", tax_amount="380"),
    )
    assert Decimal(updated.amount_total) == Decimal("2380")


async def test_a_cancelled_invoice_reopened_as_a_draft_may_be_corrected_in_the_same_write() -> None:
    service, invoice = await _invoice("cancelled")
    updated = await service.update_invoice(
        invoice.id,
        InvoiceUpdate(status="draft", amount_subtotal="2000", tax_amount="380"),
    )
    assert updated.status == "draft"
    assert Decimal(updated.amount_total) == Decimal("2380")
