# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic schemas for the capital plan API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.core.decimal_types import FiniteDecimal

ItemStatus = Literal["proposed", "funded", "deferred"]
_YEAR = {"ge": 1900, "le": 2200}


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Plans ──────────────────────────────────────────────────────────────────


class PlanCreate(_In):
    name: str = Field(..., min_length=1, max_length=255)
    node_id: UUID | None = None
    currency: str = Field(..., min_length=3, max_length=3)
    start_year: int = Field(..., **_YEAR)
    horizon_years: int = Field(default=5, ge=1, le=15)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


class PlanPatch(_In):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    node_id: UUID | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    start_year: int | None = Field(default=None, **_YEAR)
    horizon_years: int | None = Field(default=None, ge=1, le=15)

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class PlanResponse(_Out):
    id: UUID
    node_id: UUID | None
    name: str
    currency: str
    start_year: int
    horizon_years: int
    created_by: UUID | None
    metadata_: dict[str, Any] = Field(default_factory=dict, serialization_alias="metadata")
    created_at: datetime
    updated_at: datetime


# ── Envelopes ──────────────────────────────────────────────────────────────


class EnvelopeIn(_In):
    year: int = Field(..., **_YEAR)
    amount: Decimal = Field(..., ge=0, max_digits=18, decimal_places=2)
    label: str = Field(default="", max_length=100)


class EnvelopesReplace(_In):
    envelopes: list[EnvelopeIn] = Field(default_factory=list, max_length=500)


class EnvelopeResponse(_Out):
    id: UUID
    plan_id: UUID
    year: int
    amount: Decimal
    label: str


# ── Scenarios ──────────────────────────────────────────────────────────────


class ScenarioCreate(_In):
    name: str = Field(..., min_length=1, max_length=255)
    is_baseline: bool = False
    notes: str = Field(default="", max_length=5000)


class ScenarioPatch(_In):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_baseline: bool | None = None
    notes: str | None = Field(default=None, max_length=5000)


class CloneRequest(_In):
    name: str | None = Field(default=None, min_length=1, max_length=255)


class ScenarioResponse(_Out):
    id: UUID
    plan_id: UUID
    name: str
    is_baseline: bool
    notes: str
    created_at: datetime
    updated_at: datetime


# ── Items ──────────────────────────────────────────────────────────────────


def _check_phasing(values: list[Decimal] | None) -> list[Decimal] | None:
    if values is not None and any(v < 0 or v > 1 for v in values):
        raise ValueError("phasing fractions must be between 0 and 1")
    return values


class ItemCreate(_In):
    title: str = Field(..., min_length=1, max_length=255)
    project_id: UUID | None = None
    priority: int = Field(default=3, ge=1, le=5)
    start_year: int = Field(..., **_YEAR)
    duration_years: int = Field(default=1, ge=1, le=30)
    total_cost: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)
    phasing: list[FiniteDecimal] | None = Field(default=None, max_length=30)
    status: ItemStatus = "proposed"
    score: int | None = Field(default=None, ge=0, le=100)

    _phasing = field_validator("phasing")(_check_phasing)


class ItemPatch(_In):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    project_id: UUID | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    start_year: int | None = Field(default=None, **_YEAR)
    duration_years: int | None = Field(default=None, ge=1, le=30)
    total_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    phasing: list[FiniteDecimal] | None = Field(default=None, max_length=30)
    status: ItemStatus | None = None
    score: int | None = Field(default=None, ge=0, le=100)

    _phasing = field_validator("phasing")(_check_phasing)


class ItemResponse(_Out):
    id: UUID
    scenario_id: UUID
    project_id: UUID | None
    title: str
    priority: int
    start_year: int
    duration_years: int
    total_cost: Decimal
    phasing: list[Decimal] = Field(validation_alias=AliasChoices("phasing_json", "phasing"))
    status: str
    score: int | None


class ItemStatusChange(_In):
    id: UUID
    status: ItemStatus


class ApplyStatuses(_In):
    items: list[ItemStatusChange] = Field(..., min_length=1, max_length=1000)


# ── Analysis ───────────────────────────────────────────────────────────────


class Finding(BaseModel):
    rule_id: str
    severity: str
    message: str
    element_ref: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class YearRow(BaseModel):
    year: int
    demand: FiniteDecimal
    envelope: FiniteDecimal
    gap: FiniteDecimal
    cumulative_gap: FiniteDecimal


class ItemSpend(BaseModel):
    id: str
    spend: dict[str, FiniteDecimal]
    outside_horizon: FiniteDecimal


class PlanListResponse(BaseModel):
    items: list[PlanResponse]
    total: int
    offset: int = 0
    limit: int = 200


class EnvelopeListResponse(BaseModel):
    items: list[EnvelopeResponse]
    total: int
    offset: int = 0
    limit: int = 500


class ScenarioListResponse(BaseModel):
    items: list[ScenarioResponse]
    total: int
    offset: int = 0
    limit: int = 200


class ItemListResponse(BaseModel):
    items: list[ItemResponse]
    total: int
    offset: int = 0
    limit: int = 1000


class SummaryResponse(BaseModel):
    years: list[int]
    rows: list[YearRow]
    items: list[ItemSpend]
    totals: dict[str, Decimal]
    unfunded: list[str]
    findings: list[Finding]


class Suggestion(BaseModel):
    id: str
    status: ItemStatus
    confidence: float
    reason: str
    changed: bool


class AutofundResponse(BaseModel):
    items: list[Suggestion]
    findings: list[Finding]


class ImportResponse(BaseModel):
    created: list[ItemResponse]
    skipped: int = 0


class CompareYear(BaseModel):
    year: int
    demand_a: FiniteDecimal
    demand_b: FiniteDecimal
    delta_demand: FiniteDecimal
    gap_a: FiniteDecimal
    gap_b: FiniteDecimal
    delta_gap: FiniteDecimal


class ChangedItem(BaseModel):
    title: str
    change: Literal["added", "removed", "changed"]
    status_a: str | None = None
    status_b: str | None = None
    start_year_a: int | None = None
    start_year_b: int | None = None


class CompareResponse(BaseModel):
    years: list[CompareYear]
    changed_items: list[ChangedItem]
    totals: dict[str, Decimal]
