# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Inspections Pydantic schemas - request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.optimistic_lock import CLIENT_OP_ID_PATTERN


class ChecklistEntry(BaseModel):
    """A single checklist item within an inspection."""

    id: str | None = None
    category: str | None = Field(default=None, max_length=100)
    question: str = Field(..., min_length=1, max_length=500)
    response_type: str = Field(default="yes_no", max_length=50)
    response: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    critical: bool = False


class InspectionCreate(BaseModel):
    """Create a new quality inspection."""

    model_config = ConfigDict(str_strip_whitespace=True)
    client_op_id: str | None = Field(default=None, pattern=CLIENT_OP_ID_PATTERN, exclude=True)

    project_id: UUID
    inspection_type: str = Field(
        ...,
        pattern=(
            r"^(concrete_pour|waterproofing|mep|fire_stopping|handover|general"
            r"|structural|electrical|plumbing|fire_safety|concrete)$"
        ),
    )
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    location: str | None = Field(default=None, max_length=500)
    wbs_id: str | None = Field(default=None, max_length=36)
    inspector_id: str | None = Field(default=None, max_length=36)
    inspection_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    status: str = Field(
        default="scheduled",
        pattern=r"^(scheduled|in_progress|completed|failed|cancelled)$",
    )
    result: str | None = Field(default=None, pattern=r"^(pass|fail|partial)$")
    checklist_data: list[ChecklistEntry] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InspectionUpdate(BaseModel):
    """Partial update for a quality inspection."""

    model_config = ConfigDict(str_strip_whitespace=True)
    version: int | None = Field(default=None, ge=1, exclude=True)

    inspection_type: str | None = Field(
        default=None,
        pattern=(
            r"^(concrete_pour|waterproofing|mep|fire_stopping|handover|general"
            r"|structural|electrical|plumbing|fire_safety|concrete)$"
        ),
    )
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    location: str | None = Field(default=None, max_length=500)
    wbs_id: str | None = Field(default=None, max_length=36)
    inspector_id: str | None = Field(default=None, max_length=36)
    inspection_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    status: str | None = Field(
        default=None,
        pattern=r"^(scheduled|in_progress|completed|failed|cancelled)$",
    )
    result: str | None = Field(default=None, pattern=r"^(pass|fail|partial)$")
    checklist_data: list[ChecklistEntry] | None = None
    metadata: dict[str, Any] | None = None


class InspectionResponse(BaseModel):
    """Inspection returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    version: int = 1

    id: UUID
    project_id: UUID
    inspection_number: str
    inspection_type: str
    title: str
    description: str | None = None
    location: str | None = None
    wbs_id: str | None = None
    inspector_id: str | None = None
    # Who the inspector is, in words. ``inspector_id`` holds a contact id on
    # seeded rows, a user id when a picker wrote it and a typed name otherwise,
    # so the id alone cannot be shown to anybody - a register that printed it
    # raw put a bare UUID in the inspector column. Absent when the id resolves
    # to nothing, which tells the client to fall back to the stored value.
    inspector_name: str | None = None
    inspection_date: str | None = None
    status: str = "scheduled"
    result: str | None = None
    checklist_data: list[dict[str, Any]] = Field(default_factory=list)
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class InspectionListResponse(BaseModel):
    """One page of inspections plus the size of the whole set.

    ``total`` is the row count matching the filters, not the length of
    ``items``. A quality register that shows a page and calls it the register
    hides exactly the inspections nobody has looked at yet.
    """

    items: list[InspectionResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50
