# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Safety Pydantic schemas - request/response models."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

# ── Incident schemas ─────────────────────────────────────────────────────


class CorrectiveActionEntry(BaseModel):
    """A corrective action within an incident."""

    description: str = Field(..., min_length=1, max_length=1000)
    responsible_id: str | None = None
    due_date: str | None = Field(default=None, max_length=20)
    status: str = Field(default="open", pattern=r"^(open|in_progress|completed)$")


class IncidentCreate(BaseModel):
    """Create a new safety incident."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    title: str = Field(default="", min_length=0, max_length=500)
    incident_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    location: str | None = Field(default=None, max_length=500)
    incident_type: str = Field(
        ...,
        pattern=r"^(injury|near_miss|property_damage|environmental|fire)$",
    )
    severity: str = Field(
        default="minor",
        pattern=r"^(minor|moderate|major|severe|critical)$",
    )
    description: str = Field(..., min_length=1, max_length=10000)
    injured_person_details: dict[str, Any] | None = None
    treatment_type: str | None = Field(
        default=None,
        pattern=r"^(first_aid|medical|hospital|fatality)$",
    )
    days_lost: int = Field(default=0, ge=0)
    root_cause: str | None = Field(default=None, max_length=5000)
    corrective_actions: list[CorrectiveActionEntry] = Field(default_factory=list)
    reported_to_regulator: bool = False
    status: str = Field(
        default="reported",
        pattern=r"^(reported|investigating|corrective_action|closed)$",
    )
    # WGS84 geo binding so the incident shows up as a pin on Geo Hub.
    # Optional - incidents without a map pin still work end-to-end.
    geo_lat: float | None = Field(default=None, ge=-90, le=90)
    geo_lon: float | None = Field(default=None, ge=-180, le=180)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IncidentUpdate(BaseModel):
    """Partial update for a safety incident."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=500)
    incident_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    location: str | None = Field(default=None, max_length=500)
    incident_type: str | None = Field(
        default=None,
        pattern=r"^(injury|near_miss|property_damage|environmental|fire)$",
    )
    severity: str | None = Field(
        default=None,
        pattern=r"^(minor|moderate|major|severe|critical)$",
    )
    description: str | None = Field(default=None, min_length=1, max_length=10000)
    injured_person_details: dict[str, Any] | None = None
    treatment_type: str | None = Field(
        default=None,
        pattern=r"^(first_aid|medical|hospital|fatality)$",
    )
    days_lost: int | None = Field(default=None, ge=0)
    root_cause: str | None = Field(default=None, max_length=5000)
    corrective_actions: list[CorrectiveActionEntry] | None = None
    reported_to_regulator: bool | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(reported|investigating|corrective_action|closed)$",
    )
    geo_lat: float | None = Field(default=None, ge=-90, le=90)
    geo_lon: float | None = Field(default=None, ge=-180, le=180)
    metadata: dict[str, Any] | None = None


class IncidentResponse(BaseModel):
    """Incident returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    incident_number: str
    title: str = ""
    incident_date: str
    location: str | None = None
    incident_type: str
    severity: str = "minor"
    description: str
    injured_person_details: dict[str, Any] | None = None
    treatment_type: str | None = None
    days_lost: int = 0
    root_cause: str | None = None
    corrective_actions: list[dict[str, Any]] = Field(default_factory=list)
    reported_to_regulator: bool = False
    status: str = "reported"
    geo_lat: float | None = None
    geo_lon: float | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    osha_recordable: bool = False
    osha_case_number: str | None = None
    days_away: int | None = None
    days_restricted: int | None = None
    root_cause_method: str | None = None
    root_cause_tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class IncidentListResponse(BaseModel):
    """One page of safety incidents plus the size of the matching set.

    ``total`` counts the rows the query matched, not the length of ``items``.
    The project, the incident type and the status filter are all applied before
    the count is taken, so a zero here means this question found nothing rather
    than the project holding nothing.

    Every reader of this route asks without a ``limit`` and so takes the default
    page of fifty. A project past its fiftieth incident was showing fifty and
    saying nothing, on a register whose whole point is that none of it goes
    unseen.
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[IncidentResponse]
    total: int
    offset: int
    limit: int


# ── Observation schemas ──────────────────────────────────────────────────


