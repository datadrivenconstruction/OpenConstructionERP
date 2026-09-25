# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Finance Pydantic schemas - request/response models."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.modules.einvoice.rules import VAT_CATEGORY_CODES
from app.modules.finance.variance import expected_outturn


# ── v3 §10 money serialisation helper ─────────────────────────────────────
# Mirrors backend/app/modules/boq/schemas.py - money fields are stored /
# accepted as Decimal but emitted as plain decimal strings in JSON.
def _serialise_money(v: Decimal | None) -> str | None:
    if v is None:
        return None
    if not isinstance(v, Decimal):
        try:
            v = Decimal(str(v))
        except (InvalidOperation, ValueError):
            return "0"
    if not v.is_finite():
        return "0"
    return format(v, "f")


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


def _decimal_to_str(v: object) -> object:
    """Response-side coercion: turn ORM ``Decimal`` values into canonical strings.

    Phase 2e: models that previously stored numerics as ``VARCHAR`` now
    use :class:`MoneyType` and surface :class:`Decimal` on the ORM
    attribute. The API contract still ships strings on the wire, so we
    normalise in a ``mode="before"`` validator. Non-Decimal inputs
    pass through untouched so hand-built payloads (tests, internal
    dict conversions) keep working.
    """
    if isinstance(v, Decimal):
        return format(v, "f")
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
    # Gap B (Wave 6): optional link to a costmodel.CostLine so the paid actual
    # posts onto the matching cost-spine budget row.
    cost_line_id: UUID | None = Field(default=None)
    # The same link said the way the person entering a supplier invoice knows
    # it (Issue #454). Nobody typing an invoice thinks in cost lines; they think
    # in the bill item the work was for. The service resolves this to the
    # position's own cost line and stores that, so there is still exactly one
    # link on the row and only one way for the money to roll up. Naming a
    # position that is not on the cost spine is refused rather than dropped -
    # a line that silently posted nowhere is the failure this whole field
    # exists to remove.
    boq_position_id: UUID | None = Field(default=None)
    sort_order: int = Field(default=0, ge=0)
    # EN 16931 per-line VAT. Left unset the exporter falls back to the
    # invoice-level rate, which is only right when every line shares one rate.
    vat_rate: str | None = Field(default=None, max_length=10)
    vat_category: str | None = Field(default=None, max_length=4)

    @field_validator("quantity", "unit_rate", "amount")
    @classmethod
    def _check_non_negative_decimal(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)

    @field_validator("vat_rate")
    @classmethod
    def _check_vat_rate(cls, v: str | None) -> str | None:
        return None if v is None else _validate_non_negative_decimal(v)

    @field_validator("vat_category")
    @classmethod
    def _check_vat_category(cls, v: str | None) -> str | None:
        """Reject a category code no receiver's validator would accept (BR-CL-18)."""
        if v is None:
            return None
        code = v.strip().upper()
        if code not in VAT_CATEGORY_CODES:
            raise ValueError(f"vat_category must be one of {', '.join(sorted(VAT_CATEGORY_CODES))}, got {v!r}")
        return code


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
    invoice_number: str | None = Field(default=None, max_length=50, examples=["INV-2026-0042"])
    # Phase 2.5: invoice_date may be empty when an invoice is being drafted
    # (TBD) - seeded data and frontend drafts both produce "". Validate format
    # only when a value is supplied. (BUG-FINANCE01)
    invoice_date: str = Field(
        default="",
        pattern=r"^(\d{4}-\d{2}-\d{2})?$",
        max_length=20,
        examples=["2026-04-01"],
    )
    due_date: str | None = Field(
        default=None,
        pattern=r"^(\d{4}-\d{2}-\d{2})?$",
        max_length=20,
        examples=["2026-05-01"],
    )
    currency_code: str = Field(default="", max_length=10, examples=["USD", "EUR", "GBP", "BRL"])
    amount_subtotal: str = Field(default="0", max_length=50, examples=["50000.00"])
    tax_amount: str = Field(default="0", max_length=50, examples=["9500.00"])
    retention_amount: str = Field(default="0", max_length=50, examples=["2500.00"])
    amount_total: str = Field(default="0", max_length=50, examples=["57000.00"])
    tax_config_id: str | None = Field(default=None, max_length=36)
    status: str = Field(default="draft", max_length=50)
    payment_terms_days: str | None = Field(default=None, max_length=10)
    notes: str | None = Field(default=None, max_length=5000)
    # The purchase order a supplier invoice bills against. Payable only; the
    # order must be on the same project and, when both name one, with the same
    # supplier. Optional: most small payables have no order behind them.
    purchase_order_id: UUID | None = None
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
    # Mirror InvoiceCreate.due_date so a PATCH cannot store a malformed (or
    # blank) due date that later reads as a phantom overdue in the dashboard
    # KPI. The pattern requires a real ISO date when a value is supplied.
    due_date: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        max_length=20,
    )
    currency_code: str | None = Field(default=None, max_length=10)
    amount_subtotal: str | None = Field(default=None, max_length=50)
    tax_amount: str | None = Field(default=None, max_length=50)
    retention_amount: str | None = Field(default=None, max_length=50)
    amount_total: str | None = Field(default=None, max_length=50)
    tax_config_id: str | None = Field(default=None, max_length=36)
    status: str | None = Field(default=None, max_length=50)
    payment_terms_days: str | None = Field(default=None, max_length=10)
    notes: str | None = Field(default=None, max_length=5000)
    # Send null to unlink the invoice from its purchase order.
    purchase_order_id: UUID | None = None
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
    cost_line_id: UUID | None = None
    sort_order: int = 0
    vat_rate: str | None = None
    vat_category: str | None = None
    created_at: datetime
    updated_at: datetime

    _coerce_decimal = field_validator("quantity", "unit_rate", "amount", mode="before")(
        lambda cls, v: _decimal_to_str(v)
    )
    _coerce_vat_rate = field_validator("vat_rate", mode="before")(
        lambda cls, v: None if v is None else _decimal_to_str(v)
    )


