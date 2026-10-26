# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Time clock request and response schemas​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

Coordinates travel as plain floats (WGS84 degrees), distances in metres and
hours as Decimal strings, like every other hours figure in field time.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

_SHAPE_PATTERN = "^(circle|polygon)$"
_KIND_PATTERN = "^(in|out)$"


class GeofenceBase(BaseModel):
    """Fields shared by create and response."""

    name: str = Field(default="", max_length=200)
    shape: str = Field(default="circle", pattern=_SHAPE_PATTERN)
    center_lat: float | None = Field(default=None, ge=-90, le=90)
    center_lng: float | None = Field(default=None, ge=-180, le=180)
    radius_m: float | None = Field(default=None, gt=0, le=50_000)
    polygon: list[tuple[float, float]] = Field(default_factory=list, max_length=500)
    tolerance_m: float = Field(default=0, ge=0, le=5_000)
    supervisor_user_ids: list[UUID] = Field(default_factory=list, max_length=50)
    default_cost_code: str = Field(default="", max_length=100)
    active: bool = True


class GeofenceCreate(GeofenceBase):
    """Create a site geofence on a project."""

    project_id: UUID


class GeofenceUpdate(BaseModel):
    """Partial update of a geofence; omitted fields stay as they are."""

    name: str | None = Field(default=None, max_length=200)
    shape: str | None = Field(default=None, pattern=_SHAPE_PATTERN)
    center_lat: float | None = Field(default=None, ge=-90, le=90)
    center_lng: float | None = Field(default=None, ge=-180, le=180)
    radius_m: float | None = Field(default=None, gt=0, le=50_000)
    polygon: list[tuple[float, float]] | None = Field(default=None, max_length=500)
    tolerance_m: float | None = Field(default=None, ge=0, le=5_000)
    supervisor_user_ids: list[UUID] | None = Field(default=None, max_length=50)
    default_cost_code: str | None = Field(default=None, max_length=100)
    active: bool | None = None


class GeofenceResponse(GeofenceBase):
    """A stored geofence."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime


class ClockSettingsIn(BaseModel):
    """Per-project time clock settings."""

    project_id: UUID
    enabled: bool = True
    retention_days: int = Field(default=90, ge=1, le=3650)
    default_break_minutes: int = Field(default=0, ge=0, le=240)


class ClockSettingsOut(ClockSettingsIn):
    """Settings as stored, plus the consent text version workers agree to."""

    consent_text_version: str = "1"


class ClockConsentIn(BaseModel):
    """Record or withdraw a worker's consent to position capture."""

    project_id: UUID
    resource_id: UUID
    granted: bool
    text_version: str = Field(default="1", max_length=20)


class ClockConsentOut(BaseModel):
    """A worker's consent state on a project."""

    project_id: UUID
    resource_id: UUID
    granted: bool
    granted_at: datetime | None = None
    withdrawn_at: datetime | None = None
    text_version: str = "1"


class ClockEventCreate(BaseModel):
    """A clock-in or clock-out with the position read at the tap."""

    project_id: UUID
    resource_id: UUID
    kind: str = Field(pattern=_KIND_PATTERN)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100_000)
    # Captured on the device; absent means "now" on the server.
    occurred_at: datetime | None = None
    client_op_id: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=2000)


class ClockDecision(BaseModel):
    """A supervisor's approval or rejection of a flagged clock."""

    reason: str = Field(min_length=3, max_length=2000)


class ClockEventResponse(BaseModel):
    """A stored clock event."""

    id: UUID
    project_id: UUID
    resource_id: UUID
    resource_name: str = ""
    kind: str
    occurred_at: datetime
    latitude: float | None = None
    longitude: float | None = None
    accuracy_m: float | None = None
    geofence_id: UUID | None = None
    geofence_name: str | None = None
    inside: bool = True
    distance_m: float | None = None
    approval_status: str
    approval_reason: str | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    pair_event_id: UUID | None = None
    timesheet_id: UUID | None = None
    position_purged: bool = False
    note: str | None = None
    created_at: datetime


class ClockEventListResponse(BaseModel):
    """A page of clock events."""

    items: list[ClockEventResponse]
    total: int


class CrewSkip(BaseModel):
    """A crew member the crew clock could not clock, and why."""

    resource_id: UUID
    code: str


class CrewClockResponse(BaseModel):
    """The events a crew clock recorded and the members it skipped."""

    events: list[ClockEventResponse]
    skipped: list[CrewSkip]


class OnSiteWorker(BaseModel):
    """A worker with an open shift right now."""

    resource_id: UUID
    resource_name: str = ""
    clocked_in_at: datetime
    inside: bool
    event_id: UUID


class ClockStatusResponse(BaseModel):
    """Who is on site now, for the field screen and the dashboard widget."""

    project_id: UUID
    on_site: list[OnSiteWorker]
    on_site_count: int
    pending_approvals: int
    missing_clock_outs: int
    today_hours: str


class BuildTimesheetRequest(BaseModel):
    """Build (or refresh) the draft timesheet of one day from its clock shifts."""

    project_id: UUID
    date: date_type


class PurgeResult(BaseModel):
    """How many stored positions the retention purge erased."""

    purged: int


class ClockLabourCost(BaseModel):
    """Approved field labour hours and cost in a period (for CVR / cost control)."""

    project_id: UUID
    date_from: date_type | None = None
    date_to: date_type | None = None
    labour_hours: str
    labour_cost: str
    currency: str
    timesheets: int
    from_clock_hours: str