class ObservationCreate(BaseModel):
    """Create a new safety observation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    observation_type: str = Field(
        ...,
        pattern=r"^(positive|unsafe_act|unsafe_condition|near_miss)$",
    )
    description: str = Field(..., min_length=1, max_length=10000)
    location: str | None = Field(default=None, max_length=500)
    severity: int = Field(default=1, ge=1, le=5)
    likelihood: int = Field(default=1, ge=1, le=5)
    immediate_action: str | None = Field(default=None, max_length=5000)
    corrective_action: str | None = Field(default=None, max_length=5000)
    status: str = Field(default="open", pattern=r"^(open|in_progress|closed)$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ObservationUpdate(BaseModel):
    """Partial update for a safety observation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    observation_type: str | None = Field(
        default=None,
        pattern=r"^(positive|unsafe_act|unsafe_condition|near_miss)$",
    )
    description: str | None = Field(default=None, min_length=1, max_length=10000)
    location: str | None = Field(default=None, max_length=500)
    severity: int | None = Field(default=None, ge=1, le=5)
    likelihood: int | None = Field(default=None, ge=1, le=5)
    immediate_action: str | None = Field(default=None, max_length=5000)
    corrective_action: str | None = Field(default=None, max_length=5000)
    status: str | None = Field(default=None, pattern=r"^(open|in_progress|closed)$")
    metadata: dict[str, Any] | None = None


class ObservationResponse(BaseModel):
    """Observation returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    observation_number: str
    observation_type: str
    description: str
    location: str | None = None
    severity: int = 1
    likelihood: int = 1
    risk_score: int = 1
    risk_tier: str = "low"
    immediate_action: str | None = None
    corrective_action: str | None = None
    status: str = "open"
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Stats & Trends schemas ─────────────────────────────────────────────────


class SafetyStatsResponse(BaseModel):
    """Dashboard KPIs for a project's safety data."""

    total_incidents: int = 0
    total_observations: int = 0
    days_without_incident: int | None = Field(
        default=None,
        description=(
            "Calendar days since the last incident. None when there are no "
            "incidents, OR when incidents exist but none had a usable date "
            "(see days_without_incident_status to disambiguate)."
        ),
    )
    days_without_incident_status: str = Field(
        default="none",
        description=(
            "'none' = no incidents (genuinely clean); 'ok' = computed from a "
            "valid latest incident date; 'unconfirmed' = incidents exist but "
            "no parseable date, so the metric is NOT safe to display as a "
            "reassuring number."
        ),
    )
    unparseable_incident_dates: int = Field(
        default=0,
        description="Count of incidents whose stored date could not be parsed",
    )
    total_days_lost: int = 0
    recordable_incidents: int = Field(
        default=0,
        description="Incidents with treatment_type in (medical, hospital, fatality)",
    )
    ltifr: float | None = Field(
        default=None,
        description="Lost Time Injury Frequency Rate per 1M hours (needs man-hours in metadata)",
    )
    trir: float | None = Field(
        default=None,
        description="Total Recordable Incident Rate per 200k hours (needs man-hours in metadata)",
    )
    incidents_by_type: dict[str, int] = Field(default_factory=dict)
    incidents_by_status: dict[str, int] = Field(default_factory=dict)
    observations_by_risk_tier: dict[str, int] = Field(default_factory=dict)
    open_corrective_actions: int = 0


class SafetyTrendEntry(BaseModel):
    """A single time-period bucket in a safety trend."""

    period: str = Field(description="Period label, e.g. '2026-01' for monthly")
    incident_count: int = 0
    observation_count: int = 0
    days_lost: int = 0


class SafetyTrendsResponse(BaseModel):
    """Time-series safety data for charting."""

    period_type: str = Field(description="'monthly' or 'weekly'")
    entries: list[SafetyTrendEntry] = Field(default_factory=list)


# ── Extended trends (LTIFR/TRIR time series) ───────────────────────────────


class SafetyTrendEntryExtended(BaseModel):
    """A single period bucket carrying computed LTIFR/TRIR rates.

    ``ltifr``/``trir`` are ``None`` (not 0.0) when the period has no usable
    man-hours, mirroring :class:`SafetyStatsResponse`: a missing denominator
    is "not enough data", never a falsely-precise zero rate.
    """

    period: str = Field(description="Period label, e.g. '2026-01' for monthly")
    incident_count: int = 0
    observation_count: int = 0
    days_lost: int = 0
    ltifr: float | None = Field(
        default=None,
        description="Lost Time Injury Frequency Rate per 1M hours for this period",
    )
    trir: float | None = Field(
        default=None,
        description="Total Recordable Incident Rate per 200k hours for this period",
    )
    man_hours_total: float = Field(
        default=0.0,
        description="Sum of incident man_hours_total in this period (rate denominator)",
    )
    recordable_incidents: int = 0
    lost_time_incidents: int = 0