class InvoiceResponse(BaseModel):
    """Invoice returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    contact_id: str | None = None
    counterparty_name: str | None = None
    # Gap E: link back to the certified claim this AR invoice was raised from.
    source_claim_id: UUID | None = None
    # The purchase order this supplier invoice bills against: the column, or
    # the ``metadata.po_id`` stamp an order-created invoice carried before the
    # column existed (see ``finance.po_link``).
    purchase_order_id: UUID | None = None
    invoice_direction: str
    invoice_number: str
    invoice_date: str
    due_date: str | None = None
    currency_code: str = ""
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

    _coerce_decimal = field_validator(
        "amount_subtotal",
        "tax_amount",
        "retention_amount",
        "amount_total",
        mode="before",
    )(lambda cls, v: _decimal_to_str(v))

    @model_validator(mode="after")
    def _legacy_po_stamp(self) -> "InvoiceResponse":
        if self.purchase_order_id is None:
            from app.modules.finance.po_link import invoice_po_link

            self.purchase_order_id = invoice_po_link(None, self.metadata)
        return self


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
    currency_code: str = Field(default="", max_length=10)
    exchange_rate_snapshot: str = Field(default="1", max_length=50)
    reference: str | None = Field(default=None, max_length=255)
    # R7: idempotency key - supply a stable token per payment attempt;
    # a second POST with the same key returns the existing row (no duplicate).
    idempotency_key: str | None = Field(default=None, max_length=64)
    # R7: refund flag - positive amount with is_refund=True decreases net_paid.
    is_refund: bool = Field(default=False)
    # ── Gap E (Wave 6): retainage withholding ──────────────────────────────
    # Amount of retainage held back from the certified gross at payment time.
    # ``amount`` stays the cash paid out; gross = amount + withholding_amount.
    # Defaults to "0" so ordinary (non-claim) payments are unaffected.
    withholding_amount: str = Field(default="0", max_length=50)
    # ISO date the withheld retainage becomes releasable (e.g. practical
    # completion). NULL/omitted when nothing is withheld or the date is unknown.
    withholding_release_date: str | None = Field(default=None, max_length=40)
    # Certified progress claim this payment settles, when applicable.
    source_claim_id: UUID | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("amount")
    @classmethod
    def _check_positive_amount(cls, v: str) -> str:
        return _validate_positive_decimal(v, "amount")

    @field_validator("exchange_rate_snapshot")
    @classmethod
    def _check_positive_rate(cls, v: str) -> str:
        return _validate_positive_decimal(v, "exchange_rate_snapshot")

    @field_validator("withholding_amount")
    @classmethod
    def _check_non_negative_withholding(cls, v: str) -> str:
        return _validate_non_negative_decimal(v, "withholding_amount")


class PaymentResponse(BaseModel):
    """Payment returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    invoice_id: UUID
    payment_date: str
    amount: str
    currency_code: str = ""
    exchange_rate_snapshot: str = "1"
    reference: str | None = None
    idempotency_key: str | None = None
    is_refund: bool = False
    # Gap E: retainage breakdown carried on every payment row.
    withholding_amount: str = "0"
    withholding_release_date: str | None = None
    source_claim_id: UUID | None = None
    # Enriched server-side from the parent invoice so the payments table can
    # show a human-readable reference instead of a raw invoice UUID. Resolved
    # in the router (mirrors the counterparty-name enrichment on invoices).
    invoice_number: str | None = None
    # Derived lifecycle label. Payments are immutable ledger entries created
    # when an invoice is paid, so a forward payment is "completed" and a
    # refund is "refunded". Lets the UI render a status badge without
    # inventing a column the model never stored.
    status: str = "completed"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    _coerce_decimal = field_validator("amount", "exchange_rate_snapshot", "withholding_amount", mode="before")(
        lambda cls, v: _decimal_to_str(v)
    )


