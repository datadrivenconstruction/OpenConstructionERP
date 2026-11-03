# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic schemas for the invoice-approval DMS.

Money is Decimal-as-string on the wire, consistent with the rest of the finance
module (see :mod:`app.modules.finance.schemas`).
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_non_negative_decimal(v: str, field_name: str = "value") -> str:
    try:
        d = Decimal(v)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid decimal value for {field_name}: {v!r}") from exc
    if d < 0:
        raise ValueError(f"{field_name} must be non-negative, got {v!r}")
    return v


def _decimal_to_str(v: object) -> object:
    if isinstance(v, Decimal):
        return format(v, "f")
    return v


# ── Line items (captured draft) ──────────────────────────────────────────────


class CaptureLineItem(BaseModel):
    """One draft line on a captured invoice."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(default="", max_length=500)
    quantity: str = Field(default="1", max_length=50)
    unit_rate: str = Field(default="0", max_length=50)
    amount: str = Field(default="0", max_length=50)
    cost_code: str | None = Field(default=None, max_length=100)

    @field_validator("quantity", "unit_rate", "amount")
    @classmethod
    def _non_negative(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)


# ── Create / update ──────────────────────────────────────────────────────────


class CaptureManualCreate(BaseModel):
    """Create a captured invoice by hand (the no-OCR fallback path)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    doc_kind: str = Field(default="invoice", pattern=r"^(invoice|delivery_note)$")
    supplier_name: str = Field(default="", max_length=255)
    supplier_tax_id: str | None = Field(default=None, max_length=60)
    supplier_contact_id: str | None = Field(default=None, max_length=36)
    invoice_number: str = Field(default="", max_length=100)
    invoice_date: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$", max_length=20)
    due_date: str | None = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$", max_length=20)
    currency_code: str = Field(default="", max_length=10)
    amount_net: str = Field(default="0", max_length=50)
    amount_tax: str = Field(default="0", max_length=50)
    amount_gross: str = Field(default="0", max_length=50)
    po_reference: str | None = Field(default=None, max_length=100)
    line_items: list[CaptureLineItem] = Field(default_factory=list)

    @field_validator("amount_net", "amount_tax", "amount_gross")
    @classmethod
    def _non_negative(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)


class CaptureUpdate(BaseModel):
    """Patch the reviewed draft fields. Rejected on a posted (sealed) record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    supplier_name: str | None = Field(default=None, max_length=255)
    supplier_tax_id: str | None = Field(default=None, max_length=60)
    supplier_contact_id: str | None = Field(default=None, max_length=36)
    invoice_number: str | None = Field(default=None, max_length=100)
    invoice_date: str | None = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$", max_length=20)
    due_date: str | None = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$", max_length=20)
    currency_code: str | None = Field(default=None, max_length=10)
    amount_net: str | None = Field(default=None, max_length=50)
    amount_tax: str | None = Field(default=None, max_length=50)
    amount_gross: str | None = Field(default=None, max_length=50)
    po_reference: str | None = Field(default=None, max_length=100)
    line_items: list[CaptureLineItem] | None = None

    @field_validator("amount_net", "amount_tax", "amount_gross")
    @classmethod
    def _non_negative(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_non_negative_decimal(v)


class BookingInput(BaseModel):
    """The confirmed booking a user codes onto a captured invoice."""

    model_config = ConfigDict(str_strip_whitespace=True)

    expense_account: str = Field(..., min_length=1, max_length=100)
    payable_account: str = Field(..., min_length=1, max_length=100)
    tax_account: str | None = Field(default=None, max_length=100)
    cost_code: str | None = Field(default=None, max_length=100)
    booking_project_id: UUID | None = Field(default=None)


class PurchaseOrderLink(BaseModel):
    """Link a captured invoice to its purchase order (``null`` clears the link)."""

    purchase_order_id: UUID | None = None


class ApproveInput(BaseModel):
    """Optional body of the approve call."""

    acknowledge_match: bool = Field(
        default=False,
        description="Accept the open order / goods-receipt mismatches of this invoice.",
    )


class RejectInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    reason: str = Field(..., min_length=1, max_length=2000)


class QueryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    note: str = Field(..., min_length=1, max_length=2000)


# ── Responses ────────────────────────────────────────────────────────────────


class ValidationFinding(BaseModel):
    severity: str
    code: str
    message: str
    field: str | None = None


class BookingProposalResponse(BaseModel):
    expense_account: str | None = None
    tax_account: str | None = None
    payable_account: str | None = None
    cost_code: str | None = None
    confidence: float = 0.0
    rationale: list[str] = Field(default_factory=list)


class CaptureResponse(BaseModel):
    """A captured invoice with its draft, booking, validation and seal."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    doc_kind: str = "invoice"
    direction: str = "payable"
    status: str = "captured"

    original_filename: str = ""
    storage_key: str | None = None
    mime_type: str | None = None
    file_size: int = 0
    content_sha256: str | None = None
    has_document: bool = False

    supplier_name: str = ""
    supplier_tax_id: str | None = None
    supplier_contact_id: str | None = None
    invoice_number: str = ""
    invoice_date: str = ""
    due_date: str | None = None
    currency_code: str = ""
    amount_net: str = "0"
    amount_tax: str = "0"
    amount_gross: str = "0"
    line_items: list[dict[str, Any]] = Field(default_factory=list)

    po_reference: str | None = None
    purchase_order_id: UUID | None = None

    extraction_engine: str = "manual"
    field_confidence: dict[str, Any] = Field(default_factory=dict)

    booking_expense_account: str | None = None
    booking_tax_account: str | None = None
    booking_payable_account: str | None = None
    booking_cost_code: str | None = None
    booking_project_id: UUID | None = None

    approver_id: UUID | None = None
    approved_at: str | None = None
    rejected_reason: str | None = None
    queried_note: str | None = None

    posted_at: str | None = None
    posted_transaction_ref: str | None = None
    posted_invoice_id: UUID | None = None
    archive_hash: str | None = None
    archive_sealed_at: str | None = None
    retention_until: str | None = None

    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # Computed / attached by the router (not ORM columns).
    validation: list[ValidationFinding] = Field(default_factory=list)
    booking_proposal: BookingProposalResponse | None = None

    _coerce_money = field_validator("amount_net", "amount_tax", "amount_gross", mode="before")(
        lambda cls, v: _decimal_to_str(v)
    )


class CaptureListResponse(BaseModel):
    items: list[CaptureResponse]
    total: int


class ArchiveVerifyResponse(BaseModel):
    """Result of re-checking a sealed archive's integrity."""

    id: UUID
    sealed: bool
    document_present: bool
    document_intact: bool | None = None
    booking_intact: bool
    overall_intact: bool
    content_sha256: str | None = None
    recomputed_document_sha256: str | None = None
    archive_hash: str | None = None
    recomputed_archive_hash: str | None = None
    retention_until: str | None = None
    message: str = ""


class AuditEntryResponse(BaseModel):
    """One append-only audit-log row for a captured invoice."""

    action: str
    from_status: str | None = None
    to_status: str | None = None
    reason: str | None = None
    actor_id: str | None = None
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditListResponse(BaseModel):
    items: list[AuditEntryResponse]
    total: int
