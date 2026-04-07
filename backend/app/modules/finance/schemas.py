"""Finance Pydantic schemas — request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Invoice ──────────────────────────────────────────────────────────────────


class InvoiceLineItemCreate(BaseModel):
    """Create a line item within an invoice."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(..., max_length=500)
    quantity: str = Field(default="1", max_length=50)
    unit: str | None = Field(default=None, max_length=20)
    unit_rate: str = Field(default="0", max_length=50)
    amount: str = Field(default="0", max_length=50)
    wbs_id: str | None = Field(default=None, max_length=36)
    cost_category: str | None = Field(default=None, max_length=100)
    sort_order: int = 0


class InvoiceCreate(BaseModel):
    """Create a new invoice."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    contact_id: str | None = Field(default=None, max_length=36)
    invoice_direction: str = Field(
        ...,
        pattern=r"^(payable|receivable)$",
    )
    invoice_number: str | None = Field(default=None, max_length=50)
    invoice_date: str = Field(..., max_length=20)
    due_date: str | None = Field(default=None, max_length=20)
    currency_code: str = Field(default="EUR", max_length=10)
    amount_subtotal: str = Field(default="0", max_length=50)
    tax_amount: str = Field(default="0", max_length=50)
    retention_amount: str = Field(default="0", max_length=50)
    amount_total: str = Field(default="0", max_length=50)
    tax_config_id: str | None = Field(default=None, max_length=36)
    status: str = Field(default="draft", max_length=50)
    payment_terms_days: str | None = Field(default=None, max_length=10)
    notes: str | None = None
    line_items: list[InvoiceLineItemCreate] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InvoiceUpdate(BaseModel):
    """Partial update for an invoice."""

    model_config = ConfigDict(str_strip_whitespace=True)

    contact_id: str | None = Field(default=None, max_length=36)
    invoice_direction: str | None = Field(
        default=None,
        pattern=r"^(payable|receivable)$",
    )
    invoice_date: str | None = Field(default=None, max_length=20)
    due_date: str | None = Field(default=None, max_length=20)
    currency_code: str | None = Field(default=None, max_length=10)
    amount_subtotal: str | None = Field(default=None, max_length=50)
    tax_amount: str | None = Field(default=None, max_length=50)
    retention_amount: str | None = Field(default=None, max_length=50)
    amount_total: str | None = Field(default=None, max_length=50)
    tax_config_id: str | None = Field(default=None, max_length=36)
    status: str | None = Field(default=None, max_length=50)
    payment_terms_days: str | None = Field(default=None, max_length=10)
    notes: str | None = None
    line_items: list[InvoiceLineItemCreate] | None = None
    metadata: dict[str, Any] | None = None


# ── Invoice responses ────────────────────────────────────────────────────────


class InvoiceLineItemResponse(BaseModel):
    """Line item returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    invoice_id: UUID
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


class InvoiceResponse(BaseModel):
    """Invoice returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    contact_id: str | None = None
    invoice_direction: str
    invoice_number: str
    invoice_date: str
    due_date: str | None = None
    currency_code: str = "EUR"
    amount_subtotal: str = "0"
    tax_amount: str = "0"
    retention_amount: str = "0"
    amount_total: str = "0"
    tax_config_id: str | None = None
    status: str = "draft"
    payment_terms_days: str | None = None
    notes: str | None = None
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    line_items: list[InvoiceLineItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class InvoiceListResponse(BaseModel):
    """Paginated list of invoices."""

    items: list[InvoiceResponse]
    total: int
    offset: int
    limit: int


# ── Payment ──────────────────────────────────────────────────────────────────


class PaymentCreate(BaseModel):
    """Create a payment against an invoice."""

    model_config = ConfigDict(str_strip_whitespace=True)

    invoice_id: UUID
    payment_date: str = Field(..., max_length=20)
    amount: str = Field(..., max_length=50)
    currency_code: str = Field(default="EUR", max_length=10)
    exchange_rate_snapshot: str = Field(default="1", max_length=50)
    reference: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaymentResponse(BaseModel):
    """Payment returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    invoice_id: UUID
    payment_date: str
    amount: str
    currency_code: str = "EUR"
    exchange_rate_snapshot: str = "1"
    reference: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class PaymentListResponse(BaseModel):
    """Paginated list of payments."""

    items: list[PaymentResponse]
    total: int


# ── Budget ───────────────────────────────────────────────────────────────────


class BudgetCreate(BaseModel):
    """Create a project budget line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    wbs_id: str | None = Field(default=None, max_length=36)
    category: str | None = Field(default=None, max_length=100)
    original_budget: str = Field(default="0", max_length=50)
    revised_budget: str = Field(default="0", max_length=50)
    committed: str = Field(default="0", max_length=50)
    actual: str = Field(default="0", max_length=50)
    forecast_final: str = Field(default="0", max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BudgetUpdate(BaseModel):
    """Partial update for a budget line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    wbs_id: str | None = Field(default=None, max_length=36)
    category: str | None = Field(default=None, max_length=100)
    original_budget: str | None = Field(default=None, max_length=50)
    revised_budget: str | None = Field(default=None, max_length=50)
    committed: str | None = Field(default=None, max_length=50)
    actual: str | None = Field(default=None, max_length=50)
    forecast_final: str | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None


class BudgetResponse(BaseModel):
    """Budget line returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    wbs_id: str | None = None
    category: str | None = None
    original_budget: str = "0"
    revised_budget: str = "0"
    committed: str = "0"
    actual: str = "0"
    forecast_final: str = "0"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class BudgetListResponse(BaseModel):
    """Paginated list of budgets."""

    items: list[BudgetResponse]
    total: int


# ── EVM ──────────────────────────────────────────────────────────────────────


class EVMSnapshotCreate(BaseModel):
    """Create an EVM snapshot."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    snapshot_date: str = Field(..., max_length=20)
    bac: str = Field(default="0", max_length=50)
    pv: str = Field(default="0", max_length=50)
    ev: str = Field(default="0", max_length=50)
    ac: str = Field(default="0", max_length=50)
    sv: str = Field(default="0", max_length=50)
    cv: str = Field(default="0", max_length=50)
    spi: str = Field(default="0", max_length=50)
    cpi: str = Field(default="0", max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EVMSnapshotResponse(BaseModel):
    """EVM snapshot returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    snapshot_date: str
    bac: str = "0"
    pv: str = "0"
    ev: str = "0"
    ac: str = "0"
    sv: str = "0"
    cv: str = "0"
    spi: str = "0"
    cpi: str = "0"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class EVMListResponse(BaseModel):
    """List of EVM snapshots."""

    items: list[EVMSnapshotResponse]
    total: int
