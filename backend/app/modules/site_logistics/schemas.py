# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Site Logistics Pydantic schemas - request/response models.

Covers gates, laydown zones and delivery bookings following the create /
update / response split used across the platform.

Quantities and money cross the wire as canonical Decimal STRINGS, never floats:
write schemas accept a string and validate it parses, response schemas coerce
the ``Decimal`` handed back by the ORM to a string in a ``mode="before"``
validator. Same convention as the site-inventory module next door.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.site_logistics.models import DELIVERY_STATUSES

# "HH:MM" 24-hour clock, e.g. 07:00 / 18:30.
_HHMM_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
# Delivery status enum built from the single source of truth in models.py.
_STATUS_PATTERN = r"^(" + "|".join(DELIVERY_STATUSES) + r")$"


def _parse_decimal(value: str) -> Decimal:
    """Parse a string into a ``Decimal`` or raise a clear ``ValueError``."""
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def _validate_positive(value: str) -> str:
    """Validate that a string is a strictly positive decimal, returned unchanged."""
    if _parse_decimal(value) <= 0:
        raise ValueError(f"Value must be greater than zero, got {value!r}")
    return value


def _coerce_str(value: Any) -> str:
    """Render an ORM ``Decimal`` (or anything) as a string, ``None`` -> ``'0'``."""
    if value is None:
        return "0"
    return str(value)


# ── Gate ───────────────────────────────────────────────────────────────────


class GateCreate(BaseModel):
    """Create a site access gate."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    open_time: str = Field(default="07:00", pattern=_HHMM_PATTERN)
    close_time: str = Field(default="18:00", pattern=_HHMM_PATTERN)
    capacity_per_slot: int = Field(default=1, ge=1, le=100)
    notes: str | None = None
    # Access kind (catalogue ``access_kinds``) and load limits (rule 5).
    access_kind: str | None = Field(default=None, max_length=40)
    max_axle_load_t: Decimal | None = Field(default=None, ge=0)
    max_gross_t: Decimal | None = Field(default=None, ge=0)
    max_height_m: Decimal | None = Field(default=None, ge=0)
    max_width_m: Decimal | None = Field(default=None, ge=0)
    max_length_m: Decimal | None = Field(default=None, ge=0)
    turning_radius_m: Decimal | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_hours(self) -> "GateCreate":
        if self.close_time <= self.open_time:
            raise ValueError("close_time must be later than open_time")
        return self


class GateUpdate(BaseModel):
    """Partial update for a gate."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    open_time: str | None = Field(default=None, pattern=_HHMM_PATTERN)
    close_time: str | None = Field(default=None, pattern=_HHMM_PATTERN)
    capacity_per_slot: int | None = Field(default=None, ge=1, le=100)
    notes: str | None = None
    # Access kind (catalogue ``access_kinds``) and load limits (rule 5).
    access_kind: str | None = Field(default=None, max_length=40)
    max_axle_load_t: Decimal | None = Field(default=None, ge=0)
    max_gross_t: Decimal | None = Field(default=None, ge=0)
    max_height_m: Decimal | None = Field(default=None, ge=0)
    max_width_m: Decimal | None = Field(default=None, ge=0)
    max_length_m: Decimal | None = Field(default=None, ge=0)
    turning_radius_m: Decimal | None = Field(default=None, ge=0)
    metadata: dict[str, Any] | None = None


