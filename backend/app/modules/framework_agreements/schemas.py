# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Framework agreement request and response schemas. Money travels as decimal strings."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

_METHODS = "^(none|index_ratio|formula|fixed_table)$"
_KINDS = "^(multiplier|add_per_unit|add_lump)$"
_SCOPES = "^(all|flagged|items|group)$"


class _Money(BaseModel):
    """Serialise every Decimal field as a plain string."""

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", when_used="json")
    def _dec(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            return format(value, "f")
        return value


class Page[T](BaseModel):
    """A child list of one agreement or order, read whole: ``total`` equals ``len(items)``."""

    items: list[T]
    total: int
    offset: int = 0
    limit: int = 0


# ── Price list ──────────────────────────────────────────────────────────────


class RateItemIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=80)
    description: str = Field(default="", max_length=5000)
    unit: str = Field(default="", max_length=20)
    base_rate: Decimal = Field(..., ge=0)
    classification: str | None = Field(default=None, max_length=80)
    max_qty: Decimal | None = Field(default=None, ge=0)
    estimated_qty: Decimal | None = Field(default=None, ge=0)
    surcharge_flags: list[str] = Field(default_factory=list, max_length=20)
    escalation_group: str | None = Field(default=None, max_length=40)
    is_active: bool = True
    source: str = Field(default="manual", pattern="^(gaeb|excel|manual)$")


class RateItemUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=5000)
    unit: str | None = Field(default=None, max_length=20)
    base_rate: Decimal | None = Field(default=None, ge=0)
    max_qty: Decimal | None = Field(default=None, ge=0)
    estimated_qty: Decimal | None = Field(default=None, ge=0)
    surcharge_flags: list[str] | None = None
    escalation_group: str | None = Field(default=None, max_length=40)
    is_active: bool | None = None


class RateItemOut(_Money):
    id: uuid.UUID
    code: str
    description: str
    unit: str
    base_rate: Decimal
    effective_rate: Decimal | None = None
    classification: str | None = None
    max_qty: Decimal | None = None
    estimated_qty: Decimal | None = None
    ordered_qty: Decimal = Decimal("0")
    surcharge_flags: list[str] = Field(default_factory=list)
    escalation_group: str | None = None
    is_active: bool
    cited: bool = False
    source: str


class ImportItemsRequest(BaseModel):
    items: list[RateItemIn] = Field(..., min_length=1, max_length=5000)
    replace: bool = False


# ── Rate periods and adjustments ────────────────────────────────────────────


class RatePeriodIn(BaseModel):
    label: str = Field(default="", max_length=80)
    effective_from: date
    effective_to: date | None = None
    method: str = Field(default="none", pattern=_METHODS)
    template_code: str | None = Field(default=None, max_length=40)
    base_period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    fixed_price_until: date | None = None
    fixed_part: Decimal | None = Field(default=None, ge=0, le=1)
    fixed_factor: Decimal | None = Field(default=None, gt=0)
    series_refs: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    rate_overrides: dict[str, Decimal] = Field(default_factory=dict)


class RatePeriodOut(_Money):
    id: uuid.UUID
    label: str
    effective_from: date
    effective_to: date | None = None
    method: str
    template_code: str | None = None
    base_period: str | None = None
    fixed_price_until: date | None = None
    fixed_part: Decimal | None = None
    fixed_factor: Decimal | None = None
    series_refs: list[dict[str, Any]] = Field(default_factory=list)
    rate_overrides: dict[str, Any] = Field(default_factory=dict)
    status: str
    factor_today: Decimal | None = None
    factor_error: str | None = None


class AdjustmentIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=40)
    label: str = Field(default="", max_length=255)
    kind: str = Field(default="multiplier", pattern=_KINDS)
    value: Decimal
    scope: str = Field(default="all", pattern=_SCOPES)
    scope_items: list[str] = Field(default_factory=list)
    scope_group: str | None = Field(default=None, max_length=40)
    condition: str = Field(default="", max_length=60)


class AdjustmentOut(_Money):
    id: uuid.UUID
    code: str
    label: str
    kind: str
    value: Decimal
    scope: str
    scope_items: list[str] = Field(default_factory=list)
    scope_group: str | None = None
    condition: str


# ── Agreement ───────────────────────────────────────────────────────────────


class AgreementCreate(BaseModel):
    project_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=500)
    code: str | None = Field(default=None, max_length=80)
    client_id: uuid.UUID | None = None
    client_name: str = Field(default="", max_length=255)
    start_date: date
    end_date: date
    currency: str = Field(default="", max_length=3)
    cap_value: Decimal | None = Field(default=None, ge=0)
    min_value: Decimal | None = Field(default=None, ge=0)
    estimated_value: Decimal | None = Field(default=None, ge=0)
    cap_basis: str = Field(default="committed", pattern="^(committed|certified|invoiced)$")
    threshold_pct: Decimal = Field(default=Decimal("80"), gt=0, le=100)
    rounding: str = Field(default="per_rate", pattern="^(per_rate|per_total)$")
    override_policy: str = Field(default="block", pattern="^(block|warn)$")
    numbering_pattern: str = Field(default="{agreement}-{yyyy}-{seq4}", max_length=80)
    client_kind: str = Field(default="classic", pattern="^(classic|sector)$")
    escalation_method: str = Field(default="none", pattern=_METHODS)
    pack_values: dict[str, Any] = Field(default_factory=dict)
    items: list[RateItemIn] = Field(default_factory=list, max_length=5000)


class AgreementUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    client_name: str | None = Field(default=None, max_length=255)
    start_date: date | None = None
    end_date: date | None = None
    cap_value: Decimal | None = Field(default=None, ge=0)
    min_value: Decimal | None = Field(default=None, ge=0)
    estimated_value: Decimal | None = Field(default=None, ge=0)
    cap_basis: str | None = Field(default=None, pattern="^(committed|certified|invoiced)$")
    threshold_pct: Decimal | None = Field(default=None, gt=0, le=100)
    rounding: str | None = Field(default=None, pattern="^(per_rate|per_total)$")
    override_policy: str | None = Field(default=None, pattern="^(block|warn)$")
    client_kind: str | None = Field(default=None, pattern="^(classic|sector)$")
    pack_values: dict[str, Any] | None = None


class Consumption(_Money):
    cap: Decimal | None = None
    min_value: Decimal | None = None
    committed: Decimal = Decimal("0")
    certified: Decimal = Decimal("0")
    invoiced: Decimal = Decimal("0")
    tested: Decimal = Decimal("0")
    headroom: Decimal | None = None
    pct: Decimal | None = None
    threshold_pct: Decimal = Decimal("80")
    cap_basis: str = "committed"
    term_elapsed_pct: Decimal | None = None
    orders: int = 0


class Finding(BaseModel):
    rule_id: str
    code: str
    severity: str
    message: str
    suggestion: str | None = None
    element_ref: str | None = None


class AgreementSummary(_Money):
    id: uuid.UUID
    project_id: uuid.UUID
    code: str
    title: str
    client_name: str
    status: str
    currency: str
    start_date: str | None = None
    end_date: str | None = None
    consumption: Consumption
    orders_this_month: int = 0


class AgreementListResponse(_Money):
    items: list[AgreementSummary]
    total: int


class AgreementDetail(AgreementSummary):
    terms: dict[str, Any] = Field(default_factory=dict)
    pack: dict[str, Any] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)
    current_period: RatePeriodOut | None = None


# ── Orders ──────────────────────────────────────────────────────────────────


class OrderLineIn(BaseModel):
    item_id: uuid.UUID | None = None
    code: str | None = Field(default=None, max_length=80)
    quantity: Decimal = Field(..., gt=0)


class OrderQuoteRequest(BaseModel):
    ordered_at: date
    tags: list[str] = Field(default_factory=list, max_length=20)
    currency: str | None = Field(default=None, max_length=3)
    lines: list[OrderLineIn] = Field(default_factory=list, max_length=2000)
    exclude_order_id: uuid.UUID | None = None


class OrderCreate(OrderQuoteRequest):
    site_label: str = Field(default="", max_length=255)
    site_project_id: uuid.UUID | None = None
    own_site_project: bool = False
    requested_start: date | None = None
    requested_finish: date | None = None
    issue: bool = False
    override_reason: str | None = Field(default=None, max_length=2000)
    pack_values: dict[str, Any] = Field(default_factory=dict)


class PricedLineOut(_Money):
    item_id: uuid.UUID | None = None
    code: str
    description: str = ""
    unit: str = ""
    quantity: Decimal
    unit_rate: Decimal
    total: Decimal
    rate_build: dict[str, Any] = Field(default_factory=dict)


class OrderQuote(_Money):
    lines: list[PricedLineOut]
    net: Decimal
    factor: Decimal | None = None
    period_label: str | None = None
    rounding: str
    cap: dict[str, Any] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)
    blocking: bool = False
    over_cap: bool = False
    per_rate_net: Decimal | None = None
    per_total_net: Decimal | None = None


class OrderLineOut(_Money):
    id: uuid.UUID
    code: str
    description: str
    unit: str | None = None
    quantity: Decimal
    unit_rate: Decimal
    total_value: Decimal
    origin: str
    measured_qty: Decimal | None = None
    rate_build: dict[str, Any] = Field(default_factory=dict)


class OrderSummary(_Money):
    id: uuid.UUID
    code: str
    order_no: str
    site_label: str = ""
    project_id: uuid.UUID
    ordered_at: str | None = None
    tags: list[str] = Field(default_factory=list)
    order_status: str
    line_count: int = 0
    net: Decimal = Decimal("0")
    extras: Decimal = Decimal("0")
    measured_pct: Decimal | None = None
    claimed: Decimal = Decimal("0")
    has_extras: bool = False
    measured_over_ordered: bool = False


class OrderListResponse(_Money):
    items: list[OrderSummary]
    total: int


class OrderDetail(OrderSummary):
    lines: list[OrderLineOut] = Field(default_factory=list)
    terms: dict[str, Any] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)


class OrderIssueRequest(BaseModel):
    override_reason: str | None = Field(default=None, max_length=2000)


class OrderStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(in_progress|closed|cancelled)$")


class MeasurementIn(BaseModel):
    measurements: dict[str, Decimal] = Field(..., description="order line id -> measured quantity to date")


class BreakdownRow(_Money):
    key: str
    label: str
    orders: int
    committed: Decimal
    certified: Decimal = Decimal("0")
    quantity: Decimal | None = None
    max_qty: Decimal | None = None


class BreakdownResponse(_Money):
    by: str
    rows: list[BreakdownRow]
