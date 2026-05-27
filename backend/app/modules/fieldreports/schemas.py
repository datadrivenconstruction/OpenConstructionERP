"""‌⁠‍Field Reports Pydantic schemas — request/response models.

Defines create, update, response, and summary schemas
for field reports.
"""

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

# Bound ints at PostgreSQL INT4 max.
_INT32_MAX = 2_147_483_647

# ``signature_data`` is a base64 data URI of a hand-drawn signature
# image. A typical 600×200 PNG signature is ~10 KB base64-encoded.
# Cap at 2 MB so a single field report can't blow the request body up
# into the megabytes (and so a malicious client can't dump arbitrary
# blobs into the signature column). Anything > 2 MB is rejected at the
# schema layer before the row is built — this also caps the eventual
# PDF export size.
_SIGNATURE_MAX_LEN = 2 * 1024 * 1024


def _check_signature_data(value: str | None) -> str | None:
    """Sniff the signature payload — accept only base64 image data URIs.

    A real signature pad emits ``data:image/png;base64,...`` (Chrome /
    Firefox / Safari all default to PNG). Allow PNG / JPEG / WebP /
    SVG+xml, plus a permissive empty-string fallback. Reject anything
    else outright so the column doesn't become a free-text dumping
    ground for inline scripts or arbitrary binaries.
    """
    if value is None or value == "":
        return value
    if len(value) > _SIGNATURE_MAX_LEN:
        raise ValueError(f"signature_data exceeds maximum size ({_SIGNATURE_MAX_LEN} bytes)")
    if not value.startswith("data:image/"):
        raise ValueError("signature_data must be a base64-encoded image data URI (data:image/png;base64,...)")
    # Cheap allow-list of the MIME types signature pads actually emit.
    head = value[:64].lower()
    allowed_prefixes = (
        "data:image/png",
        "data:image/jpeg",
        "data:image/jpg",
        "data:image/webp",
        "data:image/svg+xml",
    )
    if not any(head.startswith(p) for p in allowed_prefixes):
        raise ValueError("signature_data MIME type is not allowed; use png / jpeg / webp / svg+xml")
    return value


SignatureData = Annotated[str | None, AfterValidator(_check_signature_data)]

FieldType = Literal["text", "textarea", "number", "select", "date", "checkbox"]

# ── Workforce entry ────────────────────────────────────────────────────


class WorkforceEntry(BaseModel):
    """‌⁠‍A single workforce entry: trade + count + hours."""

    model_config = ConfigDict(extra="ignore")

    trade: str = Field(..., min_length=1, max_length=100)
    count: int = Field(..., ge=0, le=_INT32_MAX)
    hours: float = Field(..., ge=0.0, le=1e6, allow_inf_nan=False)


# ── Create ─────────────────────────────────────────────────────────────


class FieldReportCreate(BaseModel):
    """‌⁠‍Create a new field report."""

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
    signature_data: SignatureData = None
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
    signature_data: SignatureData = None
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


# ── Report Template schemas ───────────────────────────────────────────


class TemplateFieldDefinition(BaseModel):
    """A single editable field in a report template."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    key: str = Field(..., min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_]+$")
    label: str = Field(..., min_length=1, max_length=200)
    type: FieldType = "text"
    required: bool = False
    options: list[str] = Field(default_factory=list, max_length=100)
    placeholder: str = Field(default="", max_length=300)
    help_text: str = Field(default="", max_length=500)


class FieldReportTemplateCreate(BaseModel):
    """Create a new (project-scoped) report template."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    report_type: str = Field(
        default="daily",
        pattern=r"^(daily|inspection|safety|concrete_pour)$",
    )
    fields: list[TemplateFieldDefinition] = Field(default_factory=list, max_length=100)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class FieldReportTemplateUpdate(BaseModel):
    """Partial update for a report template."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    report_type: str | None = Field(
        default=None,
        pattern=r"^(daily|inspection|safety|concrete_pour)$",
    )
    fields: list[TemplateFieldDefinition] | None = Field(default=None, max_length=100)
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


class FieldReportTemplateResponse(BaseModel):
    """Report template returned from the API.

    ``is_builtin`` flags the code-defined defaults — those have a
    synthetic string id (``builtin:<slug>``), are read-only, and are
    merged in by the service layer rather than stored as rows.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    project_id: str | None = None
    name: str
    description: str | None = None
    report_type: str = "daily"
    fields: list[TemplateFieldDefinition] = Field(default_factory=list)
    is_active: bool = True
    is_builtin: bool = False
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime | None = None
    updated_at: datetime | None = None
