"""Accommodation Pydantic schemas — request / response models.

Money fields are Decimal. Currency is validated against the ISO 4217
three-letter alphabetic-code pattern via a Pydantic regex (no remote
lookup needed for the MVP — the registry of "real" codes lives in
``app.modules.i18n_foundation`` and can be consulted later if a
stricter check is required).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ── Enum patterns (regex, not Literal — adding a new value stays a single
#    line change and never needs a DB migration) ─────────────────────────

_KIND_PATTERN = r"^(worker_camp|rental|hotel)$"
_ROOM_STATUS_PATTERN = r"^(available|occupied|maintenance|blocked)$"
_BOOKING_STATUS_PATTERN = r"^(reserved|checked_in|checked_out|cancelled)$"
_BOOKING_SOURCE_PATTERN = r"^(manual|hr_autobook|propdev_import|pms_sync)$"
_CHARGE_KIND_PATTERN = r"^(base_rent|extra|deposit|refund)$"
_CHARGE_STATUS_PATTERN = r"^(pending|invoiced|paid|waived)$"
# ISO 4217 alphabetic code — three uppercase letters. Empty string is
# explicitly allowed on optional/write paths so the service layer can
# inherit the parent's currency rather than echoing a hard-coded "EUR".
_CURRENCY_PATTERN = r"^[A-Z]{3}$|^$"


# ── Accommodation ────────────────────────────────────────────────────────


class AccommodationCreate(BaseModel):
    """Create a new accommodation asset."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(default="", max_length=255)
    kind: str = Field(default="worker_camp", pattern=_KIND_PATTERN)
    address: str | None = None
    geo_lat: Decimal | None = Field(default=None, ge=-90, le=90)
    geo_lon: Decimal | None = Field(default=None, ge=-180, le=180)
    bim_model_id: UUID | None = None
    property_dev_block_id: UUID | None = None
    capacity_total: int = Field(default=0, ge=0)
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AccommodationUpdate(BaseModel):
    """Partial update for an accommodation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    kind: str | None = Field(default=None, pattern=_KIND_PATTERN)
    address: str | None = None
    geo_lat: Decimal | None = Field(default=None, ge=-90, le=90)
    geo_lon: Decimal | None = Field(default=None, ge=-180, le=180)
    bim_model_id: UUID | None = None
    property_dev_block_id: UUID | None = None
    capacity_total: int | None = Field(default=None, ge=0)
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class AccommodationResponse(BaseModel):
    """Read shape for an accommodation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    kind: str
    address: str | None = None
    geo_lat: Decimal | None = None
    geo_lon: Decimal | None = None
    bim_model_id: UUID | None = None
    property_dev_block_id: UUID | None = None
    capacity_total: int
    notes: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")


class AccommodationDetailResponse(AccommodationResponse):
    """Detail shape — adds nested room list + booking summary."""

    rooms: list[RoomResponse] = Field(default_factory=list)
    active_bookings_count: int = 0


# ── Room ──────────────────────────────────────────────────────────────────


class RoomCreate(BaseModel):
    """Create a single room. Bulk create uses ``list[RoomCreate]``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(..., min_length=1, max_length=120)
    capacity: int = Field(default=1, ge=1)
    bim_element_id: str | None = Field(default=None, max_length=120)
    base_rate: Decimal = Field(default=Decimal("0"), ge=0)
    base_rate_currency: str = Field(default="", pattern=_CURRENCY_PATTERN)
    status: str = Field(default="available", pattern=_ROOM_STATUS_PATTERN)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoomBulkCreate(BaseModel):
    """Container for bulk-creating rooms under one accommodation."""

    rooms: list[RoomCreate] = Field(..., min_length=1, max_length=2000)


class RoomUpdate(BaseModel):
    """Partial update for a room."""

    model_config = ConfigDict(str_strip_whitespace=True)

    label: str | None = Field(default=None, min_length=1, max_length=120)
    capacity: int | None = Field(default=None, ge=1)
    bim_element_id: str | None = Field(default=None, max_length=120)
    base_rate: Decimal | None = Field(default=None, ge=0)
    base_rate_currency: str | None = Field(default=None, pattern=_CURRENCY_PATTERN)
    status: str | None = Field(default=None, pattern=_ROOM_STATUS_PATTERN)
    metadata: dict[str, Any] | None = None


class RoomResponse(BaseModel):
    """Read shape for a room."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    accommodation_id: UUID
    label: str
    capacity: int
    bim_element_id: str | None = None
    base_rate: Decimal
    base_rate_currency: str
    status: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")


