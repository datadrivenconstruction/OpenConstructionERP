# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CVR Pydantic schemas - request/response models.

Money contract (matches costs/schemas.py): every monetary value is a
``decimal.Decimal`` in Python and on the database (``NUMERIC(18, 4)``), and is
emitted on the wire as a plain decimal *string* through :data:`DecimalMoney` so
a large total round-trips without JSON's float bridge silently rounding it.
Inputs accept any JSON number or numeric string - Pydantic v2 promotes them to
``Decimal`` and ``ge=0`` rejects a negative. Money is never a float.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, model_validator

from app.modules.cvr.compute import q2, to_decimal
from app.modules.cvr.validators import forecast_flags

# Money / percentage fields are exchanged as strings on the wire (mirrors the
# ``DecimalMoney`` alias in costs/schemas.py) so a precision-critical value never
# rides through a JSON float. The Decimal is quantized to 2dp before it reaches
# here, so ``str(v)`` is already the canonical amount.
DecimalMoney = Annotated[
    Decimal,
    PlainSerializer(lambda v: str(v) if v is not None else None, return_type=str),
]

_PERIOD_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"  # YYYY-MM
_REPORT_STATUS_PATTERN = r"^(draft|final)$"
_PAYAPP_STATUS_PATTERN = r"^(draft|submitted|certified|paid)$"


# ── Report ───────────────────────────────────────────────────────────────────


class CvrReportCreate(BaseModel):
    """Create a new CVR report."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    period: str = Field(..., pattern=_PERIOD_PATTERN, examples=["2026-06"])
    title: str | None = Field(default=None, max_length=255)
    status: str = Field(default="draft", pattern=_REPORT_STATUS_PATTERN)
    currency: str = Field(default="", max_length=3, examples=["USD", "EUR", "GBP"])
    notes: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CvrReportUpdate(BaseModel):
    """Partial update for a CVR report."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, pattern=_REPORT_STATUS_PATTERN)
    currency: str | None = Field(default=None, max_length=3)
    notes: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] | None = None


class CvrReportResponse(BaseModel):
    """CVR report returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    period: str
    title: str | None = None
    status: str = "draft"
    currency: str = ""
    notes: str | None = None
    line_count: int = 0
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class CvrReportListResponse(BaseModel):
    """Paginated list of CVR reports."""

    items: list[CvrReportResponse]
    total: int


# ── Line ─────────────────────────────────────────────────────────────────────


class CvrLineCreate(BaseModel):
    """Create a cost head within a CVR report.

    ``currency`` is optional and never stored - it is the single-currency guard:
    when supplied it must equal the report's currency (the service raises 400
    otherwise). Omit it to inherit the report currency.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    cost_code: str = Field(default="", max_length=100)
    wbs_id: UUID | None = None
    description: str = Field(default="", max_length=500)
    cost_to_date: DecimalMoney = Field(default=Decimal("0"), ge=0)
    value_to_date: DecimalMoney = Field(default=Decimal("0"), ge=0)
    accruals: DecimalMoney = Field(default=Decimal("0"), ge=0)
    forecast_cost: DecimalMoney = Field(default=Decimal("0"), ge=0)
    forecast_value: DecimalMoney = Field(default=Decimal("0"), ge=0)
    sort_order: int = Field(default=0, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CvrLineUpdate(BaseModel):
    """Partial update for a CVR line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cost_code: str | None = Field(default=None, max_length=100)
    wbs_id: UUID | None = None
    description: str | None = Field(default=None, max_length=500)
    cost_to_date: DecimalMoney | None = Field(default=None, ge=0)
    value_to_date: DecimalMoney | None = Field(default=None, ge=0)
    accruals: DecimalMoney | None = Field(default=None, ge=0)
    forecast_cost: DecimalMoney | None = Field(default=None, ge=0)
    forecast_value: DecimalMoney | None = Field(default=None, ge=0)
    sort_order: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    metadata: dict[str, Any] | None = None


class CvrLineResponse(BaseModel):
    """CVR line returned from the API, with derived margin + advisory flags."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    report_id: UUID
    cost_code: str = ""
    wbs_id: UUID | None = None
    description: str = ""
    cost_to_date: DecimalMoney = Decimal("0")
    value_to_date: DecimalMoney = Decimal("0")
    accruals: DecimalMoney = Decimal("0")
    forecast_cost: DecimalMoney = Decimal("0")
    forecast_value: DecimalMoney = Decimal("0")
    sort_order: int = 0
    # Derived (computed in model_post_init from the money fields above):
    margin_to_date: DecimalMoney = Decimal("0")
    forecast_margin: DecimalMoney = Decimal("0")
    flags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    def model_post_init(self, __context: Any) -> None:
        """Derive margin_to_date, forecast_margin and advisory flags."""
        cost = to_decimal(self.cost_to_date)
        value = to_decimal(self.value_to_date)
        fcost = to_decimal(self.forecast_cost)
        fvalue = to_decimal(self.forecast_value)
        self.margin_to_date = q2(value - cost)
        self.forecast_margin = q2(fvalue - fcost)
        self.flags = forecast_flags(
            cost_to_date=cost,
            value_to_date=value,
            forecast_cost=fcost,
            forecast_value=fvalue,
        )


# ── Report summary ───────────────────────────────────────────────────────────


class CvrSummaryResponse(BaseModel):
    """Roll-up totals + margins for a report.

    Every money field and both percentages are ``DecimalMoney`` so the whole
    summary is uniformly Decimal-as-string on the wire and the frontend never
    has to guess a type.
    """

    report_id: UUID
    project_id: UUID
    period: str
    status: str = "draft"
    currency: str = ""
    line_count: int = 0
    total_cost_to_date: DecimalMoney = Decimal("0")
    total_value_to_date: DecimalMoney = Decimal("0")
    total_accruals: DecimalMoney = Decimal("0")
    total_forecast_cost: DecimalMoney = Decimal("0")
    total_forecast_value: DecimalMoney = Decimal("0")
    margin_to_date: DecimalMoney = Decimal("0")
    forecast_margin: DecimalMoney = Decimal("0")
    margin_to_date_pct: DecimalMoney = Decimal("0")
    forecast_margin_pct: DecimalMoney = Decimal("0")
    warnings: list[str] = Field(default_factory=list)


# ── Cashflow point ───────────────────────────────────────────────────────────


class CashflowPointCreate(BaseModel):
    """Create a cash-in / cash-out point for a project period."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    period: str = Field(..., pattern=_PERIOD_PATTERN, examples=["2026-06"])
    cash_in: DecimalMoney = Field(default=Decimal("0"), ge=0)
    cash_out: DecimalMoney = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=3)
    label: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CashflowPointUpdate(BaseModel):
    """Partial update for a cashflow point."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cash_in: DecimalMoney | None = Field(default=None, ge=0)
    cash_out: DecimalMoney | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    label: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] | None = None


