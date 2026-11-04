"""Payment guards: idempotency replay scope, cancelled invoices, PATCH release gate."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.modules.finance.schemas import InvoiceCreate, InvoiceUpdate, PaymentCreate, RecordClaimPaymentRequest
from tests.unit.test_finance_service import _make_service


def _with_key_lookup(service):
    async def _by_key(key):
        return next((p for p in service.payments_repo.rows if p.idempotency_key == key), None)

    service.payments_repo.get_by_idempotency_key = _by_key
    return service


async def _invoice(service):
    return await service.create_invoice(
        InvoiceCreate(
            project_id=uuid.uuid4(),
            invoice_direction="payable",
            invoice_date="2026-04-01",
            amount_subtotal="100",
            tax_amount="0",
        )
    )


@pytest.mark.asyncio
async def test_idempotency_key_reused_on_other_invoice_is_conflict() -> None:
    service = _with_key_lookup(_make_service())
    first, second = await _invoice(service), await _invoice(service)
    await service.create_payment(
        PaymentCreate(invoice_id=first.id, payment_date="2026-04-05", amount="100", idempotency_key="k1")
    )
    with pytest.raises(HTTPException) as exc:
        await service.create_payment(
            PaymentCreate(invoice_id=second.id, payment_date="2026-04-05", amount="100", idempotency_key="k1")
        )
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc2:
        await service.record_payment_with_withholding(
            second.id, RecordClaimPaymentRequest(payment_date="2026-04-05", idempotency_key="k1")
        )
    assert exc2.value.status_code == 409


@pytest.mark.asyncio
async def test_payment_on_cancelled_invoice_is_refused() -> None:
    service = _make_service()
    inv = await _invoice(service)
    await service.update_invoice(inv.id, InvoiceUpdate(status="cancelled"))
    with pytest.raises(HTTPException) as exc:
        await service.create_payment(PaymentCreate(invoice_id=inv.id, payment_date="2026-04-05", amount="10"))
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc2:
        await service.record_payment_with_withholding(
            inv.id, RecordClaimPaymentRequest(payment_date="2026-04-05", amount="10")
        )
    assert exc2.value.status_code == 409


@pytest.mark.asyncio
async def test_patch_to_paid_runs_payment_release_rules() -> None:
    service = _make_service()
    inv = await _invoice(service)
    await service.update_invoice(inv.id, InvoiceUpdate(status="approved"))
    seen: list[str] = []

    async def _deny(invoice) -> None:
        seen.append(invoice.status)
        raise HTTPException(status_code=422, detail="goods receipt pending")

    service._check_payment_release = _deny
    with pytest.raises(HTTPException) as exc:
        await service.update_invoice(inv.id, InvoiceUpdate(status="paid"))
    assert exc.value.status_code == 422 and seen == ["approved"]
    assert service.invoices.rows[inv.id].status == "approved"
