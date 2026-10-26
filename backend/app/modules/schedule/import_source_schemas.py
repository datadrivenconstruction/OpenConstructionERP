# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Response shapes for the source of an imported schedule."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class ImportSourceRecord(BaseModel):
    """What a schedule was imported from (``Schedule.metadata_["import_source"]``)."""

    format: str
    filename: str = ""
    sha256: str = ""
    size_bytes: int = 0
    document_id: str | None = None
    document_issue: str | None = None
    imported_at: str | None = None
    imported_by: str | None = None
    activity_count: int = 0
    status: str = Field(default="pending_review", description="pending_review | accepted")
    accepted_at: str | None = None
    accepted_by: str | None = None


class SourceComparisonRow(BaseModel):
    """One activity: dates as in the source file beside the current dates."""

    activity_id: UUID
    activity_code: str | None = None
    name: str
    source_id: str | None = None
    source_start: str | None = None
    source_finish: str | None = None
    source_duration_days: int | None = None
    current_start: str | None = None
    current_finish: str | None = None
    current_duration_days: int | None = None
    start_deviation_days: int | None = None
    finish_deviation_days: int | None = None


class SourceComparisonResponse(BaseModel):
    """Source versus current dates for an imported schedule."""

    schedule_id: UUID
    source: ImportSourceRecord
    activity_count: int = 0
    deviating_count: int = 0
    max_finish_deviation_days: int = 0
    source_finish: str | None = None
    current_finish: str | None = None
    project_finish_deviation_days: int | None = None
    activities: list[SourceComparisonRow] = Field(default_factory=list)


class SourceRestoreResponse(BaseModel):
    """How many activities went back to their source dates."""

    schedule_id: UUID
    moved: int
