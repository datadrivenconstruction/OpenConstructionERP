# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic schemas of the payroll hours export."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ColumnIn(BaseModel):
    header: str = Field(default="", max_length=100)
    source: str = Field(default="", max_length=30)
    constant: str = Field(default="", max_length=100)


class ProfileConfig(BaseModel):
    """The layout of one export; pay codes are the customer's own, never defaulted."""

    model_config = ConfigDict(str_strip_whitespace=True)

    columns: list[ColumnIn] = Field(default_factory=list, max_length=30)
    delimiter: str = Field(default=";", min_length=1, max_length=1)
    decimal: str = Field(default=",", pattern=r"^[.,]$")
    date_format: str = Field(default="DD.MM.YYYY", max_length=30)
    encoding: str = Field(default="utf-8", pattern=r"^(utf-8|utf-8-sig|cp1252|latin-1)$")
    grouping: str = Field(default="day", pattern=r"^(day|week)$")
    week_start: int = Field(default=0, ge=0, le=6)
    include_daywork: bool = True
    include_header: bool = True
    fallback_to_code: bool = False
    day_threshold: Decimal | None = Field(default=None, gt=0, le=24)
    pay_codes: dict[str, str] = Field(default_factory=dict)


class ProfileCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=200)
    legal_entity_id: UUID | None = None
    is_sample: bool = False
    config: ProfileConfig = Field(default_factory=ProfileConfig)


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    legal_entity_id: UUID | None = None
    is_sample: bool = False
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ExampleOut(BaseModel):
    key: str
    label_key: str
    name: str
    config: ProfileConfig


class IssueOut(BaseModel):
    rule_id: str
    severity: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class PreviewRow(BaseModel):
    worker_ref: str
    worker_name: str
    date: date
    project_code: str
    cost_code: str
    hour_type: str
    pay_code: str
    hours: Decimal
    correction: bool


class PreviewResponse(BaseModel):
    workers: int
    rows: int
    hours: Decimal
    corrections: int
    issues: list[IssueOut]
    blocked: bool
    overlapping_runs: list[str]
    sample: list[PreviewRow]
    preview_lines: list[str] = Field(default_factory=list)


class RunCreate(BaseModel):
    profile_id: UUID
    period_from: date
    period_to: date
    project_ids: list[UUID] = Field(default_factory=list)


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: int
    profile_id: UUID | None = None
    profile_name: str
    period_from: date
    period_to: date
    row_count: int
    correction_count: int
    worker_count: int
    total_hours: Decimal
    filename: str
    sha256: str
    created_at: datetime


class ExampleListResponse(BaseModel):
    items: list[ExampleOut]
    total: int
    offset: int = 0
    limit: int = 100


class ProfileListResponse(BaseModel):
    items: list[ProfileResponse]
    total: int
    offset: int = 0
    limit: int = 200


class RunListResponse(BaseModel):
    items: list[RunResponse]
    total: int
    offset: int = 0
    limit: int = 50
