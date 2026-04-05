"""Field Reports Pydantic schemas — request/response models.

Defines create, update, response, and summary schemas
for field reports.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── Workforce entry ────────────────────────────────────────────────────


class WorkforceEntry(BaseModel):
    """A single workforce entry: trade + count + hours."""

    trade: str = Field(..., min_length=1, max_length=100)
    count: int = Field(..., ge=0)
    hours: float = Field(..., ge=0.0)


# ── Create ─────────────────────────────────────────────────────────────


class FieldReportCreate(BaseModel):
    """Create a new field report."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    report_date: date
    report_type: str = Field(
        default="daily",
        pattern=r"^(daily|inspection|safety|concrete_pour)$",
    )
    weather_condition: str = Field(
        default="clear",
        pattern=r"^(clear|cloudy|rain|snow|fog|storm)$",
    )
    temperature_c: float | None = None
    wind_speed: str | None = Field(default=None, max_length=50)
    precipitation: str | None = Field(default=None, max_length=100)
    humidity: int | None = Field(default=None, ge=0, le=100)
    workforce: list[WorkforceEntry] = Field(default_factory=list)
    equipment_on_site: list[str] = Field(default_factory=list)
    work_performed: str = ""
    delays: str | None = None
    delay_hours: float = Field(default=0.0, ge=0.0)
    visitors: str | None = None
    deliveries: str | None = None
    safety_incidents: str | None = None
    materials_used: list[str] = Field(default_factory=list)
    photos: list[str] = Field(default_factory=list)
    notes: str | None = None
    signature_by: str | None = Field(default=None, max_length=255)
    signature_data: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Update ─────────────────────────────────────────────────────────────


class FieldReportUpdate(BaseModel):
    """Partial update for a field report."""

    model_config = ConfigDict(str_strip_whitespace=True)

    report_date: date | None = None
    report_type: str | None = Field(
        default=None,
        pattern=r"^(daily|inspection|safety|concrete_pour)$",
    )
    weather_condition: str | None = Field(
        default=None,
        pattern=r"^(clear|cloudy|rain|snow|fog|storm)$",
    )
    temperature_c: float | None = None
    wind_speed: str | None = Field(default=None, max_length=50)
    precipitation: str | None = Field(default=None, max_length=100)
    humidity: int | None = Field(default=None, ge=0, le=100)
    workforce: list[WorkforceEntry] | None = None
    equipment_on_site: list[str] | None = None
    work_performed: str | None = None
    delays: str | None = None
    delay_hours: float | None = Field(default=None, ge=0.0)
    visitors: str | None = None
    deliveries: str | None = None
    safety_incidents: str | None = None
    materials_used: list[str] | None = None
    photos: list[str] | None = None
    notes: str | None = None
    signature_by: str | None = Field(default=None, max_length=255)
    signature_data: str | None = None
    metadata: dict[str, Any] | None = None


# ── Response ───────────────────────────────────────────────────────────


class FieldReportResponse(BaseModel):
    """Field report returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    report_date: date
    report_type: str = "daily"
    weather_condition: str = "clear"
    temperature_c: float | None = None
    wind_speed: str | None = None
    precipitation: str | None = None
    humidity: int | None = None
    workforce: list[dict[str, Any]] = Field(default_factory=list)
    equipment_on_site: list[str] = Field(default_factory=list)
    work_performed: str = ""
    delays: str | None = None
    delay_hours: float = 0.0
    visitors: str | None = None
    deliveries: str | None = None
    safety_incidents: str | None = None
    materials_used: list[str] = Field(default_factory=list)
    photos: list[str] = Field(default_factory=list)
    notes: str | None = None
    signature_by: str | None = None
    signature_data: str | None = None
    status: str = "draft"
    approved_by: str | None = None
    approved_at: datetime | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Summary ────────────────────────────────────────────────────────────


class FieldReportSummary(BaseModel):
    """Aggregated field report stats for a project."""

    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)
    total_workforce_hours: float = 0.0
    total_delay_hours: float = 0.0