class GateResponse(BaseModel):
    """A gate returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    # What the caller may do with this record now; set by the routes, absent elsewhere.
    can: dict[str, Any] | None = None
    id: UUID
    project_id: UUID
    name: str
    open_time: str
    close_time: str
    capacity_per_slot: int
    notes: str | None = None
    access_kind: str | None = None
    max_axle_load_t: Decimal | None = None
    max_gross_t: Decimal | None = None
    max_height_m: Decimal | None = None
    max_width_m: Decimal | None = None
    max_length_m: Decimal | None = None
    turning_radius_m: Decimal | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Laydown zone ───────────────────────────────────────────────────────────


class LaydownZoneCreate(BaseModel):
    """Create a material laydown zone."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    capacity_desc: str | None = Field(default=None, max_length=255)
    usage_note: str | None = None
    # The planned site area this zone operates in (rule 4); must be in the same project.
    site_area_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LaydownZoneUpdate(BaseModel):
    """Partial update for a laydown zone."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    capacity_desc: str | None = Field(default=None, max_length=255)
    usage_note: str | None = None
    site_area_id: UUID | None = None
    metadata: dict[str, Any] | None = None


class LaydownZoneResponse(BaseModel):
    """A laydown zone returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    # What the caller may do with this record now; set by the routes, absent elsewhere.
    can: dict[str, Any] | None = None
    id: UUID
    project_id: UUID
    name: str
    capacity_desc: str | None = None
    usage_note: str | None = None
    site_area_id: UUID | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Delivery lines (the bill positions a delivery carries) ─────────────────

# A truck can carry several bill lines, but not a hundred: the cap keeps one
# booking's payload bounded without ever getting in a real delivery's way.
MAX_DELIVERY_LINES = 50


class DeliveryLineInput(BaseModel):
    """One bill position on a delivery, with the quantity being delivered.

    ``boq_position_id`` is optional so a delivery of something the estimate
    never priced (a welfare unit, a skip) can still be listed. The service
    fills ``description`` / ``unit`` from the position when one is given, so
    the bill stays the source of truth for what the line says.

    ``position_ordinal`` is only read for a line that carries no position: a
    linked line takes its ordinal from the bill. It exists so a detached line -
    one whose position was deleted after the booking - keeps the ordinal it was
    delivered against when the delivery is edited for some other reason. That
    snapshot is what marks the line as detached; dropping it on an ordinary
    save would quietly turn the line into one that was never in the bill.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    boq_position_id: UUID | None = None
    position_ordinal: str | None = Field(default=None, max_length=50)
    description: str = Field(default="", max_length=500)
    quantity: str = Field(default="1", max_length=50)
    unit: str = Field(default="", max_length=20)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("quantity")
    @classmethod
    def _check_quantity(cls, v: str) -> str:
        return _validate_positive(v)

    @model_validator(mode="after")
    def _check_identified(self) -> "DeliveryLineInput":
        if self.boq_position_id is None and not self.description:
            raise ValueError("A delivery line needs either a bill position or a description")
        return self


class DeliveryLineResponse(BaseModel):
    """A delivery line returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    delivery_id: UUID
    boq_position_id: UUID | None = None
    position_ordinal: str | None = None
    description: str = ""
    quantity: str = "0"
    unit: str = ""
    note: str | None = None
    sort_order: int = 0

    @field_validator("quantity", mode="before")
    @classmethod
    def _num_to_str(cls, v: Any) -> str:
        return _coerce_str(v)


# ── Delivery booking ───────────────────────────────────────────────────────


class DeliveryCreate(BaseModel):
    """Book an inbound delivery."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    gate_id: UUID | None = None
    supplier_name: str = Field(..., min_length=1, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=50)
    vehicle_type: str | None = Field(default=None, max_length=120)
    materials_desc: str | None = None
    window_start: datetime
    window_end: datetime
    status: str = Field(default="requested", pattern=_STATUS_PATTERN)
    po_ref: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    # The transport this slot belongs to (Decision 3) and the load it carries (rule 5).
    transport_id: UUID | None = None
    direction: str = Field(default="inbound", pattern=r"^(inbound|outbound)$")
    gross_weight_t: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    plant_item_id: UUID | None = None
    takt_location_id: UUID | None = None
    flow_code: str | None = Field(default=None, max_length=40)
    lines: list[DeliveryLineInput] = Field(default_factory=list, max_length=MAX_DELIVERY_LINES)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_window(self) -> "DeliveryCreate":
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        return self


class DeliveryUpdate(BaseModel):
    """Partial update for a delivery booking."""

    model_config = ConfigDict(str_strip_whitespace=True)

    gate_id: UUID | None = None
    supplier_name: str | None = Field(default=None, min_length=1, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=50)
    vehicle_type: str | None = Field(default=None, max_length=120)
    materials_desc: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    status: str | None = Field(default=None, pattern=_STATUS_PATTERN)
    po_ref: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    # Replace-all semantics: omitting the key leaves the existing lines alone,
    # sending a list (including an empty one) makes the booking carry exactly
    # that list. The delivery modal always saves the whole booking, so a
    # partial line patch would only invite two clients disagreeing about which
    # lines survived.
    # The transport this slot belongs to (Decision 3) and the load it carries (rule 5).
    transport_id: UUID | None = None
    direction: str | None = Field(default=None, pattern=r"^(inbound|outbound)$")
    gross_weight_t: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    plant_item_id: UUID | None = None
    takt_location_id: UUID | None = None
    flow_code: str | None = Field(default=None, max_length=40)
    lines: list[DeliveryLineInput] | None = Field(default=None, max_length=MAX_DELIVERY_LINES)
    metadata: dict[str, Any] | None = None


class DeliveryDecisionRequest(BaseModel):
    """Approve or reject a delivery, with an optional reason for the audit note."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str | None = Field(default=None, max_length=500)


