# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Equipment Pydantic schemas - request/response models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

# Reused enum-like patterns
_ISO_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

# ── EquipmentType ────────────────────────────────────────────────────────


class EquipmentTypeCreate(BaseModel):
    """Create a new equipment type catalog entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(default="other", max_length=50)
    default_service_interval_hours: Decimal | None = None
    default_service_interval_km: Decimal | None = None
    default_inspection_interval_days: int | None = Field(default=None, ge=1)
    description: str | None = None


class EquipmentTypeUpdate(BaseModel):
    """Partial update for an equipment type."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=50)
    default_service_interval_hours: Decimal | None = None
    default_service_interval_km: Decimal | None = None
    default_inspection_interval_days: int | None = Field(default=None, ge=1)
    description: str | None = None


class EquipmentTypeResponse(BaseModel):
    """Equipment type returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    category: str
    default_service_interval_hours: Decimal | None = None
    default_service_interval_km: Decimal | None = None
    default_inspection_interval_days: int | None = None
    description: str | None = None


class EquipmentTypeListResponse(BaseModel):
    """Every equipment type, and the count of them.

    Unlike the registers, this route takes no offset or limit: the repository
    reads the whole taxonomy in one query, so ``total`` always equals
    ``len(items)`` and ``limit`` reports the count rather than a cap. That is
    the honest answer for a list that cannot truncate, and it is why a reader
    of this endpoint will never see a truncation notice. It is enveloped for
    the same reason the registers are, so no caller has to know which list
    routes describe themselves and which do not.
    """

    items: list[EquipmentTypeResponse]
    total: int
    offset: int = 0
    limit: int


# ── Equipment ────────────────────────────────────────────────────────────


class EquipmentCreate(BaseModel):
    """Create a new equipment unit."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    type_code: str = Field(default="other", max_length=50)
    manufacturer: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=255)
    serial: str | None = Field(default=None, max_length=255)
    year: int | None = Field(default=None, ge=1900, le=2100)
    ownership: str = Field(
        default="owned",
        pattern=r"^(owned|rented|leased)$",
    )
    status: str = Field(
        default="active",
        pattern=r"^(active|under_maintenance|decommissioned|reserved)$",
    )
    location_lat: float | None = Field(default=None, ge=-90, le=90)
    location_lng: float | None = Field(default=None, ge=-180, le=180)
    hour_meter: Decimal = Decimal("0")
    odometer_km: Decimal = Decimal("0")
    purchase_date: str | None = Field(default=None, pattern=_ISO_DATE_PATTERN)
    purchase_value: Decimal | None = None
    depreciation_method: str = Field(default="linear", max_length=30)
    useful_life_years: int | None = Field(default=None, ge=1, le=100)
    residual_value: Decimal | None = None
    currency: str = Field(default="", max_length=3)
    notes: str | None = None


class EquipmentUpdate(BaseModel):
    """Partial update for an equipment unit."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    type_code: str | None = Field(default=None, max_length=50)
    manufacturer: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=255)
    serial: str | None = Field(default=None, max_length=255)
    year: int | None = Field(default=None, ge=1900, le=2100)
    ownership: str | None = Field(default=None, pattern=r"^(owned|rented|leased)$")
    status: str | None = Field(
        default=None,
        pattern=r"^(active|under_maintenance|decommissioned|reserved)$",
    )
    location_lat: float | None = Field(default=None, ge=-90, le=90)
    location_lng: float | None = Field(default=None, ge=-180, le=180)
    hour_meter: Decimal | None = None
    odometer_km: Decimal | None = None
    purchase_date: str | None = Field(default=None, pattern=_ISO_DATE_PATTERN)
    purchase_value: Decimal | None = None
    depreciation_method: str | None = Field(default=None, max_length=30)
    useful_life_years: int | None = Field(default=None, ge=1, le=100)
    residual_value: Decimal | None = None
    currency: str | None = Field(default=None, max_length=3)
    notes: str | None = None


class EquipmentResponse(BaseModel):
    """Equipment unit returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    code: str
    name: str
    type_code: str
    manufacturer: str | None = None
    model: str | None = None
    serial: str | None = None
    year: int | None = None
    ownership: str
    status: str
    location_lat: float | None = None
    location_lng: float | None = None
    hour_meter: Decimal = Decimal("0")
    odometer_km: Decimal = Decimal("0")
    last_telemetry_at: datetime | None = None
    purchase_date: str | None = None
    purchase_value: Decimal | None = None
    depreciation_method: str = "linear"
    useful_life_years: int | None = None
    residual_value: Decimal | None = None
    currency: str = ""
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class EquipmentFleetListResponse(BaseModel):
    """A page of the fleet, and how many units match the filters.

    Named for the fleet rather than for ``Equipment`` because the module also
    has an ``EquipmentTypeListResponse`` and the two are easy to confuse: that
    one is the taxonomy and never truncates, this one is the register and does.
    ``total`` counts the units matching ``status``, ``type`` and ``ownership``,
    so a filtered view reports the size of what it filtered to rather than the
    size of the yard.

    It sits after ``EquipmentResponse`` rather than beside its sibling on
    purpose. ``from __future__ import annotations`` makes the field annotation
    a string, so declaring it earlier still parses, and Pydantic then fails to
    resolve the name when it builds the model.
    """

    items: list[EquipmentResponse]
    total: int
    offset: int = 0
    limit: int = 50


