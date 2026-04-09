"""Procurement Pydantic schemas — request/response models."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_non_negative_decimal(v: str) -> str:
    """Validate that a string is a valid non-negative decimal number."""
    try:
        d = Decimal(v)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid decimal value: {v!r}") from exc
    if d < 0:
        raise ValueError(f"Value must be non-negative, got {v!r}")
    return v

# ── Purchase Order ───────────────────────────────────────────────────────────


class POItemCreate(BaseModel):
    """Create a line item within a purchase order."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(..., min_length=1, max_length=500)
    quantity: str = Field(default="1", max_length=50)
    unit: str | None = Field(default=None, max_length=20)
    unit_rate: str = Field(default="0", max_length=50)
    amount: str = Field(default="0", max_length=50)
    wbs_id: str | None = Field(default=None, max_length=36)
    cost_category: str | None = Field(default=None, max_length=100)
    sort_order: int = Field(default=0, ge=0)

    @field_validator("quantity", "unit_rate", "amount")
    @classmethod
    def _check_non_negative_decimal(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)


class POCreate(BaseModel):
    """Create a new purchase order."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    vendor_contact_id: str | None = Field(default=None, max_length=36)
    po_number: str | None = Field(default=None, max_length=50)
    po_type: str = Field(default="standard", max_length=50)
    issue_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    delivery_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    currency_code: str = Field(default="EUR", max_length=10)
    amount_subtotal: str = Field(default="0", max_length=50)
    tax_amount: str = Field(default="0", max_length=50)
    amount_total: str = Field(default="0", max_length=50)
    status: str = Field(default="draft", max_length=50)
    payment_terms: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=5000)
    items: list[POItemCreate] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("amount_subtotal", "tax_amount", "amount_total")
    @classmethod
    def _check_non_negative_decimal(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)


class POUpdate(BaseModel):
    """Partial update for a purchase order."""

    model_config = ConfigDict(str_strip_whitespace=True)

    vendor_contact_id: str | None = Field(default=None, max_length=36)
    po_type: str | None = Field(default=None, max_length=50)
    issue_date: str | None = Field(default=None, max_length=20)
    delivery_date: str | None = Field(default=None, max_length=20)
    currency_code: str | None = Field(default=None, max_length=10)
    amount_subtotal: str | None = Field(default=None, max_length=50)
    tax_amount: str | None = Field(default=None, max_length=50)
    amount_total: str | None = Field(default=None, max_length=50)
    status: str | None = Field(default=None, max_length=50)
    payment_terms: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=5000)
    items: list[POItemCreate] | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("amount_subtotal", "tax_amount", "amount_total")
    @classmethod
    def _check_non_negative_decimal(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_non_negative_decimal(v)


# ── Purchase Order responses ─────────────────────────────────────────────────


class POItemResponse(BaseModel):
    """PO item returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    po_id: UUID
    description: str
    quantity: str = "1"
    unit: str | None = None
    unit_rate: str = "0"
    amount: str = "0"
    wbs_id: str | None = None
    cost_category: str | None = None
    sort_order: int = 0
    created_at: datetime
    updated_at: datetime


class POResponse(BaseModel):
    """Purchase order returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    vendor_contact_id: str | None = None
    po_number: str
    po_type: str = "standard"
    issue_date: str | None = None
    delivery_date: str | None = None
    currency_code: str = "EUR"
    amount_subtotal: str = "0"
    tax_amount: str = "0"
    amount_total: str = "0"
    status: str = "draft"
    payment_terms: str | None = None
    notes: str | None = None
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    items: list[POItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class POListResponse(BaseModel):
    """Paginated list of purchase orders."""

    items: list[POResponse]
    total: int
    offset: int
    limit: int


# ── Goods Receipt ────────────────────────────────────────────────────────────


class GRItemCreate(BaseModel):
    """Create a goods receipt line item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    po_item_id: UUID | None = None
    quantity_ordered: str = Field(default="0", max_length=50)
    quantity_received: str = Field(default="0", max_length=50)
    quantity_rejected: str = Field(default="0", max_length=50)
    rejection_reason: str | None = None

    @field_validator("quantity_ordered", "quantity_received", "quantity_rejected")
    @classmethod
    def _check_non_negative_decimal(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)


class GRCreate(BaseModel):
    """Create a goods receipt against a PO."""

    model_config = ConfigDict(str_strip_whitespace=True)

    po_id: UUID
    receipt_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    received_by_id: UUID | None = None
    delivery_note_number: str | None = Field(default=None, max_length=100)
    status: str = Field(default="draft", max_length=50)
    notes: str | None = Field(default=None, max_length=5000)
    items: list[GRItemCreate] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Goods Receipt responses ──────────────────────────────────────────────────


class GRItemResponse(BaseModel):
    """GR item returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    receipt_id: UUID
    po_item_id: UUID | None = None
    quantity_ordered: str = "0"
    quantity_received: str = "0"
    quantity_rejected: str = "0"
    rejection_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class GRResponse(BaseModel):
    """Goods receipt returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    po_id: UUID
    receipt_date: str
    received_by_id: UUID | None = None
    delivery_note_number: str | None = None
    status: str = "draft"
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    items: list[GRItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class GRListResponse(BaseModel):
    """Paginated list of goods receipts."""

    items: list[GRResponse]
    total: int


# ── Stats ────────────────────────────────────────────────────────────────


class ProcurementStatsResponse(BaseModel):
    """Aggregate statistics for procurement within a project."""

    total_pos: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    total_committed: str = "0"
    total_received: int = 0
    pending_delivery_count: int = 0
