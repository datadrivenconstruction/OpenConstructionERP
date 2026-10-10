# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Finance request strings must reject nonfinite numbers as validation errors."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.modules.finance.schemas import (
    EVMSnapshotCreate,
    InvoiceCreate,
    InvoiceLineItemCreate,
    InvoiceUpdate,
    JournalLineInput,
    LedgerEntryCreate,
    PaymentCreate,
    RecordClaimPaymentRequest,
)

_ID = UUID("476b6849-a3ee-46cb-9c17-299c291d2154")


def _cases():
    """All amount fields on the targeted request models, including signed EVM."""
    groups = [
        (
            InvoiceCreate,
            {"project_id": _ID, "invoice_direction": "receivable"},
            ("amount_subtotal", "tax_amount", "retention_amount", "amount_total"),
        ),
        (InvoiceUpdate, {}, ("amount_subtotal", "tax_amount", "retention_amount", "amount_total")),
        (InvoiceLineItemCreate, {"description": "Line"}, ("quantity", "unit_rate", "amount", "vat_rate")),
        (
            PaymentCreate,
            {"invoice_id": _ID, "payment_date": "2026-06-10", "amount": "1"},
            ("amount", "exchange_rate_snapshot", "withholding_amount"),
        ),
        (
            RecordClaimPaymentRequest,
            {"payment_date": "2026-06-10"},
            ("amount", "withholding_amount", "exchange_rate_snapshot"),
        ),
        (JournalLineInput, {"account_code": "1000"}, ("debit", "credit")),
        (
            LedgerEntryCreate,
            {
                "project_id": _ID,
                "transaction_ref": "finite-input",
                "debit_account": "1000",
                "credit_account": "4000",
                "debit_amount": "1",
                "credit_amount": "1",
            },
            ("debit_amount", "credit_amount"),
        ),
        (
            EVMSnapshotCreate,
            {"project_id": _ID, "snapshot_date": "2026-06-10"},
            ("bac", "pv", "ev", "ac", "sv", "cv", "spi", "cpi"),
        ),
    ]
    return [
        pytest.param(model, payload, field, id=f"{model.__name__}-{field}")
        for model, payload, fields in groups
        for field in fields
    ]


@pytest.mark.parametrize("model,payload,field", _cases())
@pytest.mark.parametrize("value", ["Infinity", "-Infinity", "NaN", "sNaN"])
def test_nonfinite_request_amount_is_a_field_validation_error(model, payload, field, value):
    # InvalidOperation escaping a validator is not a request validation error.
    with pytest.raises(ValidationError) as error:
        model.model_validate({**payload, field: value})

    assert any(item["loc"] == (field,) for item in error.value.errors())


@pytest.mark.parametrize("model,payload,field", _cases())
def test_finite_request_spelling_is_preserved(model, payload, field):
    value = "1.2300"
    result = model.model_validate({**payload, field: value})
    assert getattr(result, field) == value


@pytest.mark.parametrize("field", ["sv", "cv", "spi", "cpi"])
@pytest.mark.parametrize("value", ["-1.25", "0", "-0.00", "1E-3"])
def test_signed_evm_fields_keep_finite_negative_zero_and_exponent_values(field, value):
    result = EVMSnapshotCreate.model_validate({"project_id": _ID, "snapshot_date": "2026-06-10", field: value})
    assert getattr(result, field) == value
    assert Decimal(getattr(result, field)).is_finite()


@pytest.mark.parametrize("value", ["0", "-0.00"])
def test_nonnegative_invoice_and_claim_fields_still_allow_zero(value):
    assert InvoiceUpdate(amount_total=value).amount_total == value
    assert InvoiceLineItemCreate(description="Line", amount=value).amount == value
    assert RecordClaimPaymentRequest(payment_date="2026-06-10", amount=value).amount == value
    assert JournalLineInput(account_code="1000", debit=value).debit == value


@pytest.mark.parametrize("field", ["amount", "exchange_rate_snapshot"])
@pytest.mark.parametrize("value", ["0", "-0.00", "-1"])
def test_positive_payment_fields_still_reject_zero_and_negative_values(field, value):
    with pytest.raises(ValidationError):
        PaymentCreate.model_validate({"invoice_id": _ID, "payment_date": "2026-06-10", "amount": "1", field: value})


def test_nonnegative_invoice_fields_still_reject_finite_negative_values():
    with pytest.raises(ValidationError):
        InvoiceUpdate(amount_total="-0.01")


def test_optional_patch_and_claim_amounts_still_allow_none():
    assert InvoiceUpdate(amount_total=None).amount_total is None
    request = RecordClaimPaymentRequest(payment_date="2026-06-10", amount=None, withholding_amount=None)
    assert request.amount is None
    assert request.withholding_amount is None
