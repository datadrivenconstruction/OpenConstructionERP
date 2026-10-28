# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ benchmarks request and response schemas. Money is a Decimal string on the wire."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.modules.cost_benchmarks.bench_math import STANDARDS


class ElementIn(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    label: str = Field(default="", max_length=255)
    amount: Decimal = Field(ge=0)


class RecordCreate(BaseModel):
    kind: Literal["completed", "estimate"] = "completed"
    name: str = Field(min_length=1, max_length=255)
    project_type: str = Field(default="", max_length=50)
    country: str = Field(default="", max_length=2)
    region: str = Field(default="", max_length=64)
    currency: str = Field(min_length=3, max_length=3)
    cost_date: date
    standard: str = Field(default="din276")
    gfa_m2: Decimal | None = Field(default=None, ge=0)
    functional_unit: str = Field(default="", max_length=30)
    functional_units: Decimal | None = Field(default=None, ge=0)
    total_cost: Decimal | None = Field(default=None, ge=0)
    notes: str = ""
    elements: list[ElementIn] = []

    def standard_ok(self) -> bool:
        return self.standard in STANDARDS


class ElementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    label: str
    amount: Decimal

    @field_serializer("amount")
    def _s(self, v: Decimal) -> str:
        return str(v)


class RecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    project_id: uuid.UUID | None
    name: str
    project_type: str
    country: str
    region: str
    currency: str
    cost_date: date
    standard: str
    gfa_m2: Decimal | None
    functional_unit: str
    functional_units: Decimal | None
    total_cost: Decimal
    is_synthetic: bool
    source: str
    elements: list[ElementOut] = []

    @field_serializer("gfa_m2", "functional_units", "total_cost")
    def _s(self, v: Decimal | None) -> str | None:
        return None if v is None else str(v)


class RecordListResponse(BaseModel):
    items: list[RecordOut]
    total: int
    offset: int = 0
    limit: int = 50


class CompareRequest(BaseModel):
    estimate_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    project_type: str | None = None
    countries: list[str] = []
    region: str | None = None
    gfa_min: Decimal | None = None
    gfa_max: Decimal | None = None
    year_from: int | None = None
    year_to: int | None = None
    base_date: date | None = None
    base_region: str | None = None
    reporting_currency: str = Field(default="EUR", min_length=3, max_length=3)
    fx_date: date | None = None
    index_series_id: uuid.UUID | None = None
    measure: Literal["gfa", "unit"] = "gfa"
    min_projects: int = Field(default=5, ge=1, le=100)
    stale_months: int = Field(default=12, ge=1, le=120)