# ── TelemetryReading ─────────────────────────────────────────────────────


class TelemetryReadingCreate(BaseModel):
    """Append a telemetry reading for an equipment unit."""

    model_config = ConfigDict(str_strip_whitespace=True)

    recorded_at: datetime
    fuel_level: Decimal | None = None
    hour_meter: Decimal | None = None
    odometer_km: Decimal | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    engine_status: str | None = Field(default=None, max_length=30)
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class TelemetryReadingResponse(BaseModel):
    """Telemetry reading returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    equipment_id: UUID
    recorded_at: datetime
    fuel_level: Decimal | None = None
    hour_meter: Decimal | None = None
    odometer_km: Decimal | None = None
    lat: float | None = None
    lng: float | None = None
    engine_status: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


# ── MaintenanceSchedule ──────────────────────────────────────────────────


class MaintenanceScheduleCreate(BaseModel):
    """Create a maintenance schedule for an equipment unit."""

    model_config = ConfigDict(str_strip_whitespace=True)

    equipment_id: UUID
    trigger_type: str = Field(..., pattern=r"^(hours|km|date)$")
    trigger_threshold: Decimal = Decimal("0")
    description: str = Field(default="", max_length=500)
    last_completed_at: str | None = Field(default=None, pattern=_ISO_DATE_PATTERN)
    last_completed_meter: Decimal | None = None
    next_due_meter: Decimal | None = None
    next_due_date: str | None = Field(default=None, pattern=_ISO_DATE_PATTERN)
    active: bool = True


class MaintenanceScheduleUpdate(BaseModel):
    """Partial update for a maintenance schedule."""

    model_config = ConfigDict(str_strip_whitespace=True)

    trigger_type: str | None = Field(default=None, pattern=r"^(hours|km|date)$")
    trigger_threshold: Decimal | None = None
    description: str | None = Field(default=None, max_length=500)
    last_completed_at: str | None = Field(default=None, pattern=_ISO_DATE_PATTERN)
    last_completed_meter: Decimal | None = None
    next_due_meter: Decimal | None = None
    next_due_date: str | None = Field(default=None, pattern=_ISO_DATE_PATTERN)
    active: bool | None = None


class MaintenanceScheduleResponse(BaseModel):
    """Maintenance schedule returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    equipment_id: UUID
    trigger_type: str
    trigger_threshold: Decimal
    description: str
    last_completed_at: str | None = None
    last_completed_meter: Decimal | None = None
    next_due_meter: Decimal | None = None
    next_due_date: str | None = None
    active: bool


# ── MaintenanceWorkOrder ─────────────────────────────────────────────────


class MaintenanceWorkOrderCreate(BaseModel):
    """Create a maintenance work order."""

    model_config = ConfigDict(str_strip_whitespace=True)

    equipment_id: UUID
    schedule_id: UUID | None = None
    scheduled_for: str | None = Field(default=None, pattern=_ISO_DATE_PATTERN)
    status: str = Field(
        default="scheduled",
        pattern=r"^(scheduled|in_progress|completed|cancelled)$",
    )
    technician_id: str | None = Field(default=None, max_length=36)
    work_summary: str | None = None
    cost: Decimal = Decimal("0")
    currency: str = Field(default="", max_length=3)


