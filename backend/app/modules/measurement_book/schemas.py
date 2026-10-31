# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Measurement book request and response schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CheckStatus = Literal["unchecked", "checked", "disputed"]

_Dim = Decimal | None


class EntryBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    entry_date: date | None = None
    location: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    length: _Dim = Field(default=None, ge=0)
    breadth: _Dim = Field(default=None, ge=0)
    height: _Dim = Field(default=None, ge=0)
    number: _Dim = Field(default=None, ge=0)
    direct_quantity: _Dim = None
    measured_by: str | None = Field(default=None, max_length=255)
    bill_ref: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=4000)


class EntryCreate(EntryBase):
    project_id: uuid.UUID
    boq_position_id: uuid.UUID
    entry_date: date


class EntryUpdate(EntryBase):
    pass


class EntryCheck(BaseModel):
    status: CheckStatus
    check_quantity: Decimal | None = None
    checked_by: str | None = Field(default=None, max_length=255)


class EntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    boq_position_id: uuid.UUID
    entry_date: date
    location: str
    description: str
    length: Decimal | None
    breadth: Decimal | None
    height: Decimal | None
    number: Decimal | None
    direct_quantity: Decimal | None
    quantity: Decimal
    measured_by: str
    check_status: str
    check_quantity: Decimal | None
    checked_by: str | None
    checked_at: datetime | None
    bill_ref: str | None
    notes: str | None


class PositionSummary(BaseModel):
    boq_position_id: uuid.UUID
    ordinal: str
    description: str
    unit: str
    boq_quantity: Decimal
    unit_rate: Decimal
    measured_quantity: Decimal
    checked_quantity: Decimal
    entry_count: int
    unchecked_count: int
    percent_measured: Decimal
    value_to_date: Decimal


class RunningBill(BaseModel):
    project_id: uuid.UUID
    currency: str
    lines: list[PositionSummary]
    total_value: Decimal
    unchecked_count: int
    can_certify: bool


class PostToProgress(BaseModel):
    period_label: str = Field(..., min_length=1, max_length=20)


class PostToProgressResult(BaseModel):
    recorded: int
    skipped: int


class ValidationResponse(BaseModel):
    status: str
    checked: int
    results: list[dict[str, Any]]
