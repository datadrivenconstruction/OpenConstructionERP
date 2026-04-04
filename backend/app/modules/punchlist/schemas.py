"""Punch List Pydantic schemas — request/response models.

Defines create, update, response, status transition, and summary schemas
for punch list items.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── Punch Item schemas ──────────────────────────────────────────────────


class PunchItemCreate(BaseModel):
    """Create a new punch list item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    title: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    document_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    location_x: float | None = Field(default=None, ge=0.0, le=1.0)
    location_y: float | None = Field(default=None, ge=0.0, le=1.0)
    priority: str = Field(
        default="medium",
        pattern=r"^(low|medium|high|critical)$",
    )
    assigned_to: str | None = None
    due_date: datetime | None = None
    category: str | None = Field(
        default=None,
        pattern=r"^(structural|mechanical|electrical|architectural|fire_safety|plumbing|finishing)$",
    )
    trade: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PunchItemUpdate(BaseModel):
    """Partial update for a punch list item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    document_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    location_x: float | None = Field(default=None, ge=0.0, le=1.0)
    location_y: float | None = Field(default=None, ge=0.0, le=1.0)
    priority: str | None = Field(
        default=None,
        pattern=r"^(low|medium|high|critical)$",
    )
    assigned_to: str | None = None
    due_date: datetime | None = None
    category: str | None = Field(
        default=None,
        pattern=r"^(structural|mechanical|electrical|architectural|fire_safety|plumbing|finishing)$",
    )
    trade: str | None = Field(default=None, max_length=100)
    resolution_notes: str | None = None
    metadata: dict[str, Any] | None = None


class PunchItemResponse(BaseModel):
    """Punch list item returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    title: str
    description: str = ""
    document_id: str | None = None
    page: int | None = None
    location_x: float | None = None
    location_y: float | None = None
    priority: str = "medium"
    status: str = "open"
    assigned_to: str | None = None
    due_date: datetime | None = None
    category: str | None = None
    trade: str | None = None
    photos: list[str] = Field(default_factory=list)
    resolution_notes: str | None = None
    resolved_at: datetime | None = None
    verified_at: datetime | None = None
    verified_by: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Status transition schema ────────────────────────────────────────────


class PunchStatusTransition(BaseModel):
    """Request body for a status transition."""

    model_config = ConfigDict(str_strip_whitespace=True)

    new_status: str = Field(
        ...,
        pattern=r"^(open|in_progress|resolved|verified|closed)$",
    )
    notes: str | None = None


# ── Summary schema ──────────────────────────────────────────────────────


class PunchListSummary(BaseModel):
    """Aggregated punch list stats for a project."""

    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_priority: dict[str, int] = Field(default_factory=dict)
    overdue: int = 0
