"""Finance Pydantic schemas — request/response models."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_non_negative_decimal(v: str, field_name: str = "value") -> str:
    """Validate that a string is a valid non-negative decimal number."""
    try:
        d = Decimal(v)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid decimal value for {field_name}: {v!r}") from exc
    if d < 0:
        raise ValueError(f"{field_name} must be non-negative, got {v!r}")
    return v


def _validate_decimal(v: str, field_name: str = "value") -> str:
    """Validate that a string is a valid decimal number (allows negative for EVM)."""
    try:
        Decimal(v)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid decimal value for {field_name}: {v!r}") from exc
    return v


def _validate_positive_decimal(v: str, field_name: str = "value") -> str:
    """Validate that a string is a valid positive decimal number (> 0)."""
    try:
        d = Decimal(v)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid decimal value for {field_name}: {v!r}") from exc
    if d <= 0:
        raise ValueError(f"{field_name} must be positive, got {v!r}")
    return v

# ── Invoice ──────────────────────────────────────────────────────────────────


class InvoiceLineItemCreate(BaseModel):
    """Create a line item within an invoice."""

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


class InvoiceCreate(BaseModel):
    """Create a new invoice."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    contact_id: str | None = Field(default=None, max_length=36)
    invoice_direction: str = Field(
        ...,
        pattern=r"^(payable|receivable)$",
        examples=["payable"],
    )
    invoice_number: str | None = Field(
        default=None, max_length=50, examples=["INV-2026-0042"]
    )
    invoice_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20, examples=["2026-04-01"])
    due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20, examples=["2026-05-01"])
    currency_code: str = Field(default="EUR", max_length=10, examples=["EUR"])
    amount_subtotal: str = Field(default="0", max_length=50, examples=["50000.00"])
    tax_amount: str = Field(default="0", max_length=50, examples=["9500.00"])
    retention_amount: str = Field(default="0", max_length=50, examples=["2500.00"])
    amount_total: str = Field(default="0", max_length=50, examples=["57000.00"])
    tax_config_id: str | None = Field(default=None, max_length=36)
    status: str = Field(default="draft", max_length=50)
    payment_terms_days: str | None = Field(default=None, max_length=10)
    notes: str | None = Field(default=None, max_length=5000)
    line_items: list[InvoiceLineItemCreate] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("amount_subtotal", "tax_amount", "retention_amount", "amount_total")
    @classmethod
    def _check_non_negative_decimal(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)


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
    notes: str | None = Field(default=None, max_length=5000)
    line_items: list[InvoiceLineItemCreate] | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("amount_subtotal", "tax_amount", "retention_amount", "amount_total")
    @classmethod
    def _check_non_negative_decimal(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_non_negative_decimal(v)


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
    payment_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    amount: str = Field(..., max_length=50)
    currency_code: str = Field(default="EUR", max_length=10)
    exchange_rate_snapshot: str = Field(default="1", max_length=50)
    reference: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("amount")
    @classmethod
    def _check_positive_amount(cls, v: str) -> str:
        return _validate_positive_decimal(v, "amount")

    @field_validator("exchange_rate_snapshot")
    @classmethod
    def _check_positive_rate(cls, v: str) -> str:
        return _validate_positive_decimal(v, "exchange_rate_snapshot")


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

    @field_validator(
        "original_budget", "revised_budget", "committed", "actual", "forecast_final",
    )
    @classmethod
    def _check_non_negative_decimal(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)


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

    @field_validator(
        "original_budget", "revised_budget", "committed", "actual", "forecast_final",
    )
    @classmethod
    def _check_non_negative_decimal(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_non_negative_decimal(v)


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
    variance: str = "0"
    consumed_pct: float = 0.0
    warning_level: str = "normal"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    def model_post_init(self, __context: Any) -> None:
        """Compute variance, consumed_pct, and warning_level after deserialization."""
        try:
            revised = float(self.revised_budget)
            actual = float(self.actual)
            self.variance = str(revised - actual)
            if revised > 0:
                self.consumed_pct = round(actual / revised * 100, 1)
            else:
                self.consumed_pct = 0.0
            if self.consumed_pct >= 95:
                self.warning_level = "critical"
            elif self.consumed_pct >= 80:
                self.warning_level = "caution"
            else:
                self.warning_level = "normal"
        except (ValueError, TypeError):
            self.variance = "0"
            self.consumed_pct = 0.0
            self.warning_level = "normal"


class BudgetListResponse(BaseModel):
    """Paginated list of budgets."""

    items: list[BudgetResponse]
    total: int


# ── EVM ──────────────────────────────────────────────────────────────────────


class EVMSnapshotCreate(BaseModel):
    """Create an EVM snapshot."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    snapshot_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    bac: str = Field(default="0", max_length=50)
    pv: str = Field(default="0", max_length=50)
    ev: str = Field(default="0", max_length=50)
    ac: str = Field(default="0", max_length=50)
    sv: str = Field(default="0", max_length=50)
    cv: str = Field(default="0", max_length=50)
    spi: str = Field(default="0", max_length=50)
    cpi: str = Field(default="0", max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("bac", "pv", "ev", "ac")
    @classmethod
    def _check_non_negative_decimal(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)

    @field_validator("sv", "cv", "spi", "cpi")
    @classmethod
    def _check_decimal(cls, v: str) -> str:
        return _validate_decimal(v)


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
    # Forecast metrics (EVM standard)
    eac: str = "0"
    vac: str = "0"
    etc: str = "0"
    tcpi: str = "0"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class EVMListResponse(BaseModel):
    """List of EVM snapshots."""

    items: list[EVMSnapshotResponse]
    total: int


# ── Finance Dashboard ───────────────────────────────────────────────────────


class FinanceDashboardResponse(BaseModel):
    """Aggregated finance KPIs for a project or across all projects."""

    total_payable: float = 0.0
    total_receivable: float = 0.0
    total_overdue: float = 0.0
    overdue_count: int = 0
    invoices_draft: int = 0
    invoices_pending: int = 0
    invoices_approved: int = 0
    invoices_paid: int = 0
    total_budget_original: float = 0.0
    total_budget_revised: float = 0.0
    total_committed: float = 0.0
    total_actual: float = 0.0
    total_variance: float = 0.0
    budget_consumed_pct: float = 0.0
    budget_warning_level: str = "normal"  # "normal" | "caution" | "critical"
    total_payments: float = 0.0
    cash_flow_net: float = 0.0
