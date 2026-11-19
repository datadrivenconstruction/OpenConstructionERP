# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request and response schemas for levies, payment discount and bidder search."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Basis = Literal["percent", "fixed"]
AppliesAt = Literal["each_invoice", "final_account"]
DeductionOrder = Literal["levies_then_retention", "retention_then_levies"]

_PCT = {"ge": Decimal("0"), "le": Decimal("100"), "max_digits": 7, "decimal_places": 3}
_AMT = {"ge": Decimal("0"), "le": Decimal("1e15"), "max_digits": 18, "decimal_places": 2}


class LevyCatalogueItemIn(BaseModel):
    """Create or replace one catalogue levy."""

    code: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=255)
    basis: Basis = "percent"
    default_percent: Decimal | None = Field(default=None, **_PCT)
    default_fixed_amount: Decimal | None = Field(default=None, **_AMT)
    applies_at: AppliesAt = "each_invoice"
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=10_000)
    notes: str | None = Field(default=None, max_length=4000)


class LevyCatalogueItemResponse(LevyCatalogueItemIn):
    """A catalogue levy as stored."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source: str = "company"


class PackLevyDefault(BaseModel):
    """A levy name a country pack suggests; the rate is left to the company."""

    code: str
    name: str
    basis: Basis = "percent"
    applies_at: AppliesAt = "each_invoice"
    country: str
    pack: str
    source_note: str = ""
    in_catalogue: bool = False


class LevyCatalogueResponse(BaseModel):
    """The company catalogue and the levy names the workspace's packs suggest."""

    items: list[LevyCatalogueItemResponse]
    pack_defaults: list[PackLevyDefault] = Field(default_factory=list)


class SubcontractLevyIn(BaseModel):
    """One levy on a subcontract."""

    catalogue_id: UUID | None = None
    code: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=255)
    basis: Basis = "percent"
    rate_percent: Decimal | None = Field(default=None, **_PCT)
    fixed_amount: Decimal | None = Field(default=None, **_AMT)
    applies_at: AppliesAt = "each_invoice"


class SubcontractLevyResponse(SubcontractLevyIn):
    """A subcontract levy as stored."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sort_order: int = 0


class SubcontractTermsIn(BaseModel):
    """Deduction terms of a subcontract (replaces the levy list as a whole)."""

    deduction_order: DeductionOrder = "levies_then_retention"
    retention_cap_percent: Decimal | None = Field(default=None, **_PCT)
    payment_discount_percent: Decimal | None = Field(default=None, **_PCT)
    payment_discount_days: int | None = Field(default=None, ge=0, le=365)
    payment_discount_agreed: bool = False
    levies: list[SubcontractLevyIn] = Field(default_factory=list, max_length=50)


class SubcontractTermsResponse(BaseModel):
    """Deduction terms of a subcontract as stored."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    agreement_id: UUID | None = None
    contract_id: UUID | None = None
    deduction_order: DeductionOrder = "levies_then_retention"
    retention_cap_percent: Decimal | None = None
    payment_discount_percent: Decimal | None = None
    payment_discount_days: int | None = None
    payment_discount_agreed: bool = False
    source: str = "manual"
    levies: list[SubcontractLevyResponse] = Field(default_factory=list)
    is_default: bool = False


class ValidationRow(BaseModel):
    """One validation result, flattened for the client."""

    rule_id: str
    severity: str
    passed: bool
    message: str
    element_ref: str | None = None
    suggestion: str | None = None


class DeductionStatementResponse(BaseModel):
    """Levies, retention and payment discount of one payment application."""

    agreement_id: UUID
    payment_application_id: UUID | None = None
    application_number: str | None = None
    currency: str = ""
    contract_sum: Decimal
    work_value: Decimal
    deduction_order: DeductionOrder
    final_account: bool = False
    levies: list[dict[str, Any]]
    levies_total: Decimal
    retention_base: Decimal
    retention_percent: Decimal
    retention_amount: Decimal
    retention_capped: bool
    retention_cap_amount: Decimal | None = None
    retained_to_date: Decimal
    payable: Decimal
    payment_discount_percent: Decimal | None = None
    payment_discount_days: int | None = None
    payment_discount_agreed: bool = False
    payment_discount_amount: Decimal
    payable_with_discount: Decimal
    discount_due_date: date | None = None
    discount_applies: bool | None = None
    amount_to_pay: Decimal
    lines: list[dict[str, Any]]
    validation: list[ValidationRow] = Field(default_factory=list)


class FirmLocationIn(BaseModel):
    """Coordinates typed in by hand (WGS84 decimal degrees)."""

    lat: Decimal = Field(ge=Decimal("-90"), le=Decimal("90"))
    lon: Decimal = Field(ge=Decimal("-180"), le=Decimal("180"))


class FirmLocationResponse(BaseModel):
    """Where a firm is, or why the platform does not know."""

    subcontractor_id: UUID
    has_coordinates: bool
    lat: Decimal | None = None
    lon: Decimal | None = None
    source: str | None = None
    precision: str | None = None
    located_at: datetime | None = None
    # ``no_address``, ``geocoder_unavailable`` or ``not_found`` when there are no coordinates.
    reason: str | None = None


class BidderRow(BaseModel):
    """One firm in the bidder picker."""

    id: UUID
    legal_name: str
    trade_name: str | None = None
    trade_categories: list[str] = Field(default_factory=list)
    prequalification_status: str
    city: str | None = None
    has_coordinates: bool = False
    distance_km: Decimal | None = None
    within_radius: bool | None = None
    is_favourite: bool = False


class BidderSearchResponse(BaseModel):
    """Firms for a trade around a project site."""

    items: list[BidderRow]
    total: int
    radius_km: Decimal | None = None
    site_has_coordinates: bool = False
    without_coordinates: int = 0
    hidden_blocked: int = 0
    validation: list[ValidationRow] = Field(default_factory=list)


class FavouriteIn(BaseModel):
    """Mark a firm as favourite for a trade."""

    subcontractor_id: UUID
    trade: str = Field(min_length=1, max_length=120)