class MaintenanceWorkOrderUpdate(BaseModel):
    """Partial update for a maintenance work order."""

    model_config = ConfigDict(str_strip_whitespace=True)

    scheduled_for: str | None = Field(default=None, pattern=_ISO_DATE_PATTERN)
    completed_at: str | None = Field(default=None, pattern=_ISO_DATE_PATTERN)
    status: str | None = Field(
        default=None,
        pattern=r"^(scheduled|in_progress|completed|cancelled)$",
    )
    technician_id: str | None = Field(default=None, max_length=36)
    work_summary: str | None = None
    cost: Decimal | None = None
    currency: str | None = Field(default=None, max_length=3)


class MaintenanceWorkOrderResponse(BaseModel):
    """Maintenance work order returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    equipment_id: UUID
    schedule_id: UUID | None = None
    scheduled_for: str | None = None
    completed_at: str | None = None
    status: str
    technician_id: str | None = None
    work_summary: str | None = None
    cost: Decimal = Decimal("0")
    currency: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class MaintenanceWorkOrderListResponse(BaseModel):
    """One page of maintenance work orders plus the size of the matching set.

    ``total`` counts the rows the query matched, not the length of ``items``.
    ``equipment_id`` and ``status`` are applied before the count is taken, so a
    zero here means this question found nothing rather than the board holding
    nothing.
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[MaintenanceWorkOrderResponse]
    total: int
    offset: int
    limit: int


# ── Inspection ───────────────────────────────────────────────────────────


class InspectionCreate(BaseModel):
    """Create an inspection record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    equipment_id: UUID
    inspection_type: str = Field(..., pattern=r"^(annual|quarterly|pre_use|monthly|weekly)$")
    inspected_at: str = Field(..., pattern=_ISO_DATE_PATTERN)
    valid_until: str = Field(..., pattern=_ISO_DATE_PATTERN)
    inspector_name: str | None = Field(default=None, max_length=255)
    result: str = Field(default="pass", pattern=r"^(pass|fail|conditional)$")
    notes: str | None = None
    certificate_url: str | None = Field(default=None, max_length=1000)


class InspectionUpdate(BaseModel):
    """Partial update for an inspection."""

    model_config = ConfigDict(str_strip_whitespace=True)

    inspection_type: str | None = Field(
        default=None,
        pattern=r"^(annual|quarterly|pre_use|monthly|weekly)$",
    )
    inspected_at: str | None = Field(default=None, pattern=_ISO_DATE_PATTERN)
    valid_until: str | None = Field(default=None, pattern=_ISO_DATE_PATTERN)
    inspector_name: str | None = Field(default=None, max_length=255)
    result: str | None = Field(default=None, pattern=r"^(pass|fail|conditional)$")
    notes: str | None = None
    certificate_url: str | None = Field(default=None, max_length=1000)
    approved_by: str | None = Field(default=None, max_length=36)


class InspectionResponse(BaseModel):
    """Inspection record returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    equipment_id: UUID
    inspection_type: str
    inspected_at: str
    valid_until: str
    inspector_name: str | None = None
    result: str
    notes: str | None = None
    certificate_url: str | None = None
    approved_by: str | None = None


# ── EquipmentRental ──────────────────────────────────────────────────────


class EquipmentRentalCreate(BaseModel):
    """Create an internal rental of equipment to a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    equipment_id: UUID
    project_id: UUID
    start_date: str = Field(..., pattern=_ISO_DATE_PATTERN)
    end_date: str | None = Field(default=None, pattern=_ISO_DATE_PATTERN)
    internal_rate_per_day: Decimal = Decimal("0")
    internal_rate_per_hour: Decimal = Decimal("0")
    currency: str = Field(default="", max_length=3)
    status: str = Field(default="active", pattern=r"^(active|returned)$")


class EquipmentRentalUpdate(BaseModel):
    """Partial update for a rental."""

    model_config = ConfigDict(str_strip_whitespace=True)

    end_date: str | None = Field(default=None, pattern=_ISO_DATE_PATTERN)
    internal_rate_per_day: Decimal | None = None
    internal_rate_per_hour: Decimal | None = None
    currency: str | None = Field(default=None, max_length=3)
    status: str | None = Field(default=None, pattern=r"^(active|returned)$")


class EquipmentRentalResponse(BaseModel):
    """Rental returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    equipment_id: UUID
    project_id: UUID
    start_date: str
    end_date: str | None = None
    internal_rate_per_day: Decimal
    internal_rate_per_hour: Decimal
    currency: str = ""
    status: str
    billing_calculated_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── FuelLog ──────────────────────────────────────────────────────────────


