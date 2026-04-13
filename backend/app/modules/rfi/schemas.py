"""RFI Pydantic schemas — request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RFICreate(BaseModel):
    """Create a new RFI."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    subject: str = Field(..., min_length=1, max_length=500)
    question: str = Field(..., min_length=1, max_length=10000)
    raised_by: UUID | None = None  # Auto-filled from authenticated user if not provided
    assigned_to: str | None = Field(default=None, max_length=36)
    status: str = Field(
        default="draft",
        pattern=r"^(draft|open|answered|closed|void)$",
    )
    ball_in_court: str | None = Field(default=None, max_length=100)
    cost_impact: bool = False
    cost_impact_value: str | None = Field(default=None, max_length=50)
    schedule_impact: bool = False
    schedule_impact_days: int | None = Field(default=None, ge=0)
    date_required: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    response_due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    linked_drawing_ids: list[str] = Field(default_factory=list)
    change_order_id: str | None = Field(default=None, max_length=36)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RFIUpdate(BaseModel):
    """Partial update for an RFI."""

    model_config = ConfigDict(str_strip_whitespace=True)

    subject: str | None = Field(default=None, min_length=1, max_length=500)
    question: str | None = Field(default=None, min_length=1, max_length=10000)
    assigned_to: str | None = Field(default=None, max_length=36)
    status: str | None = Field(
        default=None,
        pattern=r"^(draft|open|answered|closed|void)$",
    )
    ball_in_court: str | None = Field(default=None, max_length=100)
    cost_impact: bool | None = None
    cost_impact_value: str | None = Field(default=None, max_length=50)
    schedule_impact: bool | None = None
    schedule_impact_days: int | None = Field(default=None, ge=0)
    date_required: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    response_due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    linked_drawing_ids: list[str] | None = None
    change_order_id: str | None = Field(default=None, max_length=36)
    metadata: dict[str, Any] | None = None


class RFIRespondRequest(BaseModel):
    """Request body for responding to an RFI."""

    official_response: str = Field(..., min_length=1, max_length=10000)


class RFIResponse(BaseModel):
    """RFI returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    rfi_number: str
    subject: str
    question: str
    raised_by: UUID
    assigned_to: str | None = None
    status: str = "draft"
    ball_in_court: str | None = None
    official_response: str | None = None
    responded_by: str | None = None
    responded_at: str | None = None
    cost_impact: bool = False
    cost_impact_value: str | None = None
    schedule_impact: bool = False
    schedule_impact_days: int | None = None
    date_required: str | None = None
    response_due_date: str | None = None
    linked_drawing_ids: list[str] = Field(default_factory=list)
    change_order_id: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # Computed fields
    is_overdue: bool = Field(
        default=False,
        description="True when status is open/draft and response_due_date is past today",
    )
    days_open: int = Field(
        default=0,
        description="Number of days from created_at to now (or responded_at if answered/closed)",
    )


class RFIStatsResponse(BaseModel):
    """Summary statistics for RFIs in a project."""

    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    open: int = 0
    overdue: int = 0
    avg_days_to_response: float | None = Field(
        default=None,
        description="Average days from creation to official response (answered/closed RFIs only)",
    )
    cost_impact_count: int = 0
    schedule_impact_count: int = 0
