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
    entity_id: str | None = Field(default=None, max_length=36)
    notes: str | None = Field(default=None, max_length=5000)


class ActionItemEntry(BaseModel):
    """A single action item."""

    description: str = Field(..., min_length=1, max_length=1000)
    owner_id: str | None = Field(default=None, max_length=36)
    due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
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
    chairperson_id: str | None = Field(default=None, max_length=36)
    attendees: list[AttendeeEntry] = Field(default_factory=list)
    agenda_items: list[AgendaItemEntry] = Field(default_factory=list)
    action_items: list[ActionItemEntry] = Field(default_factory=list)
    minutes: str | None = Field(default=None, max_length=50000)
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
    chairperson_id: str | None = Field(default=None, max_length=36)
    attendees: list[AttendeeEntry] | None = None
    agenda_items: list[AgendaItemEntry] | None = None
    action_items: list[ActionItemEntry] | None = None
    minutes: str | None = Field(default=None, max_length=50000)
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


# ── Stats ────────────────────────────────────────────────────────────────


class MeetingStatsResponse(BaseModel):
    """Aggregate statistics for meetings within a project."""

    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)
    open_action_items_count: int = 0
    next_meeting_date: str | None = None


class OpenActionItemResponse(BaseModel):
    """An open action item extracted from a meeting's JSON action_items array."""

    meeting_id: UUID
    meeting_number: str
    meeting_title: str
    meeting_date: str
    description: str
    owner_id: str | None = None
    due_date: str | None = None


# ── Import Preview ──────────────────────────────────────────────────────


class ImportPreviewAttendee(BaseModel):
    """Attendee extracted from transcript for preview."""

    name: str
    company: str = ""
    role: str = ""


class ImportPreviewActionItem(BaseModel):
    """Action item extracted from transcript for preview."""

    description: str
    owner: str = "TBD"
    due_date: str | None = None


class ImportPreviewDecision(BaseModel):
    """Decision extracted from transcript for preview."""

    decision: str
    made_by: str = ""


class ImportPreviewResponse(BaseModel):
    """Preview of data extracted from a meeting transcript before creating the meeting.

    Returned when the import-summary endpoint is called with preview=true.
    Allows the user to review and edit extracted data before confirming creation.
    """

    title: str
    meeting_type: str = "progress"
    source: str = "other"
    summary: str = ""
    key_topics: list[str] = Field(default_factory=list)
    attendees: list[ImportPreviewAttendee] = Field(default_factory=list)
    action_items: list[ImportPreviewActionItem] = Field(default_factory=list)
    decisions: list[ImportPreviewDecision] = Field(default_factory=list)
    agenda_items: list[dict[str, Any]] = Field(default_factory=list)
    minutes: str = ""
    ai_enhanced: bool = False
    segments_parsed: int = 0