class PaymentListResponse(BaseModel):
    """Paginated list of payments."""

    items: list[PaymentResponse]
    total: int


# ── Gap E: claim → receivable & withholding payment ──────────────────────────


class ClaimInvoiceRequest(BaseModel):
    """Body for ``POST /invoices/from-claim`` - turn a certified claim into AR.

    The claim itself carries the gross / retention / net figures and the
    contract carries the project + counterparty, so the caller only has to name
    the claim. The endpoint is idempotent on ``claim_id``.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    claim_id: UUID


class RecordClaimPaymentRequest(BaseModel):
    """Body for ``POST /invoices/{id}/record-payment`` with retainage.

    A thin superset of :class:`PaymentCreate` minus ``invoice_id`` (taken from
    the path). When ``withholding_amount`` is omitted it is derived from the
    invoice's ``retention_amount`` so a one-click "pay this claim" still holds
    back the right retainage.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    payment_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    # Cash actually paid out. When omitted the service pays the invoice net
    # (amount_total - retention) so the caller can settle a claim with no math.
    amount: str | None = Field(default=None, max_length=50)
    currency_code: str = Field(default="", max_length=10)
    exchange_rate_snapshot: str = Field(default="1", max_length=50)
    reference: str | None = Field(default=None, max_length=255)
    idempotency_key: str | None = Field(default=None, max_length=64)
    # When None the service derives it from the invoice retention_amount.
    withholding_amount: str | None = Field(default=None, max_length=50)
    withholding_release_date: str | None = Field(default=None, max_length=40)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("amount", "withholding_amount")
    @classmethod
    def _check_non_negative_optional(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_non_negative_decimal(v)

    @field_validator("exchange_rate_snapshot")
    @classmethod
    def _check_positive_rate(cls, v: str) -> str:
        return _validate_positive_decimal(v, "exchange_rate_snapshot")


# ── Budget ───────────────────────────────────────────────────────────────────


class BudgetCreate(BaseModel):
    """Create a project budget line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    wbs_id: str | None = Field(default=None, max_length=36)
    category: str | None = Field(default=None, max_length=100)
    currency_code: str = Field(default="", max_length=3, examples=["USD", "EUR", "GBP", "BRL"])
    original_budget: str = Field(default="0", max_length=50)
    revised_budget: str = Field(default="0", max_length=50)
    committed: str = Field(default="0", max_length=50)
    actual: str = Field(default="0", max_length=50)
    forecast_final: str = Field(default="0", max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "original_budget",
        "revised_budget",
        "committed",
        "actual",
        "forecast_final",
    )
    @classmethod
    def _check_non_negative_decimal(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)


class BudgetUpdate(BaseModel):
    """Partial update for a budget line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    wbs_id: str | None = Field(default=None, max_length=36)
    category: str | None = Field(default=None, max_length=100)
    currency_code: str | None = Field(default=None, max_length=3)
    original_budget: str | None = Field(default=None, max_length=50)
    revised_budget: str | None = Field(default=None, max_length=50)
    committed: str | None = Field(default=None, max_length=50)
    actual: str | None = Field(default=None, max_length=50)
    forecast_final: str | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None

    @field_validator(
        "original_budget",
        "revised_budget",
        "committed",
        "actual",
        "forecast_final",
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
    #: A readable name for ``wbs_id`` when it is an id: the WBS node's code and
    #: name, or the bill section's number and description. ``None`` when the
    #: id is already readable (a code such as "02") or names nothing.
    wbs_label: str | None = None
    category: str | None = None
    currency_code: str = ""
    # Phase 2d: the ORM now hands us ``Decimal`` values (see MoneyType
    # on ``ProjectBudget``). We still emit strings on the wire so the
    # API contract is unchanged. ``mode="before"`` runs the coercion
    # during ``model_validate`` so ``from_attributes`` picks it up.
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

    @field_validator(
        "original_budget",
        "revised_budget",
        "committed",
        "actual",
        "forecast_final",
        "variance",
        mode="before",
    )
    @classmethod
    def _decimal_to_str(cls, v: object) -> object:
        # ORM path (MoneyType → Decimal) and legacy string path both
        # normalise to the canonical string form.
        if isinstance(v, Decimal):
            return format(v, "f")
        return v

    def model_post_init(self, __context: Any) -> None:
        """Compute variance, consumed_pct, and warning_level after deserialization."""
        try:
            # variance is money: subtract as Decimal so the result is exact
            # rather than carrying binary-float drift in the tail. consumed_pct
            # is a ratio, so float is fine there.
            revised_money = Decimal(str(self.revised_budget))
            actual_money = Decimal(str(self.actual))
            committed_money = Decimal(str(self.committed))
            forecast_money = Decimal(str(self.forecast_final))
            # The rule lives in `variance.py` and nowhere else. It used to be
            # written once per caller, and only the caller that happened to be
            # read carefully got corrected.
            outturn = expected_outturn(
                forecast_final=forecast_money,
                committed=committed_money,
                actual=actual_money,
            )
            self.variance = format(revised_money - outturn, "f")
            revised = float(revised_money)
            # Two questions, deliberately on two bases. `consumed_pct` is the
            # bar: how much of the budget has actually left the building.
            # `warning_level` is the flag: how much of it is spoken for. The
            # flag used to sit on spend, which is how a line with 33.4 of its
            # 48.7 already on order read "normal" in green. A warning that
            # lights only once the money is gone is not a warning.
            if revised > 0:
                self.consumed_pct = round(float(actual_money) / revised * 100, 1)
                committed_pct = float(outturn) / revised * 100
            else:
                self.consumed_pct = 0.0
                committed_pct = 0.0
            if committed_pct >= 95:
                self.warning_level = "critical"
            elif committed_pct >= 80:
                self.warning_level = "caution"
            else:
                self.warning_level = "normal"
        except (ArithmeticError, ValueError, TypeError):
            # InvalidOperation is an ArithmeticError, not a ValueError, so the
            # narrower pair this used to catch let a malformed money string out
            # of the guard and turned one bad row into a 500 for the whole
            # budget list. A row we cannot read reports nothing instead.
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
    """Aggregated finance KPIs for a project or across all projects.

    v3 §10 - money fields are Decimal-as-string in JSON.
    ``cash_flow_net`` and ``budget_consumed_pct`` are not in the deferred
    list and stay float (one is a derived signed delta, the other a
    percentage ratio).
    """

    total_payable: Decimal = Decimal("0")
    total_receivable: Decimal = Decimal("0")
    total_overdue: Decimal = Decimal("0")
    overdue_count: int = 0
    invoices_draft: int = 0
    invoices_pending: int = 0
    invoices_approved: int = 0
    invoices_paid: int = 0
    total_budget_original: Decimal = Decimal("0")
    total_budget_revised: Decimal = Decimal("0")
    # The cost position, read from the records by ``finance.cost_position``
    # (its docstring states the basis of each). ``total_committed`` and
    # ``total_invoiced`` are net of VAT, like the budget above them;
    # ``total_actual`` is what has been paid, net of VAT; ``total_paid`` is
    # the same money as cash, VAT included.
    total_committed: Decimal = Decimal("0")
    total_invoiced: Decimal = Decimal("0")
    total_actual: Decimal = Decimal("0")
    total_paid: Decimal = Decimal("0")
    total_variance: Decimal = Decimal("0")
    budget_consumed_pct: float = 0.0
    budget_warning_level: str = "normal"  # "normal" | "caution" | "critical"
    total_payments: Decimal = Decimal("0")
    cash_flow_net: float = 0.0
    # Base currency the totals above are expressed in. For a project-scoped
    # dashboard this is the project's own currency and every foreign-currency
    # record has been FX-converted into it via Project.fx_rates; for a
    # cross-project rollup it is the dominant currency. Empty string when no
    # financial record carries a currency yet - the UI then renders amounts
    # without a currency symbol rather than mislabelling them (task #217).
    currency: str = ""
    # True when financial records span more than one currency. The totals are
    # still expressed in ``currency`` (converted where an FX rate exists), but
    # the UI can surface a "mixed currencies" hint so the figure isn't read as
    # a single native-currency sum.
    mixed_currencies: bool = False
    # Foreign currency codes present on records but with no FX rate configured
    # on the project. Their amounts are summed unconverted (never dropped), so
    # the UI can warn that the total is approximate until a rate is supplied.
    missing_fx_rates: list[str] = Field(default_factory=list)

    @field_serializer(
        "total_payable",
        "total_receivable",
        "total_overdue",
        "total_budget_original",
        "total_budget_revised",
        "total_committed",
        "total_invoiced",
        "total_actual",
        "total_paid",
        "total_variance",
        "total_payments",
        when_used="json",
    )
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Ledger (R7 double-entry) ──────────────────────────────────────────────


class LedgerEntryCreate(BaseModel):
    """Payload for create_ledger_transaction().

    Represents a balanced double-entry transaction - the service enforces
    debit_amount == credit_amount before writing any rows.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    transaction_ref: str = Field(..., min_length=1, max_length=100)
    debit_account: str = Field(..., min_length=1, max_length=100)
    credit_account: str = Field(..., min_length=1, max_length=100)
    debit_amount: str = Field(..., max_length=50)
    credit_amount: str = Field(..., max_length=50)
    description: str | None = Field(default=None, max_length=2000)
    currency_code: str = Field(default="", max_length=10)
    posted_at: str = Field(default="", max_length=30)
    source_type: str | None = Field(default=None, max_length=50)
    source_id: str | None = Field(default=None, max_length=36)
    created_by: str | None = Field(default=None, max_length=36)
    # Optional caller-supplied idempotency token. When omitted the service
    # derives a deterministic key from transaction_ref + source so a benign
    # retry returns the existing entry instead of double-posting the ledger.
    idempotency_key: str | None = Field(default=None, max_length=64)

    @field_validator("debit_amount", "credit_amount")
    @classmethod
    def _check_non_negative(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)


class LedgerEntryResponse(BaseModel):
    """Single ledger row returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    transaction_ref: str
    account_code: str
    description: str | None = None
    debit_amount: str = "0"
    credit_amount: str = "0"
    currency_code: str = ""
    posted_at: str
    source_type: str | None = None
    source_id: str | None = None
    is_reversal: bool = False
    reversal_of_id: UUID | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    _coerce_decimal = field_validator("debit_amount", "credit_amount", mode="before")(lambda cls, v: _decimal_to_str(v))


class LedgerTransactionResponse(BaseModel):
    """Pair of ledger rows from a balanced transaction."""

    debit: LedgerEntryResponse
    credit: LedgerEntryResponse


class LedgerListResponse(BaseModel):
    """Paginated ledger entry list."""

    items: list[LedgerEntryResponse]
    total: int


# ── GAAP: chart of accounts ───────────────────────────────────────────────


_ACCOUNT_TYPE_PATTERN = r"^(asset|liability|equity|revenue|expense)$"
_NORMAL_BALANCE_PATTERN = r"^(debit|credit)$"


class LedgerAccountCreate(BaseModel):
    """Create a chart-of-accounts account.

    ``normal_balance`` may be omitted - the service derives it from
    ``account_type`` (assets/expenses debit-normal, the rest credit-normal) and
    rejects a value that contradicts the type.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = Field(default=None)
    account_code: str = Field(..., min_length=1, max_length=100, examples=["1000"])
    name: str = Field(..., min_length=1, max_length=255, examples=["Cash and Cash Equivalents"])
    account_type: str = Field(..., pattern=_ACCOUNT_TYPE_PATTERN, examples=["asset"])
    normal_balance: str | None = Field(default=None, pattern=_NORMAL_BALANCE_PATTERN)
    parent_id: UUID | None = Field(default=None)
    statement_section: str | None = Field(default=None, max_length=50)
    is_cash: bool = Field(default=False)
    is_active: bool = Field(default=True)
    currency_code: str = Field(default="", max_length=10)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LedgerAccountUpdate(BaseModel):
    """Patch a chart-of-accounts account (code and type are immutable)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    statement_section: str | None = Field(default=None, max_length=50)
    is_cash: bool | None = Field(default=None)
    is_active: bool | None = Field(default=None)
    currency_code: str | None = Field(default=None, max_length=10)
    parent_id: UUID | None = Field(default=None)
    metadata: dict[str, Any] | None = Field(default=None)


class LedgerAccountResponse(BaseModel):
    """A chart-of-accounts row returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None = None
    account_code: str
    name: str
    account_type: str
    normal_balance: str
    parent_id: UUID | None = None
    statement_section: str | None = None
    is_cash: bool = False
    is_active: bool = True
    currency_code: str = ""
    created_at: datetime
    updated_at: datetime


class LedgerAccountListResponse(BaseModel):
    """Paginated chart-of-accounts list."""

    items: list[LedgerAccountResponse]
    total: int


# ── GAAP: journal entry (multi-line, balanced) ────────────────────────────


class JournalLineInput(BaseModel):
    """One line of a journal entry: a debit or credit against an account.

    Exactly one of ``debit`` / ``credit`` must be > 0 (the other 0). Both are
    Decimal-as-string on the wire.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    account_code: str = Field(..., min_length=1, max_length=100)
    debit: str = Field(default="0", max_length=50)
    credit: str = Field(default="0", max_length=50)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("debit", "credit")
    @classmethod
    def _check_non_negative(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)


class JournalEntryCreate(BaseModel):
    """Post a balanced journal entry of two or more lines.

    The service enforces ``sum(debit) == sum(credit)`` and a single currency
    before any row is written; an unbalanced or single-line entry is rejected.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    transaction_ref: str = Field(..., min_length=1, max_length=100)
    lines: list[JournalLineInput] = Field(..., min_length=2)
    description: str | None = Field(default=None, max_length=2000)
    currency_code: str = Field(default="", max_length=10)
    posted_at: str = Field(default="", max_length=30)
    source_type: str | None = Field(default=None, max_length=50)
    source_id: str | None = Field(default=None, max_length=36)
    # Optional caller-supplied idempotency token. When omitted the service
    # derives a deterministic key from transaction_ref + source so a replayed
    # post returns the already-written rows instead of duplicating the entry.
    idempotency_key: str | None = Field(default=None, max_length=64)


class JournalEntryResponse(BaseModel):
    """The posted ledger rows that make up a journal entry."""

    transaction_ref: str
    lines: list[LedgerEntryResponse]
    total_debits: str
    total_credits: str


# ── GAAP: trial balance + statements ──────────────────────────────────────


class TrialBalanceRow(BaseModel):
    """One account's debit/credit totals and signed balance in a trial balance."""

    account_code: str
    name: str
    account_type: str
    normal_balance: str
    debit_total: str
    credit_total: str
    balance: str


class TrialBalanceResponse(BaseModel):
    """Trial balance with the grand debit == credit tie-out check."""

    currency: str
    as_of: str | None = None
    date_from: str | None = None
    rows: list[TrialBalanceRow]
    total_debits: str
    total_credits: str
    is_balanced: bool
    out_of_balance: str


class StatementLineResponse(BaseModel):
    """One line on a financial statement (Decimal-as-string amount)."""

    code: str
    name: str
    amount: str
    account_type: str = ""
    section: str = ""


class IncomeStatementResponse(BaseModel):
    """Income statement (P&L) for a period."""

    currency: str
    date_from: str | None = None
    date_to: str | None = None
    revenue_lines: list[StatementLineResponse]
    expense_lines: list[StatementLineResponse]
    total_revenue: str
    total_expenses: str
    net_income: str


class BalanceSheetResponse(BaseModel):
    """Balance sheet as of a date with the assets = L + E tie-out check."""

    currency: str
    as_of: str | None = None
    asset_lines: list[StatementLineResponse]
    liability_lines: list[StatementLineResponse]
    equity_lines: list[StatementLineResponse]
    total_assets: str
    total_liabilities: str
    total_equity: str
    liabilities_plus_equity: str
    is_balanced: bool
    out_of_balance: str


class CashFlowResponse(BaseModel):
    """Direct-method cash flow with the bucket-sum tie-out check."""

    currency: str
    date_from: str | None = None
    date_to: str | None = None
    method: str = "direct"
    operating: str
    investing: str
    financing: str
    opening_cash: str
    net_change: str
    closing_cash: str
    ties_out: bool


# -- Retention / withholding ledger ----------------------------------------


class RetentionRollupResponse(BaseModel):
    """Held / released / outstanding retainage for one scope (group or total).

    Money is Decimal-as-string. The ``*_pct`` ratios are guarded: ``None`` when
    the denominator (held or scheduled retainage) is zero, so the UI renders
    "n/a" rather than a bogus 0%.

    Basis of each figure:
    ``scheduled`` = sum of invoice retention_amount (planned hold-back);
    ``held_to_date`` = sum of payment withholding_amount;
    ``released_to_date`` = held retainage whose release date has been reached as
    of ``as_of``; ``outstanding`` = held minus released (clamped at zero).
    """

    currency_code: str = ""
    direction: str = ""
    contact_id: str | None = None
    counterparty_name: str | None = None
    scheduled: str = "0"
    held_to_date: str = "0"
    released_to_date: str = "0"
    outstanding: str = "0"
    payment_count: int = 0
    released_pct: str | None = None
    outstanding_pct: str | None = None
    held_vs_scheduled_pct: str | None = None
    earliest_release_date: str | None = None
    latest_release_date: str | None = None


class RetentionLedgerResponse(BaseModel):
    """Project retention / withholding ledger.

    ``groups`` are per-counterparty lines (each within one currency and
    direction); ``totals`` roll them up per (currency, direction). ``as_of`` is
    the release-date cutoff used to classify retainage as released. Nothing is
    blended across currencies or across payable / receivable.
    """

    project_id: UUID
    as_of: str | None = None
    groups: list[RetentionRollupResponse] = Field(default_factory=list)
    totals: list[RetentionRollupResponse] = Field(default_factory=list)