class CashflowPointResponse(BaseModel):
    """Cashflow point returned from the API (net is derived)."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    period: str
    cash_in: DecimalMoney = Decimal("0")
    cash_out: DecimalMoney = Decimal("0")
    net: DecimalMoney = Decimal("0")
    currency: str = ""
    label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    def model_post_init(self, __context: Any) -> None:
        """Derive per-period net = cash_in - cash_out."""
        self.net = q2(to_decimal(self.cash_in) - to_decimal(self.cash_out))


class CashflowSeriesEntry(BaseModel):
    """One period on the cumulative cashflow S-curve (all money as strings)."""

    period: str
    cash_in: DecimalMoney = Decimal("0")
    cash_out: DecimalMoney = Decimal("0")
    net: DecimalMoney = Decimal("0")
    cumulative_cash_in: DecimalMoney = Decimal("0")
    cumulative_cash_out: DecimalMoney = Decimal("0")
    cumulative_net: DecimalMoney = Decimal("0")


class CashflowSeriesResponse(BaseModel):
    """Cumulative cashflow series for a project."""

    project_id: UUID
    currency: str = ""
    points: list[CashflowSeriesEntry] = Field(default_factory=list)
    total_cash_in: DecimalMoney = Decimal("0")
    total_cash_out: DecimalMoney = Decimal("0")
    net_position: DecimalMoney = Decimal("0")


# ── Payment application ──────────────────────────────────────────────────────


class PaymentApplicationCreate(BaseModel):
    """Create an interim payment application (IPA).

    ``net_value`` is not accepted - it is always derived as
    ``gross_value - retention`` by the service so the figures cannot drift.

    ``progress_claim_id`` raises the application from a contract progress
    claim of the same project. The claim then fills every figure the caller
    left unset: period (from the claim's period end), number, gross,
    retention and currency. ``period`` is required only without a claim.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    period: str | None = Field(default=None, pattern=_PERIOD_PATTERN, examples=["2026-06"])
    progress_claim_id: UUID | None = None
    application_number: str | None = Field(default=None, max_length=50, examples=["IPA-001"])
    gross_value: DecimalMoney = Field(default=Decimal("0"), ge=0)
    retention: DecimalMoney = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=3)
    status: str = Field(default="draft", pattern=_PAYAPP_STATUS_PATTERN)
    notes: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _period_or_claim(self) -> "PaymentApplicationCreate":
        if not self.period and self.progress_claim_id is None:
            raise ValueError("period is required unless the application is raised from a progress claim")
        return self


class PaymentApplicationUpdate(BaseModel):
    """Partial update for a payment application."""

    model_config = ConfigDict(str_strip_whitespace=True)

    application_number: str | None = Field(default=None, max_length=50)
    gross_value: DecimalMoney | None = Field(default=None, ge=0)
    retention: DecimalMoney | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    status: str | None = Field(default=None, pattern=_PAYAPP_STATUS_PATTERN)
    notes: str | None = Field(default=None, max_length=5000)
    # Link to (or, with an explicit null, unlink from) a progress claim of the
    # same project. Linking on update never rewrites the figures.
    progress_claim_id: UUID | None = None
    metadata: dict[str, Any] | None = None


class PaymentApplicationResponse(BaseModel):
    """Payment application returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    period: str
    application_number: str | None = None
    gross_value: DecimalMoney = Decimal("0")
    retention: DecimalMoney = Decimal("0")
    net_value: DecimalMoney = Decimal("0")
    currency: str = ""
    status: str = "draft"
    notes: str | None = None
    progress_claim_id: UUID | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class PaymentApplicationListResponse(BaseModel):
    """Paginated list of payment applications."""

    items: list[PaymentApplicationResponse]
    total: int


class ProgressClaimOption(BaseModel):
    """One contract progress claim offered by the payment application picker."""

    id: UUID
    contract_id: UUID
    contract_code: str = ""
    claim_number: str = ""
    status: str = ""
    period: str | None = None
    gross_amount: DecimalMoney = Decimal("0")
    retention_amount: DecimalMoney = Decimal("0")
    net_due: DecimalMoney = Decimal("0")
    currency: str = ""


class ProgressClaimOptionListResponse(BaseModel):
    """Every progress claim the picker can offer, plus how many there are.

    Not paged: the picker has to see every claim on the project, so ``total``
    equals the length of ``items``. It is there so a reader can tell the whole
    set from a part of it. Declared after :class:`ProgressClaimOption` because
    ``from __future__ import annotations`` makes the field a string.
    """

    items: list[ProgressClaimOption]
    total: int
