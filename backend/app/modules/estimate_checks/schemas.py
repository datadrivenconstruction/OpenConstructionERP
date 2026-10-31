# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate check request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DisplayMode = Literal["all", "issues", "badge", "off"]
Status = Literal["normal", "suspect", "warning", "no_data"]
Comparables = Literal["auto", "currency", "all"]


class PositionRef(BaseModel):
    id: str
    ordinal: str
    description: str


class Acceptance(BaseModel):
    reason: str
    accepted_by: str
    accepted_at: datetime | None = None
    status_at_accept: str
    value_at_accept: str | None = None


class KpiResult(BaseModel):
    kpi_id: str
    group: str
    unit: str
    unit_label: str | None = None
    value: float | None = None
    low: float | None = None
    high: float | None = None
    compared: int = 0
    status: Status
    confidence: float
    reason: str
    positions: list[PositionRef] = Field(default_factory=list)
    position_count: int = 0
    accepted: Acceptance | None = None


class StatusCounts(BaseModel):
    normal: int = 0
    suspect: int = 0
    warning: int = 0
    accepted: int = 0


class CheckResponse(BaseModel):
    boq_id: str
    revision: str
    currency: str
    comparables_scope: str
    comparables_pool: int
    counts: StatusCounts
    kpis: list[KpiResult]


class AcceptRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=2000)


class KpiSetting(BaseModel):
    enabled: bool = True
    low: float | None = None
    high: float | None = None


class SettingsBody(BaseModel):
    comparables: Comparables = "auto"
    min_comparables: int = Field(default=5, ge=2, le=200)
    warning_margin: float = Field(default=0.5, ge=0, le=10)
    database_rate_tolerance_pct: float = Field(default=30.0, gt=0, le=1000)
    count_warning_share_pct: float = Field(default=5.0, gt=0, le=100)
    kpis: dict[str, KpiSetting] = Field(default_factory=dict)


class KpiCatalogEntry(BaseModel):
    kpi_id: str
    group: str
    unit: str
    kind: str
    default_low: float | None = None
    default_high: float | None = None


class SettingsResponse(SettingsBody):
    catalog: list[KpiCatalogEntry] = Field(default_factory=list)


class PreferenceBody(BaseModel):
    display_mode: DisplayMode = "badge"