# ── Booking ──────────────────────────────────────────────────────────────


class BookingCreate(BaseModel):
    """Create a booking on a specific room."""

    model_config = ConfigDict(str_strip_whitespace=True)

    occupant_contact_id: UUID | None = None
    occupant_name: str | None = Field(default=None, max_length=255)
    check_in: date
    check_out: date | None = None
    status: str = Field(default="reserved", pattern=_BOOKING_STATUS_PATTERN)
    source: str = Field(default="manual", pattern=_BOOKING_SOURCE_PATTERN)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_dates_and_occupant(self) -> BookingCreate:
        if self.check_out is not None and self.check_out <= self.check_in:
            raise ValueError("check_out must be strictly after check_in")
        if self.occupant_contact_id is None and not (self.occupant_name or "").strip():
            raise ValueError(
                "either occupant_contact_id or occupant_name must be provided",
            )
        return self


class BookingUpdate(BaseModel):
    """Partial update for a booking.

    The service layer enforces the state-machine transitions; this schema
    only validates field shapes.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    occupant_contact_id: UUID | None = None
    occupant_name: str | None = Field(default=None, max_length=255)
    check_in: date | None = None
    check_out: date | None = None
    status: str | None = Field(default=None, pattern=_BOOKING_STATUS_PATTERN)
    source: str | None = Field(default=None, pattern=_BOOKING_SOURCE_PATTERN)
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_dates(self) -> BookingUpdate:
        if self.check_in is not None and self.check_out is not None and self.check_out <= self.check_in:
            raise ValueError("check_out must be strictly after check_in")
        return self


class BookingResponse(BaseModel):
    """Read shape for a booking.

    ``room_label`` is optional and only populated by list endpoints that
    eagerly resolve the parent room — single-booking GETs leave it
    ``None`` because the room id is already in scope at the call site.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    room_id: UUID
    room_label: str | None = None
    occupant_contact_id: UUID | None = None
    occupant_name: str | None = None
    check_in: date
    check_out: date | None = None
    status: str
    source: str
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")


class BookingDetailResponse(BookingResponse):
    """Detail shape — adds nested charges."""

    charges: list[ChargeResponse] = Field(default_factory=list)


class BookingListResponse(BaseModel):
    """Paginated booking list with room labels decorated server-side."""

    items: list[BookingResponse] = Field(default_factory=list)
    total: int = 0
    limit: int
    offset: int


# ── Charge ───────────────────────────────────────────────────────────────


class ChargeCreate(BaseModel):
    """Create a charge against a booking."""

    model_config = ConfigDict(str_strip_whitespace=True)

    kind: str = Field(default="extra", pattern=_CHARGE_KIND_PATTERN)
    description: str | None = None
    amount: Decimal = Field(..., ge=0)
    currency: str = Field(default="", pattern=_CURRENCY_PATTERN)
    period_start: date | None = None
    period_end: date | None = None
    status: str = Field(default="pending", pattern=_CHARGE_STATUS_PATTERN)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_period(self) -> ChargeCreate:
        if self.period_start is not None and self.period_end is not None and self.period_end < self.period_start:
            raise ValueError("period_end must not precede period_start")
        return self


class ChargeResponse(BaseModel):
    """Read shape for a charge."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    booking_id: UUID
    kind: str
    description: str | None = None
    amount: Decimal
    currency: str
    period_start: date | None = None
    period_end: date | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")


# ── Cross-module integrations ────────────────────────────────────────────


class BootstrapFromPropDevResponse(BaseModel):
    """Result payload for the PropDev → Accommodation bootstrap."""

    accommodation_id: UUID
    block_id: UUID
    rooms_created: int
    rooms_skipped: int
    total_rooms: int


class SuggestFromHRRequest(BaseModel):
    """Body for ``POST /bookings/suggest-from-hr``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    employee_contact_id: UUID
    start_date: date


class SuggestFromHRResponse(BaseModel):
    """Suggested room — NOT auto-confirmed; UI must POST a real booking."""

    room_id: UUID
    room_label: str
    accommodation_id: UUID
    accommodation_name: str
    accommodation_kind: str
    capacity: int
    base_rate: Decimal
    base_rate_currency: str


# Resolve forward references (RoomResponse / ChargeResponse referenced
# from earlier schemas).
AccommodationDetailResponse.model_rebuild()
BookingDetailResponse.model_rebuild()
BookingListResponse.model_rebuild()
