# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Response shapes of the progress sheet round-trip."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class FieldChange(BaseModel):
    """One value the sheet would change: what the app has, what the sheet says."""

    old: str | float | int | None = None
    new: str | float | int | None = None


class SheetIssue(BaseModel):
    """A validation finding on one sheet row."""

    rule_id: str
    code: str
    severity: str
    message: str


class SheetPreviewRow(BaseModel):
    """One sheet row matched against the schedule."""

    row_number: int
    activity_id: UUID | None = None
    activity_code: str | None = None
    name: str | None = None
    changes: dict[str, FieldChange] = Field(default_factory=dict)
    issues: list[SheetIssue] = Field(default_factory=list)
    stale: bool = False
    has_errors: bool = False
    applicable: bool = Field(default=False, description="Has changes and no errors")


class SheetPreviewResponse(BaseModel):
    """What an upload would change, per activity, before anything is written."""

    schedule_id: UUID
    filename: str
    sha256: str
    exported_at: str | None = None
    exported_data_date: str | None = None
    status_date: str
    row_count: int = 0
    changed_count: int = 0
    error_count: int = 0
    stale_count: int = 0
    rows: list[SheetPreviewRow] = Field(default_factory=list)


class SheetApplySkip(BaseModel):
    """A selected row that was not applied, and why."""

    row_number: int
    activity_id: UUID | None = None
    code: str


class SheetApplyResponse(BaseModel):
    """Result of applying a confirmed progress sheet."""

    schedule_id: UUID
    batch_id: str
    status_date: str
    applied_count: int = 0
    applied_activity_ids: list[UUID] = Field(default_factory=list)
    skipped: list[SheetApplySkip] = Field(default_factory=list)
    data_date_advanced: bool = False