class FuelLogCreate(BaseModel):
    """Create a fuel log entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    equipment_id: UUID
    logged_at: str = Field(..., pattern=_ISO_DATE_PATTERN)
    fuel_liters: Decimal = Decimal("0")
    hour_meter_at_fill: Decimal | None = None
    odometer_km_at_fill: Decimal | None = None
    cost: Decimal = Decimal("0")
    currency: str = Field(default="", max_length=3)
    supplier: str | None = Field(default=None, max_length=255)
    fuel_type: str | None = Field(default=None, max_length=40)


class FuelLogUpdate(BaseModel):
    """Partial update for a fuel log entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    logged_at: str | None = Field(default=None, pattern=_ISO_DATE_PATTERN)
    fuel_liters: Decimal | None = None
    hour_meter_at_fill: Decimal | None = None
    odometer_km_at_fill: Decimal | None = None
    cost: Decimal | None = None
    currency: str | None = Field(default=None, max_length=3)
    supplier: str | None = Field(default=None, max_length=255)
    fuel_type: str | None = Field(default=None, max_length=40)


class FuelLogResponse(BaseModel):
    """Fuel log returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    equipment_id: UUID
    logged_at: str
    fuel_liters: Decimal
    hour_meter_at_fill: Decimal | None = None
    odometer_km_at_fill: Decimal | None = None
    cost: Decimal
    currency: str = ""
    supplier: str | None = None
    fuel_type: str | None = None


class FuelLogListResponse(BaseModel):
    """One page of fuel logs for one machine plus the size of that set.

    ``total`` counts the machine's whole fuel history, not the length of
    ``items``. The route requires ``equipment_id``, so the count is per machine
    by construction and there is no other filter to be inside or outside it.

    A refuel is logged every time a machine is filled, which makes this the
    fastest-growing child register in the module: a year of a busy plant item
    runs well past the page the drawer asks for.
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[FuelLogResponse]
    total: int
    offset: int
    limit: int


# ── PartsLog ─────────────────────────────────────────────────────────────


class PartsLogCreate(BaseModel):
    """Create a parts log entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    equipment_id: UUID
    work_order_id: UUID | None = None
    part_number: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    quantity: Decimal = Decimal("1")
    unit_cost: Decimal = Decimal("0")
    currency: str = Field(default="", max_length=3)
    logged_at: str | None = Field(default=None, pattern=_ISO_DATE_PATTERN)


class PartsLogUpdate(BaseModel):
    """Partial update for a parts log entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str | None = Field(default=None, max_length=500)
    quantity: Decimal | None = None
    unit_cost: Decimal | None = None
    currency: str | None = Field(default=None, max_length=3)
    logged_at: str | None = Field(default=None, pattern=_ISO_DATE_PATTERN)


class PartsLogResponse(BaseModel):
    """Parts log returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    equipment_id: UUID
    work_order_id: UUID | None = None
    part_number: str
    description: str
    quantity: Decimal
    unit_cost: Decimal
    currency: str = ""
    logged_at: str | None = None


# ── DamageReport ─────────────────────────────────────────────────────────


class DamageReportCreate(BaseModel):
    """Create a damage report."""

    model_config = ConfigDict(str_strip_whitespace=True)

    equipment_id: UUID
    reported_at: str = Field(..., pattern=_ISO_DATE_PATTERN)
    reported_by: str | None = Field(default=None, max_length=36)
    severity: str = Field(default="minor", pattern=r"^(minor|major|critical)$")
    description: str = Field(default="", max_length=10000)
    photos: list[str] = Field(default_factory=list)
    repair_cost_estimate: Decimal | None = None
    currency: str = Field(default="", max_length=3)


class DamageReportUpdate(BaseModel):
    """Partial update for a damage report."""

    model_config = ConfigDict(str_strip_whitespace=True)

    severity: str | None = Field(default=None, pattern=r"^(minor|major|critical)$")
    description: str | None = Field(default=None, max_length=10000)
    photos: list[str] | None = None
    repair_cost_estimate: Decimal | None = None
    currency: str | None = Field(default=None, max_length=3)
    status: str | None = Field(
        default=None,
        pattern=r"^(reported|under_repair|repaired)$",
    )


class DamageReportResponse(BaseModel):
    """Damage report returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    equipment_id: UUID
    reported_at: str
    reported_by: str | None = None
    severity: str
    description: str
    photos: list[str] = Field(default_factory=list)
    repair_cost_estimate: Decimal | None = None
    currency: str = ""
    status: str
    work_order_id: UUID | None = None