class SafetyTrendsExtendedResponse(BaseModel):
    """Rolling LTIFR/TRIR time series with a trend-direction heuristic."""

    period_type: str = Field(description="'monthly' or 'weekly'")
    entries: list[SafetyTrendEntryExtended] = Field(default_factory=list)
    rolling_12_month_ltifr: float | None = Field(
        default=None,
        description="Mean LTIFR across the trailing window of periods with a usable rate",
    )
    rolling_12_month_trir: float | None = Field(
        default=None,
        description="Mean TRIR across the trailing window of periods with a usable rate",
    )
    current_period_ltifr: float | None = Field(
        default=None,
        description="LTIFR of the most recent period (None when no man-hours)",
    )
    current_period_trir: float | None = Field(
        default=None,
        description="TRIR of the most recent period (None when no man-hours)",
    )
    trend_direction: str = Field(
        default="unknown",
        pattern=r"^(improving|stable|declining|unknown)$",
        description=(
            "3-period LTIFR slope heuristic: 'improving' (rate falling), "
            "'declining' (rate rising), 'stable', or 'unknown' (<3 usable periods)"
        ),
    )


class SafetyThresholdAlertResponse(BaseModel):
    """Current LTIFR/TRIR checked against configurable safe-baselines.

    Status bands per rate: ``green`` when current <= baseline, ``yellow`` when
    current is 120-150 percent of baseline, ``red`` when above 150 percent.
    ``unknown`` when the rate could not be computed (no man-hours).
    """

    current_ltifr: float | None = None
    current_trir: float | None = None
    baseline_ltifr: float
    baseline_trir: float
    ltifr_delta: float | None = Field(
        default=None,
        description="current_ltifr - baseline_ltifr (None when current is unknown)",
    )
    trir_delta: float | None = Field(
        default=None,
        description="current_trir - baseline_trir (None when current is unknown)",
    )
    ltifr_status: str = Field(default="unknown", pattern=r"^(green|yellow|red|unknown)$")
    trir_status: str = Field(default="unknown", pattern=r"^(green|yellow|red|unknown)$")
    message: str = Field(default="")


# -- Leading vs lagging safety indicators -----------------------------------
# Decimal rate fields are stored/computed as Decimal but emitted as plain
# decimal strings in JSON, mirroring the money serialisation used in
# app/modules/finance/schemas.py and app/modules/boq/schemas.py so a rate is
# never a lossy float on the wire.
def _serialise_rate(v: Decimal | None) -> str | None:
    """Emit a Decimal rate as a plain string, passing None through unchanged."""
    return None if v is None else str(v)


class LaggingIndicatorsResponse(BaseModel):
    """Lagging indicators - harm that already happened over the period."""

    total_incidents: int = 0
    recordable_incidents: int = 0
    lost_time_incidents: int = 0
    total_days_lost: int = 0
    total_hours_worked: Decimal = Field(
        default=Decimal("0"),
        description="Sum of incident man_hours_total in period (frequency-rate denominator)",
    )
    trir: Decimal | None = Field(
        default=None,
        description="Total Recordable Incident Rate per 200k hours, or null when no man-hours",
    )
    ltifr: Decimal | None = Field(
        default=None,
        description="Lost Time Injury Frequency Rate per 1M hours, or null when no man-hours",
    )
    severity_rate: Decimal | None = Field(
        default=None,
        description="Lost days per 1M hours, or null when no man-hours",
    )

    @field_serializer("total_hours_worked", "trir", "ltifr", "severity_rate")
    def _ser_rate(self, v: Decimal | None) -> str | None:
        return _serialise_rate(v)


class LeadingIndicatorsResponse(BaseModel):
    """Leading indicators - proactive prevention work done over the period."""

    near_misses_reported: int = Field(
        default=0,
        description="Near-miss incidents plus near-miss observations captured in period",
    )
    observations_total: int = 0
    observations_open: int = 0
    observations_closed: int = 0
    corrective_actions_total: int = 0
    corrective_actions_open: int = 0
    corrective_actions_closed: int = 0
    corrective_action_close_rate: Decimal | None = Field(
        default=None,
        description="Closed / total corrective actions as a 0..1 ratio, or null when there are none",
    )

    @field_serializer("corrective_action_close_rate")
    def _ser_rate(self, v: Decimal | None) -> str | None:
        return _serialise_rate(v)


class SafetyIndicatorsResponse(BaseModel):
    """Leading and lagging safety indicators for a project over a period."""

    project_id: UUID
    period_start: date | None = Field(
        default=None,
        description="Inclusive lower date bound applied, or null for all-time",
    )
    period_end: date | None = Field(
        default=None,
        description="Inclusive upper date bound (as-of cutoff) applied, or null for all-time",
    )
    leading: LeadingIndicatorsResponse = Field(default_factory=LeadingIndicatorsResponse)
    lagging: LaggingIndicatorsResponse = Field(default_factory=LaggingIndicatorsResponse)
