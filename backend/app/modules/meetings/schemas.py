"""Meetings Pydantic schemas — request/response models.

Defines create, update, and response schemas for meetings.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Nested entry schemas ──────────────────────────────────────────────────


class AttendeeEntry(BaseModel):
    """A single attendee entry."""

    user_id: str | None = None
    name: str = Field(..., min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    status: str = Field(default="present", pattern=r"^(present|absent|excused)$")


class AgendaItemEntry(BaseModel):
    """A single agenda item."""

    number: str | None = Field(default=None, max_length=10)
    topic: str = Field(..., min_length=1, max_length=500)
    presenter: str | None = Field(default=None, max_length=200)
    entity_type: str | None = Field(default=None, max_length=50)
    entity_id: str | None = None
    notes: str | None = None


class ActionItemEntry(BaseModel):
    """A single action item."""

    description: str = Field(..., min_length=1, max_length=1000)
    owner_id: str | None = None
    due_date: str | None = Field(default=None, max_length=20)
    status: str = Field(default="open", pattern=r"^(open|completed|cancelled)$")


# ── Create ────────────────────────────────────────────────────────────────


class MeetingCreate(BaseModel):
    """Create a new meeting."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    meeting_type: str = Field(
        ...,
        pattern=r"^(progress|design|safety|subcontractor|kickoff|closeout)$",
    )
    title: str = Field(..., min_length=1, max_length=500)
    meeting_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    location: str | None = Field(default=None, max_length=500)
    chairperson_id: str | None = None
    attendees: list[AttendeeEntry] = Field(default_factory=list)
    agenda_items: list[AgendaItemEntry] = Field(default_factory=list)
    action_items: list[ActionItemEntry] = Field(default_factory=list)
    minutes: str | None = None
    status: str = Field(
        default="draft",
        pattern=r"^(draft|scheduled|in_progress|completed|cancelled)$",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Update ────────────────────────────────────────────────────────────────


class MeetingUpdate(BaseModel):
    """Partial update for a meeting."""

    model_config = ConfigDict(str_strip_whitespace=True)

    meeting_type: str | None = Field(
        default=None,
        pattern=r"^(progress|design|safety|subcontractor|kickoff|closeout)$",
    )
    title: str | None = Field(default=None, min_length=1, max_length=500)
    meeting_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    location: str | None = Field(default=None, max_length=500)
    chairperson_id: str | None = None
    attendees: list[AttendeeEntry] | None = None
    agenda_items: list[AgendaItemEntry] | None = None
    action_items: list[ActionItemEntry] | None = None
    minutes: str | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(draft|scheduled|in_progress|completed|cancelled)$",
    )
    metadata: dict[str, Any] | None = None


# ── Response ──────────────────────────────────────────────────────────────


class MeetingResponse(BaseModel):
    """Meeting returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    meeting_number: str
    meeting_type: str
    title: str
    meeting_date: str
    location: str | None = None
    chairperson_id: str | None = None
    attendees: list[dict[str, Any]] = Field(default_factory=list)
    agenda_items: list[dict[str, Any]] = Field(default_factory=list)
    action_items: list[dict[str, Any]] = Field(default_factory=list)
    minutes: str | None = None
    status: str = "draft"
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
