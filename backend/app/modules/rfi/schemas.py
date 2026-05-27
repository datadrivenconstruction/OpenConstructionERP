"""‌⁠‍RFI Pydantic schemas — request/response models."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _sanitise_rfi_text(value: str | None) -> str | None:
    """‌⁠‍Strip XSS payloads from RFI free-text fields (BUG-389).

    RFIs are often rendered in email digests (raw HTML) and PDF reports,
    so a ``<script>`` / event-handler payload smuggled into a subject
    would turn into a real XSS vector. Sanitise at the schema layer so
    the DB never stores the payload.
    """
    if value is None:
        return value
    from app.core.sanitize import strip_dangerous_html

    return strip_dangerous_html(value)


def _validate_cost_impact_value(value: str | None) -> str | None:
    """‌⁠‍Round-trip ``cost_impact_value`` through :class:`Decimal`.

    R5 / BUG-RFI-DEC: ``cost_impact_value`` is stored as a free-form
    string so the DB layer never accumulates IEEE-754 drift. The schema
    still has to reject garbage (``"definitely cheap"``) up front so the
    variation builder (which feeds the value into ChangeOrder.cost_impact)
    never sees a non-numeric blob.

    Empty / ``None`` passes through. Otherwise we parse via Decimal and
    re-serialise the canonical form so storage is always a clean number
    string. Inf / NaN are rejected because Decimal accepts them but they
    cannot become a valid currency amount.
    """
    if value is None or value == "":
        return value
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("cost_impact_value must be a numeric amount") from exc
    if not parsed.is_finite():
        raise ValueError("cost_impact_value must be a finite number")
    return format(parsed, "f")


class RFICreate(BaseModel):
    """‌⁠‍Create a new RFI."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    subject: str = Field(..., min_length=1, max_length=500)
    question: str = Field(..., min_length=1, max_length=10000)

    @field_validator("subject", "question", mode="after")
    @classmethod
    def _sanitise(cls, v: str) -> str:
        return _sanitise_rfi_text(v) or ""

    raised_by: UUID | None = None  # Auto-filled from authenticated user if not provided
    assigned_to: str | None = Field(default=None, max_length=36)
    status: str = Field(
        default="draft",
        pattern=r"^(draft|open|answered|closed|void)$",
    )
    ball_in_court: str | None = Field(default=None, max_length=100)
    cost_impact: bool = False
    cost_impact_value: str | None = Field(default=None, max_length=50)

    @field_validator("cost_impact_value", mode="after")
    @classmethod
    def _validate_cost(cls, v: str | None) -> str | None:
        return _validate_cost_impact_value(v)

    schedule_impact: bool = False
    schedule_impact_days: int | None = Field(default=None, ge=0)
    date_required: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    response_due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    linked_drawing_ids: list[str] = Field(default_factory=list)
    change_order_id: str | None = Field(default=None, max_length=36)
    priority: str | None = Field(
        default=None,
        pattern=r"^(low|normal|high|critical)$",
        description="Priority — low | normal | high | critical.",
    )
    discipline: str | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RFIUpdate(BaseModel):
    """Partial update for an RFI."""

    model_config = ConfigDict(str_strip_whitespace=True)

    subject: str | None = Field(default=None, min_length=1, max_length=500)
    question: str | None = Field(default=None, min_length=1, max_length=10000)

    @field_validator("subject", "question", mode="after")
    @classmethod
    def _sanitise(cls, v: str | None) -> str | None:
        return _sanitise_rfi_text(v)

    assigned_to: str | None = Field(default=None, max_length=36)
    status: str | None = Field(
        default=None,
        pattern=r"^(draft|open|answered|closed|void)$",
    )
    ball_in_court: str | None = Field(default=None, max_length=100)
    cost_impact: bool | None = None
    cost_impact_value: str | None = Field(default=None, max_length=50)

    @field_validator("cost_impact_value", mode="after")
    @classmethod
    def _validate_cost(cls, v: str | None) -> str | None:
        return _validate_cost_impact_value(v)

    schedule_impact: bool | None = None
    schedule_impact_days: int | None = Field(default=None, ge=0)
    date_required: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    response_due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    linked_drawing_ids: list[str] | None = None
    change_order_id: str | None = Field(default=None, max_length=36)
    priority: str | None = Field(
        default=None,
        pattern=r"^(low|normal|high|critical)$",
        description="Priority — low | normal | high | critical.",
    )
    discipline: str | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None


class RFIRespondRequest(BaseModel):
    """Request body for responding to an RFI."""

    official_response: str = Field(..., min_length=1, max_length=10000)

    @field_validator("official_response", mode="after")
    @classmethod
    def _sanitise(cls, v: str) -> str:
        return _sanitise_rfi_text(v) or ""


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
    attachments: list[str] = Field(
        default_factory=list,
        description="Server-derived relative paths under uploads/rfi/attachments/.",
    )
    change_order_id: str | None = None
    created_by: str | None = None
    priority: str | None = None
    discipline: str | None = None
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