class DeliveryResponse(BaseModel):
    """A delivery booking returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    # What the caller may do with this record now; set by the routes, absent elsewhere.
    can: dict[str, Any] | None = None
    # Checks that were not made for this delivery (``gate_hours_unchecked``); set by the routes.
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    id: UUID
    project_id: UUID
    gate_id: UUID | None = None
    supplier_name: str
    contact_name: str | None = None
    contact_phone: str | None = None
    vehicle_type: str | None = None
    materials_desc: str | None = None
    window_start: datetime
    window_end: datetime
    status: str = "requested"
    po_ref: str | None = None
    notes: str | None = None
    transport_id: UUID | None = None
    direction: str = "inbound"
    gross_weight_t: Decimal | None = None
    plant_item_id: UUID | None = None
    takt_location_id: UUID | None = None
    flow_code: str | None = None
    created_by: str | None = None
    lines: list[DeliveryLineResponse] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Bill coverage ──────────────────────────────────────────────────────────

# A bill runs to thousands of positions; the coverage table and the position
# picker both read this endpoint, so the response is capped and says so.
BILL_COVERAGE_LIMIT = 200


class BillCoverageRow(BaseModel):
    """One bill position with what has been booked and delivered against it."""

    position_id: UUID
    boq_id: UUID
    ordinal: str = ""
    description: str = ""
    unit: str = ""
    #: What the estimate says has to be built.
    bill_quantity: str = "0"
    unit_rate: str = "0"
    bill_total: str = "0"
    #: On site now (deliveries that arrived or completed).
    delivered_quantity: str = "0"
    #: Arranged but still inbound (requested or approved deliveries).
    booked_quantity: str = "0"
    #: bill - delivered - booked. Negative when more is on the way than the
    #: bill calls for; deliberately not clamped.
    outstanding_quantity: str = "0"
    #: delivered_quantity priced at the position's current unit rate.
    delivered_value: str = "0"
    delivery_line_count: int = 0
    over_delivered: bool = False


class BillCoverageResponse(BaseModel):
    """The project's bill, read as a delivery ledger."""

    rows: list[BillCoverageRow] = Field(default_factory=list)
    #: Positions matching the filter before the cap was applied.
    total: int = 0
    truncated: bool = False
    currency: str = ""
    #: Positions with at least one delivery line pointing at them.
    linked_position_count: int = 0
    #: Sum of ``delivered_value`` over every row returned.
    delivered_value_total: str = "0"
    #: Delivery lines whose bill position has since been deleted. They still
    #: hold their own description and quantity; see ``DeliveryLine``.
    detached_line_count: int = 0


# ── Stats ──────────────────────────────────────────────────────────────────


class SiteLogisticsStatsResponse(BaseModel):
    """Aggregate delivery statistics for a project."""

    total_deliveries: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    gate_count: int = 0
    laydown_zone_count: int = 0
    upcoming_approved: int = 0
    #: Deliveries carrying at least one line linked to a bill position.
    deliveries_linked_to_bill: int = 0
    #: Distinct bill positions with at least one delivery line.
    positions_covered: int = 0
