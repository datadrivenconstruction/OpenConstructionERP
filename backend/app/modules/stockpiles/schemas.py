# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Stockpile request and response schemas.

Tonnes and volumes travel as JSON numbers rounded to the stored precision
(0.01 t, 0.001 m3); the service keeps Decimal arithmetic underneath.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

DensitySource = Literal["measured", "supplier", "assumed"]
SourceKind = Literal["surface", "typed"]


class Finding(BaseModel):
    rule_id: str
    severity: str
    message: str
    suggestion: str = ""
    element_ref: str | None = None


class StockpileCreate(BaseModel):
    """A new stockpile. The base is an existing surface or a point file read on the spot."""

    name: str = Field(min_length=1, max_length=255)
    material: str = Field(default="", max_length=120)
    location_note: str = Field(default="", max_length=255)
    base_surface_id: uuid.UUID | None = None
    base_text: str = Field(default="", max_length=6_000_000)
    base_filename: str = Field(default="", max_length=255)
    book_tonnes: float | None = Field(default=None, ge=0, le=1e10)
    variance_tolerance_pct: float | None = Field(default=None, ge=0, le=100)
    site_inventory_item_id: uuid.UUID | None = None
    note: str = Field(default="", max_length=2000)


class StockpileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    material: str | None = Field(default=None, max_length=120)
    location_note: str | None = Field(default=None, max_length=255)
    base_surface_id: uuid.UUID | None = None
    book_tonnes: float | None = Field(default=None, ge=0, le=1e10)
    variance_tolerance_pct: float | None = Field(default=None, ge=0, le=100)
    site_inventory_item_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=2000)


class SurveyCreate(BaseModel):
    """One survey: a surface or point file for the pile, or a typed volume, plus the density."""

    surveyed_on: date | None = None
    pile_surface_id: uuid.UUID | None = None
    pile_text: str = Field(default="", max_length=6_000_000)
    pile_filename: str = Field(default="", max_length=255)
    volume_m3: float | None = Field(default=None, gt=0, le=1e9)
    cell_size_m: float | None = Field(default=None, gt=0, le=1000)
    density_t_m3: float = Field(gt=0, le=25)
    density_source: DensitySource = "assumed"
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _one_source(self) -> Self:
        given = [self.pile_surface_id is not None, bool(self.pile_text.strip()), self.volume_m3 is not None]
        if sum(given) != 1:
            raise ValueError("Give exactly one of: a pile surface, a point file, or a volume")
        return self


class SurveyUpdate(BaseModel):
    surveyed_on: date | None = None
    pile_surface_id: uuid.UUID | None = None
    volume_m3: float | None = Field(default=None, gt=0, le=1e9)
    cell_size_m: float | None = Field(default=None, gt=0, le=1000)
    density_t_m3: float | None = Field(default=None, gt=0, le=25)
    density_source: DensitySource | None = None
    note: str | None = Field(default=None, max_length=2000)


class AdjustmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    survey_id: uuid.UUID
    stockpile_id: uuid.UUID
    delta_t: float
    status: str
    movement_id: uuid.UUID | None = None
    note: str = ""
    confirmed_by_name: str = ""
    confirmed_at: datetime | None = None
    created_at: datetime | None = None


class SurveyOut(BaseModel):
    id: uuid.UUID
    stockpile_id: uuid.UUID
    surveyed_on: date
    source_kind: str
    pile_surface_id: uuid.UUID | None = None
    pile_name: str = ""
    volume_m3: float
    cell_size_m: float | None = None
    coverage_pct: float | None = None
    crs_epsg: int | None = None
    density_t_m3: float
    density_source: str
    tonnes: float
    book_tonnes: float | None = None
    variance_t: float | None = None
    variance_pct: float | None = None
    status: str
    note: str = ""
    findings: list[Finding] = Field(default_factory=list)
    adjustment: AdjustmentOut | None = None
    created_at: datetime | None = None


class StockpileOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    code: str
    name: str
    material: str = ""
    location_note: str = ""
    base_surface_id: uuid.UUID | None = None
    base_name: str = ""
    site_inventory_item_id: uuid.UUID | None = None
    book_tonnes: float | None = None
    variance_tolerance_pct: float | None = None
    note: str = ""
    survey_count: int = 0
    last_survey: SurveyOut | None = None
    created_at: datetime | None = None


class StockpileDetail(StockpileOut):
    surveys: list[SurveyOut] = Field(default_factory=list)


class StockpileSummary(BaseModel):
    stockpiles: int
    surveyed_tonnes: float
    book_tonnes: float
    variance_pct: float | None = None
    surveyed_stockpiles: int = 0


class AdjustmentConfirm(BaseModel):
    note: str = Field(default="", max_length=2000)
