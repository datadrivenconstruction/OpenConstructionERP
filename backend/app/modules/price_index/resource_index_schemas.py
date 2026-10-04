# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic v2 schemas for the resource-index method (Russia).

Money, indices and percentages travel as decimal strings (``DecimalStr``), the
platform-wide convention, so a kopeck never goes through a JSON float.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.price_index.resource_index_math import (
    ResourceIndexInputError,
    normalise_quarter,
)
from app.modules.price_index.schemas import DecimalStr

_NUM_MAX = Decimal("1000000000000")
_PCT_MAX = Decimal("10000")

ResourceGroup = Literal["labor", "machine", "operator_wages", "material"]
ResourceKind = Literal["labor", "machine", "operator", "material"]

# The Literals mirror ``INDEX_GROUPS`` and ``RESOURCE_KINDS`` of the math
# module; a test keeps them in step so the API never accepts a group the
# computation does not know.


def _quarter(value: str) -> str:
    try:
        return normalise_quarter(value)
    except ResourceIndexInputError as exc:
        raise ValueError(str(exc)) from exc


# ── Resource index values ────────────────────────────────────────────────────


class ResourceIndexValueCreate(BaseModel):
    """Enter one index from a quarterly letter."""

    model_config = ConfigDict(str_strip_whitespace=True)

    region_code: str = Field(..., min_length=1, max_length=64)
    quarter: str = Field(..., description="Quarter the index applies to, e.g. '2026-Q1'")
    resource_group: ResourceGroup
    index_value: Decimal = Field(..., gt=0, le=_NUM_MAX)
    source: str = Field(default="", max_length=2000, description="The letter the value comes from")

    @field_validator("quarter")
    @classmethod
    def _check_quarter(cls, value: str) -> str:
        return _quarter(value)


class ResourceIndexValueUpdate(BaseModel):
    """Change an index value or its source. A changed row is no longer a sample."""

    model_config = ConfigDict(str_strip_whitespace=True)

    index_value: Decimal | None = Field(default=None, gt=0, le=_NUM_MAX)
    source: str | None = Field(default=None, max_length=2000)


class ResourceIndexValueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    region_code: str
    quarter: str
    resource_group: str
    index_value: DecimalStr
    source: str
    is_sample: bool
    created_at: datetime
    updated_at: datetime


# ── Overhead and profit norms ────────────────────────────────────────────────


class OverheadNormCreate(BaseModel):
    """Enter the NR and SP percentages for one type of work."""

    model_config = ConfigDict(str_strip_whitespace=True)

    work_type_code: str = Field(..., min_length=1, max_length=64)
    label: str = Field(default="", max_length=255)
    nr_pct: Decimal = Field(..., ge=0, le=_PCT_MAX)
    sp_pct: Decimal = Field(..., ge=0, le=_PCT_MAX)
    source: str = Field(default="", max_length=2000)


class OverheadNormUpdate(BaseModel):
    """Change a norm. A changed row is no longer a sample."""

    model_config = ConfigDict(str_strip_whitespace=True)

    label: str | None = Field(default=None, max_length=255)
    nr_pct: Decimal | None = Field(default=None, ge=0, le=_PCT_MAX)
    sp_pct: Decimal | None = Field(default=None, ge=0, le=_PCT_MAX)
    source: str | None = Field(default=None, max_length=2000)


class OverheadNormResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    work_type_code: str
    label: str
    nr_pct: DecimalStr
    sp_pct: DecimalStr
    source: str
    is_sample: bool
    created_at: datetime
    updated_at: datetime


# ── Compute: explicit input ──────────────────────────────────────────────────