# ── Dashboard / aggregate responses ──────────────────────────────────────


class EquipmentDashboardResponse(BaseModel):
    """Per-equipment dashboard payload."""

    equipment_id: UUID
    code: str
    name: str
    status: str
    utilization_pct: float = 0.0
    fuel_cost_mtd: Decimal = Decimal("0")
    open_work_orders: int = 0
    expiring_inspections: int = 0
    blocked: bool = False
    last_telemetry_at: datetime | None = None


class EquipmentCostSummaryResponse(BaseModel):
    """Aggregated cost breakdown for one machine, optionally scoped to a project.

    Returned by ``GET /equipment/{id}/cost-summary``. Each bucket is a
    Decimal-as-string so the frontend can format it in the project currency
    without float rounding.
    """

    equipment_id: UUID
    project_id: UUID | None = None
    rental_cost: Decimal = Decimal("0")
    rental_days: int = 0
    fuel_cost: Decimal = Decimal("0")
    fuel_litres: Decimal = Decimal("0")
    maintenance_cost: Decimal = Decimal("0")
    maintenance_orders: int = 0
    parts_cost: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    plant_hours: Decimal = Decimal("0")
    cost_per_hour: Decimal | None = None

    @field_serializer(
        "rental_cost",
        "fuel_cost",
        "fuel_litres",
        "maintenance_cost",
        "parts_cost",
        "total_cost",
        "plant_hours",
        "cost_per_hour",
        when_used="json",
    )
    def _ser(self, v: Decimal | None) -> str | None:
        if v is None:
            return None
        return str(v.quantize(Decimal("0.01")))


class FleetDashboardResponse(BaseModel):
    """Fleet-wide dashboard payload."""

    total_units: int = 0
    counts_by_status: dict[str, int] = Field(default_factory=dict)
    counts_by_type: dict[str, int] = Field(default_factory=dict)
    utilization_pct: float = 0.0
    fuel_cost_mtd: Decimal = Decimal("0")
    open_work_orders: int = 0
    expiring_inspections: int = 0
    blocked_units: int = 0
    active_rentals: int = 0


# ── Predictive maintenance / fleet analytics ──────────────────────────────


class HealthAnomalyResponse(BaseModel):
    """A single anomalous telemetry reading."""

    recorded_at: datetime
    metric: str
    value: float
    z_score: float
    reason: str


class HealthAnalyticsResponse(BaseModel):
    """Per-unit predictive health assessment.

    Plain-English fields (``health_score`` 0-100, red/amber/green ``band``)
    so a fleet manager can read it without reliability-engineering jargon.
    """

    equipment_id: UUID
    health_score: float = Field(..., ge=0, le=100)
    band: str
    anomaly_detected: bool
    maintenance_trend: str
    reasons: list[str] = Field(default_factory=list)
    anomalies: list[HealthAnomalyResponse] = Field(default_factory=list)
    sample_count: int = 0


class FailureForecastResponse(BaseModel):
    """Per-unit failure / next-service forecast."""

    equipment_id: UUID
    predicted_failure_date: str | None = None
    failure_confidence: float = Field(..., ge=0, le=1)
    days_to_failure: int | None = None
    basis: str
    daily_usage: float = 0.0


class FleetUnderutilizedResponse(BaseModel):
    """An underutilised unit with its idle-cost saving opportunity."""

    equipment_id: str
    code: str
    name: str
    utilization_pct: float
    estimated_idle_days: float
    estimated_monthly_saving: str


class FleetMaintenanceBundleResponse(BaseModel):
    """A group of units that should be serviced together."""

    label: str
    equipment_ids: list[str] = Field(default_factory=list)
    codes: list[str] = Field(default_factory=list)
    unit_count: int = 0


class FleetOptimizationResponse(BaseModel):
    """Fleet-wide optimisation recommendations."""

    total_units: int = 0
    target_utilization_pct: float = 70.0
    window_days: int = 30
    underutilized_count: int = 0
    estimated_monthly_savings: str = "0"
    underutilized: list[FleetUnderutilizedResponse] = Field(default_factory=list)
    maintenance_bundles: list[FleetMaintenanceBundleResponse] = Field(default_factory=list)
