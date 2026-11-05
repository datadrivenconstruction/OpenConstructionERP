# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Owner schedule API schemas. Money and quantities travel as decimal strings."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProfileSummary(BaseModel):
    key: str
    name: str
    source: str
    file_type: str
    handled_by: str


class ProfileListResponse(BaseModel):
    items: list[ProfileSummary]
    total: int
    offset: int = 0
    limit: int = 200


class DetectCandidate(BaseModel):
    profile_key: str
    name: str
    source: str
    confidence: float
    reasons: list[str] = Field(default_factory=list)
    item_count: int = 0


class Issue(BaseModel):
    severity: str
    code: str
    row: int | None = None
    item_no: str | None = None
    role: str | None = None


class PreviewLine(BaseModel):
    row: int
    item_no: str
    description: str
    unit: str
    quantity: str | None
    is_section: bool
    is_alternate: bool
    is_lump_sum: bool


class PreviewResponse(BaseModel):
    profile_key: str
    sheet: str | None
    header_row: int | None
    columns: dict[str, int]
    item_count: int
    lines: list[PreviewLine]
    issues: list[Issue]


class ScheduleItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_no: str
    description: str
    unit: str
    quantity: str | None
    is_section: bool
    is_alternate: bool
    is_lump_sum: bool
    removed: bool
    position_id: uuid.UUID | None
    unit_price: str | None = None
    amount: str | None = None


class Finding(BaseModel):
    rule_id: str
    severity: str
    message: str
    item_no: str | None = None


class ScheduleStatus(BaseModel):
    id: uuid.UUID
    boq_id: uuid.UUID
    profile_key: str
    profile_name: str
    file_name: str
    revision: int
    item_count: int
    priced_count: int
    total: str
    alternates_total: str
    items: list[ScheduleItemOut]
    findings: list[Finding]


class ImportResult(BaseModel):
    schedule_id: uuid.UUID
    created_positions: int
    linked_positions: int
    item_count: int


class DiffChange(BaseModel):
    kind: str
    item_no: str
    fields: list[str] = Field(default_factory=list)
    old: dict[str, Any] | None = None
    new: dict[str, Any] | None = None


class AddendumPreview(BaseModel):
    file_name: str
    changes: list[DiffChange]
    issues: list[Issue]


class AddendumApplied(BaseModel):
    revision: int
    applied: int


class CheckReport(BaseModel):
    file_name: str
    total: str
    alternates_total: str
    line_sum: str
    writes: list[dict[str, Any]]
    findings: list[Finding]