class ResourceLineIn(BaseModel):
    """One resource of a norm at base prices; quantity is per unit of the position."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(default="", max_length=120)
    name: str = Field(default="", max_length=500)
    unit: str = Field(default="", max_length=40)
    kind: ResourceKind
    quantity: Decimal = Field(..., ge=0, le=_NUM_MAX)
    base_unit_price: Decimal = Field(..., ge=0, le=_NUM_MAX)


class PositionIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    ref: str = Field(default="", max_length=64)
    ordinal: str = Field(default="", max_length=50)
    description: str = Field(default="", max_length=2000)
    unit: str = Field(default="", max_length=40)
    quantity: Decimal = Field(..., ge=0, le=_NUM_MAX)
    work_type: str = Field(..., min_length=1, max_length=64)
    resources: list[ResourceLineIn] = Field(default_factory=list, max_length=500)


class ResourceIndexComputeRequest(BaseModel):
    """Price explicit positions with the stored indices, norms and VAT."""

    model_config = ConfigDict(str_strip_whitespace=True)

    region_code: str = Field(..., min_length=1, max_length=64)
    quarter: str
    on_date: date | None = Field(default=None, description="Date the VAT rate is read for; defaults to today")
    positions: list[PositionIn] = Field(..., max_length=5000)

    @field_validator("quarter")
    @classmethod
    def _check_quarter(cls, value: str) -> str:
        return _quarter(value)


# ── Compute: from a BOQ ──────────────────────────────────────────────────────


class BOQResourceIndexSettings(BaseModel):
    """The choices a person makes to price one BOQ by the resource-index method.

    ``work_types`` maps a position id to its work type; positions not in it use
    ``default_work_type``. Stored on the BOQ so the choices survive a visit.

    ``resources_at_base_prices`` is the person's statement that the resource
    prices on this bill are base prices of the 2022 federal base. A line nobody
    has judged (``price_basis`` unset) is indexed only under that statement:
    the platform's own resource splits and most imported bills carry current
    money, and indexing current money a second time is the error this method
    is easiest to make without seeing it.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    region_code: str = Field(default="", max_length=64)
    quarter: str = Field(default="", max_length=7)
    default_work_type: str = Field(default="", max_length=64)
    work_types: dict[str, str] = Field(default_factory=dict, max_length=20000)
    resources_at_base_prices: bool = False

    @field_validator("quarter")
    @classmethod
    def _check_quarter(cls, value: str) -> str:
        return _quarter(value) if value else ""

    @field_validator("work_types")
    @classmethod
    def _check_work_types(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for key, code in value.items():
            k = str(key).strip()
            c = str(code or "").strip()
            if not k or not c:
                continue
            if len(c) > 64:
                raise ValueError("work type codes are at most 64 characters")
            cleaned[k] = c
        return cleaned


class BOQResourceIndexComputeRequest(BOQResourceIndexSettings):
    """Price a BOQ; the same fields as the settings plus the VAT date."""

    on_date: date | None = None


# ── Result ───────────────────────────────────────────────────────────────────


class LineOut(BaseModel):
    code: str
    name: str
    unit: str
    kind: str
    quantity: DecimalStr
    base_unit_price: DecimalStr
    position_quantity: DecimalStr
    base_amount: DecimalStr
    index_group: str
    index: DecimalStr
    current_amount: DecimalStr
    operator_wage_index: DecimalStr | None = None
    operator_wage_current: DecimalStr | None = None


class PositionOut(BaseModel):
    ref: str
    ordinal: str
    description: str
    unit: str
    quantity: DecimalStr
    work_type: str
    work_type_source: Literal["chosen", "default", "explicit"] = "explicit"
    lines: list[LineOut]
    base_ot: DecimalStr
    base_em: DecimalStr
    base_otm: DecimalStr
    base_m: DecimalStr
    base_direct: DecimalStr
    ot: DecimalStr
    em: DecimalStr
    otm: DecimalStr
    m: DecimalStr
    direct: DecimalStr
    fot: DecimalStr
    nr_pct: DecimalStr
    nr: DecimalStr
    sp_pct: DecimalStr
    sp: DecimalStr
    total: DecimalStr


class WorkTypeSummaryOut(BaseModel):
    work_type: str
    label: str
    nr_pct: DecimalStr
    sp_pct: DecimalStr
    fot: DecimalStr
    nr: DecimalStr
    sp: DecimalStr


class TotalsOut(BaseModel):
    base_ot: DecimalStr
    base_em: DecimalStr
    base_otm: DecimalStr
    base_m: DecimalStr
    base_direct: DecimalStr
    ot: DecimalStr
    em: DecimalStr
    otm: DecimalStr
    m: DecimalStr
    direct: DecimalStr
    fot: DecimalStr
    nr: DecimalStr
    sp: DecimalStr
    total: DecimalStr
    vat_rate_pct: DecimalStr
    vat: DecimalStr
    total_with_vat: DecimalStr


class IndexUsedOut(BaseModel):
    resource_group: str
    index_value: DecimalStr
    source: str
    is_sample: bool


class NormUsedOut(BaseModel):
    work_type_code: str
    label: str
    nr_pct: DecimalStr
    sp_pct: DecimalStr
    source: str
    is_sample: bool


class ExcludedPositionOut(BaseModel):
    """A BOQ position that could not be priced by this method, and why."""

    position_id: str
    ordinal: str
    description: str
    reason: Literal[
        "no_resources",
        "unmapped_resource_type",
        "foreign_currency",
        "no_work_type",
        "bad_number",
        "not_base_prices",
        "base_prices_unconfirmed",
        "estimated_resources",
        "machine_without_operator_wages",
    ]
    detail: str = ""


class ResourceIndexEstimateResponse(BaseModel):
    """The priced estimate with every operand, plus what was left out."""

    region_code: str
    quarter: str
    on_date: date
    currency: str
    vat_rate_pct: DecimalStr
    vat_tax_name: str = ""
    indices_used: list[IndexUsedOut]
    norms_used: list[NormUsedOut]
    uses_sample_data: bool
    positions: list[PositionOut]
    by_work_type: list[WorkTypeSummaryOut]
    totals: TotalsOut
    excluded: list[ExcludedPositionOut] = Field(default_factory=list)
    priced_count: int
    excluded_count: int
    is_complete: bool
    boq_id: UUID | None = None
    boq_name: str | None = None
    project_id: UUID | None = None
