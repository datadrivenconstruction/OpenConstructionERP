# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic schemas of the plant rate catalogue."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.decimal_types import Decimal18_4

_ISO_DATE = r"^\d{4}-\d{2}-\d{2}$"
_CONVENTION = r"^(average_value|average_annual_investment)$"


class CatalogueBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=200)
    source_label: str = Field(default="", max_length=200)
    licence_note: str = Field(default="", max_length=4000)
    currency: str = Field(default="", max_length=3)
    valid_from: str = Field(..., pattern=_ISO_DATE)
    interest_convention: str = Field(default="average_value", pattern=_CONVENTION)
    working_days_per_month: Decimal | None = Field(default=None, gt=0, le=31)
    standby_factor: Decimal | None = Field(default=None, ge=0)
    breakdown_factor: Decimal | None = Field(default=None, ge=0)
    tolerance_pct: Decimal | None = Field(default=None, ge=0)


class CatalogueCreate(CatalogueBase):
    is_synthetic: bool = False


class CatalogueUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    source_label: str | None = Field(default=None, max_length=200)
    licence_note: str | None = Field(default=None, max_length=4000)
    currency: str | None = Field(default=None, max_length=3)
    interest_convention: str | None = Field(default=None, pattern=_CONVENTION)
    working_days_per_month: Decimal | None = Field(default=None, gt=0, le=31)
    standby_factor: Decimal | None = Field(default=None, ge=0)
    breakdown_factor: Decimal | None = Field(default=None, ge=0)
    tolerance_pct: Decimal | None = Field(default=None, ge=0)


class CatalogueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    family_id: UUID
    name: str
    source_label: str
    licence_note: str
    currency: str
    valid_from: str
    interest_convention: str
    is_synthetic: bool
    working_days_per_month: Decimal | None = None
    standby_factor: Decimal | None = None
    breakdown_factor: Decimal | None = None
    tolerance_pct: Decimal | None = None
    superseded: bool = False
    superseded_on: str | None = None
    machines: int = 0
    used_by_assets: int = 0
    created_at: datetime
    updated_at: datetime


class ItemInputs(BaseModel):
    """The formula inputs; interest and repair are fractions (0.06 = 6%)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    value: Decimal18_4
    residual: Decimal18_4
    life_years: Decimal
    months_per_year: Decimal
    interest: Decimal
    repair: Decimal
    hours_per_month: Decimal | None = None


class ItemCreate(ItemInputs):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    category: str = Field(default="", max_length=100)
    size_key: str = Field(default="", max_length=50)
    override_monthly_rate: Decimal18_4 | None = Field(default=None, ge=0)
    operating_cost_per_hour: Decimal18_4 | None = Field(default=None, ge=0)


class ItemUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(default=None, max_length=100)
    size_key: str | None = Field(default=None, max_length=50)
    value: Decimal18_4 | None = None
    residual: Decimal18_4 | None = None
    life_years: Decimal | None = None
    months_per_year: Decimal | None = None
    interest: Decimal | None = None
    repair: Decimal | None = None
    hours_per_month: Decimal | None = None
    override_monthly_rate: Decimal18_4 | None = Field(default=None, ge=0)
    operating_cost_per_hour: Decimal18_4 | None = Field(default=None, ge=0)


class RateBreakdown(BaseModel):
    depreciation: Decimal | None = None
    interest: Decimal | None = None
    repair: Decimal | None = None
    monthly: Decimal | None = None
    hourly: Decimal | None = None
    daily: Decimal | None = None
    manual: bool = False


class ItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    catalogue_id: UUID
    code: str
    name: str
    category: str
    size_key: str
    value: Decimal
    residual: Decimal
    life_years: Decimal
    months_per_year: Decimal
    interest: Decimal
    repair: Decimal
    hours_per_month: Decimal | None = None
    override_monthly_rate: Decimal | None = None
    operating_cost_per_hour: Decimal | None = None
    is_synthetic: bool = False
    assets: int = 0
    rates: RateBreakdown = Field(default_factory=RateBreakdown)


class CatalogueDetailResponse(CatalogueResponse):
    items: list[ItemResponse] = Field(default_factory=list)


class PreviewRequest(BaseModel):
    """Live preview of the formula for the drawer; any input may still be empty."""

    value: Decimal | None = None
    residual: Decimal | None = None
    life_years: Decimal | None = None
    months_per_year: Decimal | None = None
    interest: Decimal | None = None
    repair: Decimal | None = None
    hours_per_month: Decimal | None = None
    interest_convention: str = Field(default="average_value", pattern=_CONVENTION)
    working_days_per_month: Decimal | None = None
    override_monthly_rate: Decimal | None = None


class IssueOut(BaseModel):
    rule_id: str
    severity: str
    message: str
    field: str | None = None
    row: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class PreviewResponse(BaseModel):
    valid: bool
    rates: RateBreakdown
    issues: list[IssueOut] = Field(default_factory=list)


class ProfileCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=200)
    layout_key: str = Field(default="own", max_length=50)
    mapping: dict[str, str] = Field(default_factory=dict)
    decimal_comma: bool = False
    percent_fields: list[str] = Field(default_factory=lambda: ["interest", "repair"])


class ProfileResponse(ProfileCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


class ProfileListResponse(BaseModel):
    items: list[ProfileResponse]
    total: int
    offset: int = 0
    limit: int = 50


class CatalogueListResponse(BaseModel):
    items: list[CatalogueResponse]
    total: int
    offset: int = 0
    limit: int = 50


class LayoutOut(BaseModel):
    key: str
    label_key: str
    mapping: dict[str, str]
    decimal_comma: bool
    interest_convention: str


class ImportPreviewResponse(BaseModel):
    headers: list[str]
    sample: list[list[str]]
    total_rows: int
    suggested_mapping: dict[str, str]
    layouts: list[LayoutOut]
    fields: list[str]
    required_fields: list[str]


class ImportCheckResponse(BaseModel):
    ready: int
    error_rows: int
    total_rows: int
    issues: list[IssueOut]
    catalogue_id: UUID | None = None


class RentalDefaults(BaseModel):
    equipment_id: UUID
    item_id: UUID | None = None
    catalogue_name: str | None = None
    currency: str = ""
    hourly_rate: Decimal | None = None
    daily_rate: Decimal | None = None
    monthly_rate: Decimal | None = None
    synthetic: bool = False
    tolerance_pct: Decimal | None = None


class ChargePreviewRequest(BaseModel):
    equipment_id: UUID
    operational_hours: Decimal = Field(default=Decimal("0"), ge=0)
    standby_hours: Decimal = Field(default=Decimal("0"), ge=0)
    breakdown_hours: Decimal = Field(default=Decimal("0"), ge=0)


class ChargePreviewResponse(BaseModel):
    currency: str = ""
    hourly_rate: Decimal | None = None
    operational: Decimal = Decimal("0")
    standby: Decimal = Decimal("0")
    breakdown: Decimal = Decimal("0")
    operating_cost: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    standby_billed: bool = False
