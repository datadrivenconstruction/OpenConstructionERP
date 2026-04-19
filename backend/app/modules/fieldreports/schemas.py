"""Field Reports Pydantic schemas — request/response models.

Defines create, update, response, and summary schemas
for field reports.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Bound ints at PostgreSQL INT4 max.
_INT32_MAX = 2_147_483_647

# ── Workforce entry ────────────────────────────────────────────────────


class WorkforceEntry(BaseModel):
    """A single workforce entry: trade + count + hours."""

    model_config = ConfigDict(extra="ignore")

    trade: str = Field(..., min_length=1, max_length=100)
    count: int = Field(..., ge=0, le=_INT32_MAX)
    hours: float = Field(..., ge=0.0, le=1e6, allow_inf_nan=False)


# ── Create ─────────────────────────────────────────────────────────────


class FieldReportCreate(BaseModel):
    """Create a new field report."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

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
    temperature_c: float | None = Field(default=None, ge=-100.0, le=100.0, allow_inf_nan=False)
    wind_speed: str | None = Field(default=None, max_length=50)
    precipitation: str | None = Field(default=None, max_length=100)
    humidity: int | None = Field(default=None, ge=0, le=100)
    workforce: list[WorkforceEntry] = Field(default_factory=list, max_length=1000)
    equipment_on_site: list[str] = Field(default_factory=list, max_length=1000)
    work_performed: str = Field(default="", max_length=10000)
    delays: str | None = Field(default=None, max_length=5000)
    delay_hours: float = Field(default=0.0, ge=0.0, le=1e4, allow_inf_nan=False)
    visitors: str | None = Field(default=None, max_length=2000)
    deliveries: str | None = Field(default=None, max_length=5000)
    safety_incidents: str | None = Field(default=None, max_length=5000)
    materials_used: list[str] = Field(default_factory=list, max_length=1000)
    photos: list[str] = Field(default_factory=list, max_length=1000)
    notes: str | None = Field(default=None, max_length=5000)
    signature_by: str | None = Field(default=None, max_length=255)
    signature_data: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Optional coordinates for auto-fetching weather from OpenWeatherMap
    lat: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    lon: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)


# ── Update ─────────────────────────────────────────────────────────────


class FieldReportUpdate(BaseModel):
    """Partial update for a field report."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    report_date: date | None = None
    report_type: str | None = Field(
        default=None,
        pattern=r"^(daily|inspection|safety|concrete_pour)$",
    )
    weather_condition: str | None = Field(
        default=None,
        pattern=r"^(clear|cloudy|rain|snow|fog|storm)$",
    )
    temperature_c: float | None = Field(default=None, ge=-100.0, le=100.0, allow_inf_nan=False)
    wind_speed: str | None = Field(default=None, max_length=50)
    precipitation: str | None = Field(default=None, max_length=100)
    humidity: int | None = Field(default=None, ge=0, le=100)
    workforce: list[WorkforceEntry] | None = Field(default=None, max_length=1000)
    equipment_on_site: list[str] | None = Field(default=None, max_length=1000)
    work_performed: str | None = Field(default=None, max_length=10000)
    delays: str | None = Field(default=None, max_length=5000)
    delay_hours: float | None = Field(default=None, ge=0.0, le=1e4, allow_inf_nan=False)
    visitors: str | None = Field(default=None, max_length=2000)
    deliveries: str | None = Field(default=None, max_length=5000)
    safety_incidents: str | None = Field(default=None, max_length=5000)
    materials_used: list[str] | None = Field(default=None, max_length=1000)
    photos: list[str] | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=5000)
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
    document_ids: list[str] = Field(default_factory=list)
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


# ── Link documents schema ─────────────────────────────────────────────


class LinkDocumentsRequest(BaseModel):
    """Request body for linking documents to a field report."""

    model_config = ConfigDict(str_strip_whitespace=True)

    document_ids: list[str] = Field(..., min_length=1, description="List of document UUIDs to link")


class LinkedDocumentResponse(BaseModel):
    """Minimal document reference returned from the linked-documents endpoint."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    name: str
    category: str = "other"
    file_size: int = 0
    mime_type: str = ""


# ── Site Workforce Log schemas ────────────────────────────────────────


class SiteWorkforceLogCreate(BaseModel):
    """Create a workforce log entry."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    field_report_id: UUID
    worker_type: str = Field(..., min_length=1, max_length=100)
    company: str | None = Field(default=None, max_length=255)
    headcount: int = Field(default=0, ge=0, le=_INT32_MAX)
    hours_worked: str = Field(default="0", max_length=10)
    overtime_hours: str = Field(default="0", max_length=10)
    wbs_id: str | None = Field(default=None, max_length=36)
    cost_category: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SiteWorkforceLogUpdate(BaseModel):
    """Partial update for a workforce log entry."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    worker_type: str | None = Field(default=None, min_length=1, max_length=100)
    company: str | None = Field(default=None, max_length=255)
    headcount: int | None = Field(default=None, ge=0, le=_INT32_MAX)
    hours_worked: str | None = Field(default=None, max_length=10)
    overtime_hours: str | None = Field(default=None, max_length=10)
    wbs_id: str | None = Field(default=None, max_length=36)
    cost_category: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] | None = None


class SiteWorkforceLogResponse(BaseModel):
    """Workforce log entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    field_report_id: UUID
    worker_type: str
    company: str | None
    headcount: int
    hours_worked: str
    overtime_hours: str
    wbs_id: str | None
    cost_category: str | None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Site Equipment Log schemas ────────────────────────────────────────


class SiteEquipmentLogCreate(BaseModel):
    """Create an equipment log entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    field_report_id: UUID
    equipment_description: str = Field(..., min_length=1, max_length=500)
    equipment_type: str | None = Field(default=None, max_length=100)
    hours_operational: str = Field(default="0", max_length=10)
    hours_standby: str = Field(default="0", max_length=10)
    hours_breakdown: str = Field(default="0", max_length=10)
    operator_name: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SiteEquipmentLogUpdate(BaseModel):
    """Partial update for an equipment log entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    equipment_description: str | None = Field(default=None, min_length=1, max_length=500)
    equipment_type: str | None = Field(default=None, max_length=100)
    hours_operational: str | None = Field(default=None, max_length=10)
    hours_standby: str | None = Field(default=None, max_length=10)
    hours_breakdown: str | None = Field(default=None, max_length=10)
    operator_name: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] | None = None


class SiteEquipmentLogResponse(BaseModel):
    """Equipment log entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    field_report_id: UUID
    equipment_description: str
    equipment_type: str | None
    hours_operational: str
    hours_standby: str
    hours_breakdown: str
    operator_name: str | None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime
