# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request and response shapes of award terms, negotiation rounds and the award gate.

Money and percentages are Decimal in, decimal strings out (pydantic emits a
Decimal as a JSON string).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.decimal_types import finite_decimal

Money = finite_decimal(18, 2, non_negative=True)
Percent = finite_decimal(7, 4, non_negative=True)
PricingMode = Literal["unit_price", "lump_sum"]


class AwardTermsIn(BaseModel):
    """The terms an estimator agrees with the winning firm."""

    model_config = ConfigDict(str_strip_whitespace=True)

    bid_id: UUID
    round_id: UUID | None = None
    discount_percent: Percent = Field(default=Decimal("0"), le=100)
    lump_sum: Money | None = None
    retention_percent: Percent | None = Field(default=None, le=100)
    retention_cap_percent: Percent | None = Field(default=None, le=100)
    payment_discount_percent: Percent | None = Field(default=None, le=100)
    payment_discount_days: int | None = Field(default=None, ge=0, le=365)
    note: str = Field(default="", max_length=5000)


class RoundIn(BaseModel):
    """A negotiated offer of one bidder."""

    model_config = ConfigDict(str_strip_whitespace=True)

    pricing_mode: PricingMode = "unit_price"
    lump_sum: Money | None = None
    discount_percent: Percent = Field(default=Decimal("0"), le=100)
    note: str = Field(default="", max_length=5000)


class RoundOut(BaseModel):
    """A negotiation round as the award panel shows it."""

    id: UUID
    package_id: UUID
    bid_id: UUID
    round_no: int
    pricing_mode: str
    lines_total: Decimal
    lump_sum: Decimal | None = None
    discount_percent: Decimal
    offer_total: Decimal
    contract_sum: Decimal
    note: str = ""
    is_final: bool = False
    approved_by: str | None = None
    approved_at: datetime | None = None
    created_at: datetime | None = None


class GateFinding(BaseModel):
    """One reason a firm may not be invited or awarded, or a warning about it."""

    rule_id: str
    severity: Literal["error", "warning"]
    code: str
    document_type: str | None = None
    state: str | None = None
    lapsed_on: date | None = None


class BidderGate(BaseModel):
    """What the directory says about a firm, judged against the certificates the project's pack asks for."""

    subcontractor_id: UUID | None = None
    subcontractor_name: str | None = None
    blocked: bool = False
    required_types: list[str] = Field(default_factory=list)
    requirements_source: str = "fallback"
    requirements_reference: str | None = None
    findings: list[GateFinding] = Field(default_factory=list)


class AwardLineOut(BaseModel):
    """One contract line the award would draft."""

    index: int
    description: str = ""
    unit: str = ""
    quantity: Decimal
    offer_rate: Decimal
    offer_total: Decimal
    contract_rate: Decimal
    contract_total: Decimal


class RuleOut(BaseModel):
    """A failed award rule."""

    rule_id: str
    severity: str
    message: str
    element_ref: str | None = None
    suggestion: str | None = None


class AwardPreview(BaseModel):
    """The award an estimator is about to make, recomputed from the terms."""

    package_id: UUID
    bid_id: UUID
    company_name: str = ""
    currency: str = ""
    pricing_mode: str
    contract_type: str
    lines_total: Decimal
    offer_total: Decimal
    discount_percent: Decimal
    discount_amount: Decimal
    contract_sum: Decimal
    lump_sum_source: str | None = None
    retention_percent: Decimal | None = None
    retention_cap_percent: Decimal | None = None
    retention_cap_amount: Decimal | None = None
    payment_discount_percent: Decimal | None = None
    payment_discount_days: int | None = None
    round_id: UUID | None = None
    round_no: int | None = None
    rounds_count: int = 0
    revisions_count: int = 0
    lines: list[AwardLineOut] = Field(default_factory=list)
    gate: BidderGate = Field(default_factory=BidderGate)
    blockers: list[RuleOut] = Field(default_factory=list)
    warnings: list[RuleOut] = Field(default_factory=list)
    can_award: bool = True


class AwardTermsOut(BaseModel):
    """Stored terms with the preview they produce, and the drafted contract's check once awarded."""

    package_id: UUID
    package_status: str
    terms: AwardTermsIn | None = None
    preview: AwardPreview | None = None
    contract_id: UUID | None = None
    contract_code: str | None = None


class RoundListResponse(BaseModel):
    """Negotiation rounds of a package."""

    items: list[RoundOut]
    total: int
    offset: int = 0
    limit: int = 50
