"""‌⁠‍Property Development Pydantic schemas — request/response models."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

# ── R7 money serialization helper ───────────────────────────────────────
#
# Pydantic v2 serializes ``Decimal`` to a JSON *number* by default, which
# JS rounds to a float (precision loss past ~15 digits). The platform-wide
# convention (mirrors boq/schemas.py BUG-B-011) is to emit money fields as
# plain-decimal *strings* so the wire format is locale-neutral and exact.
# This helper formats a Decimal as a fixed-point string ("12345.67" — not
# "1.234567E+4"), defends against NaN/Inf (collapses to "0"), and tolerates
# values that arrive as int/float when callers bypass the Pydantic input
# coercion. Applied via ``@field_serializer(..., when_used="json")`` on
# every response model that carries money.


def _serialize_money_string(value: Any) -> str | None:
    """Render a Decimal-ish value as a plain-decimal string, or None."""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return "0"
    if not value.is_finite():
        return "0"
    return format(value, "f")


# Regex for an ISO-4217 3-letter currency code (uppercase).
_CURRENCY_PATTERN = r"^[A-Z]{3}$"

# R6 (task #137) enum patterns — kept in module scope so router + tests can re-use.
_LEAD_SOURCE_PATTERN = r"^(web_form|walk_in|broker|referral|portal|other)$"
_LEAD_STATUS_PATTERN = (
    r"^(new|qualified|viewing_scheduled|visited|quotation_sent|"
    r"negotiating|converted|lost|disqualified)$"
)
_RESERVATION_STATUS_PATTERN = r"^(active|expired|converted|cancelled|refunded)$"
_SPA_STATUS_PATTERN = (
    r"^(draft|sent_for_signature|partially_signed|signed|countersigned|"
    r"registered|cancelled)$"
)
_SCHEDULE_STATUS_PATTERN = r"^(active|completed|suspended|cancelled)$"
_INSTALMENT_STATUS_PATTERN = r"^(pending|due|overdue|paid|waived|cancelled)$"
_PARTY_ROLE_PATTERN = r"^(primary|co_owner|guarantor|power_of_attorney)$"
_RESERVATION_NUMBER_PATTERN = r"^RES-[A-Z0-9-]{1,40}-\d{5}$"
_CONTRACT_NUMBER_PATTERN = r"^SPA-[A-Z0-9-]{1,40}-\d{5}$"

# ── Development ─────────────────────────────────────────────────────────


# Allowed development "types" — kept as a regex pattern (not a Literal) so
# adding a new value is a single-line change. ``other`` is the catch-all.
_DEV_TYPE_PATTERN = (
    r"^(residential|mixed_use|commercial|industrial|hospitality|"
    r"resort|senior_living|student_housing|retail|office|logistics|other)$"
)
_COUNTRY_CODE_PATTERN = r"^[A-Z]{2}$"


class DevelopmentCreate(BaseModel):
    """‌⁠‍Create a new development."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(default="", max_length=255)
    description: str | None = None
    dev_type: str = Field(default="residential", pattern=_DEV_TYPE_PATTERN)
    location_address: str | None = None
    country_code: str | None = Field(default=None, pattern=_COUNTRY_CODE_PATTERN)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    total_plots: int = Field(default=0, ge=0)
    total_area_m2: Decimal = Field(default=Decimal("0"), ge=0)
    total_floors: int = Field(default=0, ge=0)
    sales_phase: str = Field(
        default="planning",
        pattern=r"^(planning|launch|sales|handover|closed)$",
    )
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    launch_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    completion_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    marketing_brief: str | None = None
    status: str = Field(default="active", pattern=r"^(active|paused|completed)$")
    units: str = Field(default="metric", pattern=r"^(metric|imperial)$")
    sales_target_amount: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=8)
    developer_name: str | None = Field(default=None, max_length=255)
    architect_name: str | None = Field(default=None, max_length=255)
    general_contractor_name: str | None = Field(default=None, max_length=255)
    cover_image_url: str | None = Field(default=None, max_length=1024)
    brochure_url: str | None = Field(default=None, max_length=1024)
    website_url: str | None = Field(default=None, max_length=1024)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DevelopmentUpdate(BaseModel):
    """‌⁠‍Partial update for a development."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    dev_type: str | None = Field(default=None, pattern=_DEV_TYPE_PATTERN)
    location_address: str | None = None
    country_code: str | None = Field(default=None, pattern=_COUNTRY_CODE_PATTERN)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    total_plots: int | None = Field(default=None, ge=0)
    total_area_m2: Decimal | None = Field(default=None, ge=0)
    total_floors: int | None = Field(default=None, ge=0)
    sales_phase: str | None = Field(default=None, pattern=r"^(planning|launch|sales|handover|closed)$")
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    launch_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    completion_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    marketing_brief: str | None = None
    status: str | None = Field(default=None, pattern=r"^(active|paused|completed)$")
    units: str | None = Field(default=None, pattern=r"^(metric|imperial)$")
    sales_target_amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    developer_name: str | None = Field(default=None, max_length=255)
    architect_name: str | None = Field(default=None, max_length=255)
    general_contractor_name: str | None = Field(default=None, max_length=255)
    cover_image_url: str | None = Field(default=None, max_length=1024)
    brochure_url: str | None = Field(default=None, max_length=1024)
    website_url: str | None = Field(default=None, max_length=1024)
    metadata: dict[str, Any] | None = None


class DevelopmentResponse(BaseModel):
    """Development returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    code: str
    name: str = ""
    description: str | None = None
    dev_type: str = "residential"
    location_address: str | None = None
    country_code: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    total_plots: int = 0
    total_area_m2: Decimal = Decimal("0")
    total_floors: int = 0
    sales_phase: str = "planning"
    start_date: str | None = None
    launch_date: str | None = None
    completion_date: str | None = None
    marketing_brief: str | None = None
    status: str = "active"
    units: str = "metric"
    sales_target_amount: Decimal = Decimal("0")
    currency: str = ""
    developer_name: str | None = None
    architect_name: str | None = None
    general_contractor_name: str | None = None
    cover_image_url: str | None = None
    brochure_url: str | None = None
    website_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # R7: money fields as plain-decimal strings (mirrors boq BUG-B-011).
    @field_serializer("total_area_m2", "sales_target_amount", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


# ── House Type ──────────────────────────────────────────────────────────


class HouseTypeCreate(BaseModel):
    """Create a new house type."""

    model_config = ConfigDict(str_strip_whitespace=True)

    development_id: UUID
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(default="", max_length=255)
    bedrooms: int = Field(default=0, ge=0)
    bathrooms: int = Field(default=0, ge=0)
    total_area_m2: Decimal = Field(default=Decimal("0"), ge=0)
    footprint_m2: Decimal = Field(default=Decimal("0"), ge=0)
    levels: int = Field(default=1, ge=1)
    base_price: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=8)
    bim_model_ref: str | None = Field(default=None, max_length=120)
    thumbnail_url: str | None = Field(default=None, max_length=1024)
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HouseTypeUpdate(BaseModel):
    """Partial update for a house type."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    bedrooms: int | None = Field(default=None, ge=0)
    bathrooms: int | None = Field(default=None, ge=0)
    total_area_m2: Decimal | None = Field(default=None, ge=0)
    footprint_m2: Decimal | None = Field(default=None, ge=0)
    levels: int | None = Field(default=None, ge=1)
    base_price: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    bim_model_ref: str | None = Field(default=None, max_length=120)
    thumbnail_url: str | None = Field(default=None, max_length=1024)
    description: str | None = None
    metadata: dict[str, Any] | None = None


class HouseTypeResponse(BaseModel):
    """House type returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    development_id: UUID
    code: str
    name: str = ""
    bedrooms: int = 0
    bathrooms: int = 0
    total_area_m2: Decimal = Decimal("0")
    footprint_m2: Decimal = Decimal("0")
    levels: int = 1
    base_price: Decimal = Decimal("0")
    currency: str = ""
    bim_model_ref: str | None = None
    thumbnail_url: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # R7: money fields as plain-decimal strings.
    @field_serializer("total_area_m2", "footprint_m2", "base_price", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


# ── House Type Variant ──────────────────────────────────────────────────


class HouseTypeVariantCreate(BaseModel):
    """Create a new house type variant."""

    model_config = ConfigDict(str_strip_whitespace=True)

    house_type_id: UUID
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(default="", max_length=255)
    modifier_pct: Decimal = Field(default=Decimal("0"))
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HouseTypeVariantUpdate(BaseModel):
    """Partial update for a variant."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    modifier_pct: Decimal | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None


class HouseTypeVariantResponse(BaseModel):
    """Variant returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    house_type_id: UUID
    code: str
    name: str = ""
    modifier_pct: Decimal = Decimal("0")
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Plot ────────────────────────────────────────────────────────────────


class PlotCreate(BaseModel):
    """Create a new plot."""

    model_config = ConfigDict(str_strip_whitespace=True)

    development_id: UUID
    plot_number: str = Field(..., min_length=1, max_length=50)
    house_type_id: UUID | None = None
    house_type_variant_id: UUID | None = None
    house_type_label: str | None = Field(default=None, max_length=120)
    block_id: UUID | None = None
    level_in_block: int | None = Field(default=None, ge=-10, le=200)
    position_on_floor: str | None = Field(default=None, max_length=40)
    orientation: str | None = Field(default=None, max_length=16)
    view_type: str | None = Field(default=None, max_length=40)
    area_m2: Decimal = Field(default=Decimal("0"), ge=0)
    garden_area_m2: Decimal | None = Field(default=None, ge=0)
    balcony_area_m2: Decimal | None = Field(default=None, ge=0)
    storage_area_m2: Decimal | None = Field(default=None, ge=0)
    bedrooms: int = Field(default=0, ge=0, le=20)
    bathrooms: int = Field(default=0, ge=0, le=20)
    parking_spaces: int = Field(default=0, ge=0, le=20)
    sun_exposure_hours: Decimal | None = Field(default=None, ge=0, le=24)
    price_base: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=8)
    status: str = Field(
        default="planned",
        pattern=r"^(planned|reserved|under_construction|ready|sold|handed_over|held|blocked)$",
    )
    reservation_deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    construction_status_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlotUpdate(BaseModel):
    """Partial update for a plot."""

    model_config = ConfigDict(str_strip_whitespace=True)

    house_type_id: UUID | None = None
    house_type_variant_id: UUID | None = None
    house_type_label: str | None = Field(default=None, max_length=120)
    block_id: UUID | None = None
    level_in_block: int | None = Field(default=None, ge=-10, le=200)
    position_on_floor: str | None = Field(default=None, max_length=40)
    orientation: str | None = Field(default=None, max_length=16)
    view_type: str | None = Field(default=None, max_length=40)
    area_m2: Decimal | None = Field(default=None, ge=0)
    garden_area_m2: Decimal | None = Field(default=None, ge=0)
    balcony_area_m2: Decimal | None = Field(default=None, ge=0)
    storage_area_m2: Decimal | None = Field(default=None, ge=0)
    bedrooms: int | None = Field(default=None, ge=0, le=20)
    bathrooms: int | None = Field(default=None, ge=0, le=20)
    parking_spaces: int | None = Field(default=None, ge=0, le=20)
    sun_exposure_hours: Decimal | None = Field(default=None, ge=0, le=24)
    price_base: Decimal | None = Field(default=None, ge=0)
    computed_price: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    status: str | None = Field(
        default=None,
        pattern=r"^(planned|reserved|under_construction|ready|sold|handed_over|held|blocked)$",
    )
    reservation_deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    construction_status_percent: Decimal | None = Field(default=None, ge=0, le=100)
    metadata: dict[str, Any] | None = None


class PlotResponse(BaseModel):
    """Plot returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    development_id: UUID
    plot_number: str
    house_type_id: UUID | None = None
    house_type_variant_id: UUID | None = None
    house_type_label: str | None = None
    block_id: UUID | None = None
    level_in_block: int | None = None
    position_on_floor: str | None = None
    orientation: str | None = None
    view_type: str | None = None
    area_m2: Decimal = Decimal("0")
    garden_area_m2: Decimal | None = None
    balcony_area_m2: Decimal | None = None
    storage_area_m2: Decimal | None = None
    bedrooms: int = 0
    bathrooms: int = 0
    parking_spaces: int = 0
    sun_exposure_hours: Decimal | None = None
    price_base: Decimal = Decimal("0")
    computed_price: Decimal | None = None
    currency: str = ""
    status: str = "planned"
    reservation_deadline: str | None = None
    construction_status_percent: Decimal = Decimal("0")
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # R7: money + numeric area fields as plain-decimal strings.
    @field_serializer(
        "area_m2",
        "price_base",
        "construction_status_percent",
        when_used="json",
    )
    @classmethod
    def _ser_money_required(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"

    @field_serializer(
        "garden_area_m2",
        "balcony_area_m2",
        "storage_area_m2",
        "sun_exposure_hours",
        "computed_price",
        when_used="json",
    )
    @classmethod
    def _ser_money_opt(cls, v: Decimal | None) -> str | None:
        return _serialize_money_string(v)


class PlotReserveRequest(BaseModel):
    """Payload for /plots/{id}/reserve."""

    model_config = ConfigDict(str_strip_whitespace=True)

    buyer_id: UUID | None = None
    full_name: str = Field(default="", max_length=255)
    email: str = Field(default="", max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    language: str = Field(default="en", max_length=10)
    reservation_deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Buyer Option Group ──────────────────────────────────────────────────


class BuyerOptionGroupCreate(BaseModel):
    """Create a buyer option group."""

    model_config = ConfigDict(str_strip_whitespace=True)

    development_id: UUID
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(default="", max_length=255)
    group_type: str = Field(
        default="extras",
        pattern=r"^(kitchen|bathroom|flooring|extras|exterior|technology|other)$",
    )
    display_order: int = Field(default=0, ge=0)
    allow_multiple: bool = False
    max_count: int | None = Field(default=None, ge=1)
    freeze_offset_days_before_handover: int = Field(default=60, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BuyerOptionGroupUpdate(BaseModel):
    """Partial update for a buyer option group."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    group_type: str | None = Field(
        default=None,
        pattern=r"^(kitchen|bathroom|flooring|extras|exterior|technology|other)$",
    )
    display_order: int | None = Field(default=None, ge=0)
    allow_multiple: bool | None = None
    max_count: int | None = Field(default=None, ge=1)
    freeze_offset_days_before_handover: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] | None = None


class BuyerOptionGroupResponse(BaseModel):
    """Buyer option group returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    development_id: UUID
    code: str
    name: str = ""
    group_type: str = "extras"
    display_order: int = 0
    allow_multiple: bool = False
    max_count: int | None = None
    freeze_offset_days_before_handover: int = 60
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Buyer Option ────────────────────────────────────────────────────────


class BuyerOptionCreate(BaseModel):
    """Create a buyer option."""

    model_config = ConfigDict(str_strip_whitespace=True)

    group_id: UUID
    code: str = Field(..., min_length=1, max_length=80)
    name: str = Field(default="", max_length=255)
    sku: str | None = Field(default=None, max_length=120)
    price_delta: Decimal = Field(default=Decimal("0"))
    currency: str = Field(default="", max_length=8)
    lead_time_days: int = Field(default=0, ge=0)
    supplier_name: str | None = Field(default=None, max_length=255)
    thumbnail_url: str | None = Field(default=None, max_length=1024)
    is_active: bool = True
    compatibility_rules: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BuyerOptionUpdate(BaseModel):
    """Partial update for a buyer option."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    sku: str | None = Field(default=None, max_length=120)
    price_delta: Decimal | None = None
    currency: str | None = Field(default=None, max_length=8)
    lead_time_days: int | None = Field(default=None, ge=0)
    supplier_name: str | None = Field(default=None, max_length=255)
    thumbnail_url: str | None = Field(default=None, max_length=1024)
    is_active: bool | None = None
    compatibility_rules: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class BuyerOptionResponse(BaseModel):
    """Buyer option returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    group_id: UUID
    code: str
    name: str = ""
    sku: str | None = None
    price_delta: Decimal = Decimal("0")
    currency: str = ""
    lead_time_days: int = 0
    supplier_name: str | None = None
    thumbnail_url: str | None = None
    is_active: bool = True
    compatibility_rules: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # R7: money fields as plain-decimal strings.
    @field_serializer("price_delta", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


# ── Buyer ───────────────────────────────────────────────────────────────


class BuyerCreate(BaseModel):
    """Create a buyer / lead."""

    model_config = ConfigDict(str_strip_whitespace=True)

    development_id: UUID
    plot_id: UUID | None = None
    portal_user_id: UUID | None = None
    full_name: str = Field(default="", max_length=255)
    email: str = Field(default="", max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    language: str = Field(default="en", max_length=10)
    status: str = Field(
        default="lead",
        pattern=r"^(lead|reserved|contracted|completed|cancelled)$",
    )
    contract_value: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=8)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BuyerUpdate(BaseModel):
    """Partial update for a buyer."""

    model_config = ConfigDict(str_strip_whitespace=True)

    plot_id: UUID | None = None
    portal_user_id: UUID | None = None
    full_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    language: str | None = Field(default=None, max_length=10)
    status: str | None = Field(
        default=None,
        pattern=r"^(lead|reserved|contracted|completed|cancelled)$",
    )
    contract_value: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    contract_signed_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    deposit_paid_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    freeze_deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    # Optional financial / jurisdiction fields exposed so the edit flow
    # introduced in task #134 can adjust them post-contract without
    # forcing the user back through ``POST /buyers/{id}/contract``.
    deposit_amount: Decimal | None = Field(default=None, ge=0)
    jurisdiction: str | None = Field(default=None, max_length=8)
    metadata: dict[str, Any] | None = None


class BuyerResponse(BaseModel):
    """Buyer returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    development_id: UUID
    plot_id: UUID | None = None
    portal_user_id: UUID | None = None
    # Contacts module bridge — see app.modules.contacts.bridge.
    contact_id: UUID | None = None
    full_name: str = ""
    email: str = ""
    phone: str | None = None
    language: str = "en"
    status: str = "lead"
    contract_value: Decimal = Decimal("0")
    currency: str = ""
    contract_signed_at: str | None = None
    deposit_paid_at: str | None = None
    freeze_deadline: str | None = None
    deposit_amount: Decimal = Decimal("0")
    deposit_forfeited: Decimal = Decimal("0")
    deposit_refunded: Decimal = Decimal("0")
    jurisdiction: str = ""
    cancelled_at: str | None = None
    cancelled_reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # R7: money fields as plain-decimal strings.
    @field_serializer(
        "contract_value",
        "deposit_amount",
        "deposit_forfeited",
        "deposit_refunded",
        when_used="json",
    )
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class BuyerContractRequest(BaseModel):
    """Payload for /buyers/{id}/contract."""

    model_config = ConfigDict(str_strip_whitespace=True)

    contract_value: Decimal = Field(..., ge=0)
    currency: str = Field(..., min_length=1, max_length=8)
    contract_signed_at: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    deposit_paid_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    freeze_deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    deposit_amount: Decimal | None = Field(default=None, ge=0)
    jurisdiction: str | None = Field(default=None, max_length=8)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BuyerCancelRequest(BaseModel):
    """Payload for /buyers/{id}/cancel — cancel + compute forfeiture."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cancelled_at: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str = Field(default="", max_length=500)
    jurisdiction_override: str | None = Field(default=None, max_length=8)


class DepositForfeitureResponse(BaseModel):
    """Result of a deposit-forfeiture computation."""

    buyer_id: UUID
    jurisdiction: str
    deposit_amount: Decimal = Decimal("0")
    forfeited_amount: Decimal = Decimal("0")
    refundable_amount: Decimal = Decimal("0")
    rule_citation: str = ""
    rule_summary: str = ""

    # R7: money fields as plain-decimal strings.
    @field_serializer(
        "deposit_amount",
        "forfeited_amount",
        "refundable_amount",
        when_used="json",
    )
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


# ── Buyer Selection ─────────────────────────────────────────────────────


class BuyerSelectionCreate(BaseModel):
    """Create a buyer selection."""

    model_config = ConfigDict(str_strip_whitespace=True)

    buyer_id: UUID
    status: str = Field(default="draft", pattern=r"^(draft|submitted|locked|cancelled)$")
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BuyerSelectionUpdate(BaseModel):
    """Partial update for a buyer selection."""

    model_config = ConfigDict(str_strip_whitespace=True)

    status: str | None = Field(default=None, pattern=r"^(draft|submitted|locked|cancelled)$")
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class BuyerSelectionResponse(BaseModel):
    """Buyer selection returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    buyer_id: UUID
    status: str = "draft"
    submitted_at: str | None = None
    locked_at: str | None = None
    total_options_value: Decimal = Decimal("0")
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class BuyerSelectionItemCreate(BaseModel):
    """Create a buyer selection item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    option_id: UUID
    quantity: int = Field(default=1, ge=1)
    unit_price_snapshot: Decimal | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BuyerSelectionItemResponse(BaseModel):
    """Buyer selection item returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    selection_id: UUID
    option_id: UUID
    quantity: int = 1
    unit_price_snapshot: Decimal = Decimal("0")
    total_price: Decimal = Decimal("0")
    included_in_production: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # R7: money fields as plain-decimal strings.
    @field_serializer("unit_price_snapshot", "total_price", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


# ── Handover & Snag ─────────────────────────────────────────────────────


class HandoverCreate(BaseModel):
    """Create a handover record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    plot_id: UUID
    scheduled_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HandoverUpdate(BaseModel):
    """Partial update for a handover record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    scheduled_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    completed_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    snag_count_at_handover: int | None = Field(default=None, ge=0)
    final_check_passed: bool | None = None
    keys_handed_over_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    customer_signature_ref: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class HandoverResponse(BaseModel):
    """Handover record returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    plot_id: UUID
    scheduled_at: str | None = None
    completed_at: str | None = None
    snag_count_at_handover: int = 0
    final_check_passed: bool = False
    keys_handed_over_at: str | None = None
    customer_signature_ref: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class HandoverCompleteRequest(BaseModel):
    """Payload for /handovers/{id}/complete."""

    model_config = ConfigDict(str_strip_whitespace=True)

    completed_at: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    customer_signature_ref: str = Field(..., min_length=1, max_length=255)
    keys_handed_over_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    final_check_passed: bool = True
    snag_count_at_handover: int = Field(default=0, ge=0)
    notes: str | None = None


_SNAG_CATEGORY_PATTERN = (
    r"^(cosmetic|functional|structural|mechanical|electrical|plumbing|"
    r"finishing|exterior|general|safety)$"
)


class SnagCreate(BaseModel):
    """Create a snag entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    handover_id: UUID
    buyer_id: UUID | None = None
    category: str = Field(default="general", pattern=_SNAG_CATEGORY_PATTERN)
    location_in_plot: str | None = Field(default=None, max_length=255)
    severity: str = Field(default="minor", pattern=r"^(cosmetic|minor|major|safety)$")
    description: str = Field(..., min_length=1)
    status: str = Field(default="open", pattern=r"^(open|in_progress|fixed|wont_fix)$")
    reported_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    cost_impact: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    metadata: dict[str, Any] = Field(default_factory=dict)


class SnagUpdate(BaseModel):
    """Partial update for a snag entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    category: str | None = Field(default=None, pattern=_SNAG_CATEGORY_PATTERN)
    location_in_plot: str | None = Field(default=None, max_length=255)
    severity: str | None = Field(default=None, pattern=r"^(cosmetic|minor|major|safety)$")
    description: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, pattern=r"^(open|in_progress|fixed|wont_fix)$")
    fixed_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    fix_notes: str | None = None
    cost_impact: Decimal | None = Field(default=None, ge=Decimal("0"))
    metadata: dict[str, Any] | None = None


class SnagResponse(BaseModel):
    """Snag returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    handover_id: UUID
    buyer_id: UUID | None = None
    category: str = "general"
    location_in_plot: str | None = None
    severity: str = "minor"
    description: str = ""
    status: str = "open"
    reported_at: str | None = None
    fixed_at: str | None = None
    fix_notes: str | None = None
    cost_impact: Decimal = Decimal("0")
    photos: list[str] = Field(default_factory=list)
    linked_punch_item_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Warranty ────────────────────────────────────────────────────────────


class WarrantyClaimCreate(BaseModel):
    """Create a warranty claim."""

    model_config = ConfigDict(str_strip_whitespace=True)

    plot_id: UUID
    buyer_id: UUID
    handover_id: UUID | None = None
    source_snag_id: UUID | None = None
    assigned_to_user_id: UUID | None = None
    raised_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    category: str = Field(
        default="defect",
        pattern=r"^(defect|snag|service|structural|cosmetic|mep)$",
    )
    severity: str = Field(default="minor", pattern=r"^(minor|major|critical)$")
    description: str = Field(..., min_length=1)
    photos: list[str] = Field(default_factory=list)
    status: str = Field(
        default="raised",
        pattern=r"^(raised|under_review|accepted|rejected|closed)$",
    )
    sla_deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    linked_service_ticket_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WarrantyClaimUpdate(BaseModel):
    """Partial update for a warranty claim."""

    model_config = ConfigDict(str_strip_whitespace=True)

    category: str | None = Field(
        default=None,
        pattern=r"^(defect|snag|service|structural|cosmetic|mep)$",
    )
    severity: str | None = Field(default=None, pattern=r"^(minor|major|critical)$")
    description: str | None = Field(default=None, min_length=1)
    photos: list[str] | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(raised|under_review|accepted|rejected|closed)$",
    )
    assigned_to_user_id: UUID | None = None
    sla_deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    handover_id: UUID | None = None
    resolution_notes: str | None = None
    accepted_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    closed_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    linked_service_ticket_id: UUID | None = None
    metadata: dict[str, Any] | None = None


class WarrantyClaimAssignRequest(BaseModel):
    """Assign or unassign a warranty claim."""

    model_config = ConfigDict(str_strip_whitespace=True)

    assigned_to_user_id: UUID | None = None


class WarrantyClaimResponse(BaseModel):
    """Warranty claim returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    plot_id: UUID
    buyer_id: UUID
    handover_id: UUID | None = None
    source_snag_id: UUID | None = None
    assigned_to_user_id: UUID | None = None
    raised_at: str | None = None
    category: str = "defect"
    severity: str = "minor"
    description: str = ""
    photos: list[str] = Field(default_factory=list)
    status: str = "raised"
    sla_deadline: str | None = None
    accepted_at: str | None = None
    closed_at: str | None = None
    resolution_notes: str | None = None
    linked_service_ticket_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    # Computed at read-time by the service layer (see
    # ``PropertyDevService._is_in_warranty``). True when raised_at falls
    # within the structural-warranty window from Handover.completed_at.
    is_in_warranty: bool = False
    created_at: datetime
    updated_at: datetime


# ── Composite responses ─────────────────────────────────────────────────


class PlotPricingResponse(BaseModel):
    """Pricing breakdown for a plot."""

    plot_id: UUID
    base_price: Decimal
    variant_modifier_value: Decimal = Decimal("0")
    selections_total: Decimal = Decimal("0")
    final_price: Decimal
    currency: str = ""


class BuyerConfiguratorResponse(BaseModel):
    """Configurator state for a buyer on a plot."""

    plot: PlotResponse
    house_type: HouseTypeResponse | None = None
    variant: HouseTypeVariantResponse | None = None
    option_groups: list[BuyerOptionGroupResponse] = Field(default_factory=list)
    options_by_group: dict[str, list[BuyerOptionResponse]] = Field(default_factory=dict)
    current_selection: BuyerSelectionResponse | None = None
    current_items: list[BuyerSelectionItemResponse] = Field(default_factory=list)
    pricing: PlotPricingResponse | None = None


class DevelopmentDashboard(BaseModel):
    """Sales dashboard KPIs for a development."""

    development_id: UUID
    total_plots: int = 0
    plots_by_status: dict[str, int] = Field(default_factory=dict)
    buyers_by_status: dict[str, int] = Field(default_factory=dict)
    contracted_value: Decimal = Decimal("0")
    open_snags: int = 0
    open_warranty_claims: int = 0
    completed_handovers: int = 0
    scheduled_handovers: int = 0
    sell_through_percent: Decimal = Decimal("0")


# ── Handover docs ───────────────────────────────────────────────────────


_HANDOVER_DOC_TYPES = (
    r"^(warranty|manual|key_receipt|hs_file|epc|nhbc|inspection_cert|certificate_completion|insurance|other)$"
)


class HandoverDocCreate(BaseModel):
    """Create a handover document entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    handover_id: UUID
    doc_type: str = Field(..., pattern=_HANDOVER_DOC_TYPES)
    title: str = Field(default="", max_length=255)
    file_url: str | None = Field(default=None, max_length=1024)
    is_required: bool = False
    is_delivered: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class HandoverDocUpdate(BaseModel):
    """Patch a handover document entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=255)
    file_url: str | None = Field(default=None, max_length=1024)
    is_required: bool | None = None
    is_delivered: bool | None = None
    metadata: dict[str, Any] | None = None


class HandoverDocResponse(BaseModel):
    """Handover doc returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    handover_id: UUID
    doc_type: str
    title: str = ""
    file_url: str | None = None
    is_required: bool = False
    is_delivered: bool = False
    delivered_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class HandoverBundleResponse(BaseModel):
    """Aggregate of all handover docs + missing-required-doc warning."""

    handover_id: UUID
    docs: list[HandoverDocResponse] = Field(default_factory=list)
    delivered_count: int = 0
    required_count: int = 0
    missing_required: list[str] = Field(default_factory=list)
    ready_for_handover: bool = True


# ── Sales pipeline kanban ───────────────────────────────────────────────


class SalesKanbanBuyerCard(BaseModel):
    """One buyer card on the kanban."""

    buyer_id: UUID
    full_name: str
    email: str = ""
    plot_id: UUID | None = None
    plot_number: str | None = None
    status: str
    contract_value: Decimal = Decimal("0")
    currency: str = ""
    contract_signed_at: str | None = None
    freeze_deadline: str | None = None

    # R8: money fields as plain-decimal strings (matches BuyerResponse).
    @field_serializer("contract_value", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class SalesKanbanColumn(BaseModel):
    """One column on the kanban (one status)."""

    status: str
    buyers: list[SalesKanbanBuyerCard] = Field(default_factory=list)
    count: int = 0
    total_value: Decimal = Decimal("0")

    # R8: money fields as plain-decimal strings.
    @field_serializer("total_value", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class SalesKanbanResponse(BaseModel):
    """Kanban response — one column per buyer-status."""

    development_id: UUID
    columns: list[SalesKanbanColumn] = Field(default_factory=list)


# ── Reservation calendar ────────────────────────────────────────────────


class ReservationCalendarEntry(BaseModel):
    """One entry on the reservation calendar."""

    plot_id: UUID
    plot_number: str
    buyer_id: UUID | None = None
    buyer_name: str = ""
    reservation_deadline: str | None = None
    freeze_deadline: str | None = None
    status: str


class ReservationCalendarResponse(BaseModel):
    """All upcoming reservation-related deadlines for a development."""

    development_id: UUID
    period_start: str
    period_end: str
    entries: list[ReservationCalendarEntry] = Field(default_factory=list)


# ── Development P&L ─────────────────────────────────────────────────────


class DevelopmentPnLResponse(BaseModel):
    """Aggregate P&L for a development.

    Reads from CRM/finance via the cross-module events; service-layer
    aggregates contract revenue + actual costs + deposit retention.
    """

    development_id: UUID
    currency: str = ""
    mixed_currency: bool = False
    revenue_contracted: Decimal = Decimal("0")
    revenue_completed: Decimal = Decimal("0")
    deposits_held: Decimal = Decimal("0")
    deposits_forfeited: Decimal = Decimal("0")
    plot_count_sold: int = 0
    plot_count_handed_over: int = 0
    avg_sale_price: Decimal = Decimal("0")
    open_warranty_count: int = 0
    open_snag_count: int = 0

    # R8: money fields as plain-decimal strings.
    @field_serializer(
        "revenue_contracted",
        "revenue_completed",
        "deposits_held",
        "deposits_forfeited",
        "avg_sale_price",
        when_used="json",
    )
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


# ──────────────────────────────────────────────────────────────────────────
# R6 — Lead / Reservation / SalesContract / PaymentSchedule / ContractParty
# ──────────────────────────────────────────────────────────────────────────


def _strict_currency_validator(value: str | None) -> str | None:
    """Coerce empty-string to None; uppercase + validate 3-letter ISO."""
    if value is None or value == "":
        return value
    value = value.upper()
    if len(value) != 3 or not value.isalpha():
        raise ValueError("currency must be a 3-letter ISO code")
    return value


# ── Lead ────────────────────────────────────────────────────────────────


class LeadCreate(BaseModel):
    """Create a new lead at the top of the funnel."""

    model_config = ConfigDict(str_strip_whitespace=True)

    development_id: UUID | None = None
    tenant_id: UUID | None = None
    source: str = Field(default="other", pattern=_LEAD_SOURCE_PATTERN)
    lead_score: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    assigned_agent_user_id: UUID | None = None
    status: str = Field(default="new", pattern=_LEAD_STATUS_PATTERN)
    nurture_stage: str | None = None
    full_name: str = Field(default="", max_length=255)
    email: str = Field(default="", max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    language: str = Field(default="en", max_length=10)
    budget_min: Decimal | None = Field(default=None, ge=0)
    budget_max: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="", max_length=8)
    preferred_house_type_id: UUID | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def _v_currency(cls, v: str) -> str:
        return _strict_currency_validator(v) or ""


class LeadUpdate(BaseModel):
    """Partial update for a lead."""

    model_config = ConfigDict(str_strip_whitespace=True)

    development_id: UUID | None = None
    source: str | None = Field(default=None, pattern=_LEAD_SOURCE_PATTERN)
    lead_score: Decimal | None = Field(default=None, ge=0, le=100)
    assigned_agent_user_id: UUID | None = None
    status: str | None = Field(default=None, pattern=_LEAD_STATUS_PATTERN)
    nurture_stage: str | None = None
    full_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    language: str | None = Field(default=None, max_length=10)
    budget_min: Decimal | None = Field(default=None, ge=0)
    budget_max: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    preferred_house_type_id: UUID | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("currency")
    @classmethod
    def _v_currency(cls, v: str | None) -> str | None:
        return _strict_currency_validator(v)


class LeadResponse(BaseModel):
    """Lead returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    development_id: UUID | None = None
    tenant_id: UUID | None = None
    # Contacts module bridge — see app.modules.contacts.bridge.
    contact_id: UUID | None = None
    source: str = "other"
    lead_score: Decimal = Decimal("0")
    assigned_agent_user_id: UUID | None = None
    status: str = "new"
    nurture_stage: str | None = None
    full_name: str = ""
    email: str = ""
    phone: str | None = None
    language: str = "en"
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    currency: str = ""
    preferred_house_type_id: UUID | None = None
    notes: str | None = None
    converted_to_buyer_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # R8: money / score fields as plain-decimal strings.
    @field_serializer(
        "lead_score",
        "budget_min",
        "budget_max",
        when_used="json",
    )
    @classmethod
    def _ser_money(cls, v: Decimal | None) -> str | None:
        return _serialize_money_string(v)


class LeadConvertToReservationRequest(BaseModel):
    """Convert a Lead into a Reservation on a plot."""

    model_config = ConfigDict(str_strip_whitespace=True)

    plot_id: UUID
    deposit_amount: Decimal = Field(..., ge=0)
    currency: str = Field(..., min_length=3, max_length=3)
    cooling_off_days: int = Field(default=7, ge=0, le=90)
    expires_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    # Optional Buyer-shadow creation. When True a Buyer row is materialised
    # from the Lead data so downstream modules (selections, handover, ...)
    # have something to link against.
    create_buyer: bool = True

    @field_validator("currency")
    @classmethod
    def _v_currency(cls, v: str) -> str:
        return _strict_currency_validator(v) or ""


# ── Reservation ─────────────────────────────────────────────────────────


class ReservationCreate(BaseModel):
    """Create a standalone reservation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    plot_id: UUID
    lead_id: UUID | None = None
    buyer_id: UUID | None = None
    tenant_id: UUID | None = None
    # Auto-generated when omitted — see ``next_reservation_number``.
    reservation_number: str | None = Field(default=None, pattern=_RESERVATION_NUMBER_PATTERN)
    deposit_amount: Decimal = Field(..., ge=0)
    currency: str = Field(..., min_length=3, max_length=3)
    cooling_off_days: int = Field(default=7, ge=0, le=90)
    expires_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def _v_currency(cls, v: str) -> str:
        return _strict_currency_validator(v) or ""


class ReservationUpdate(BaseModel):
    """Partial update for a reservation (limited fields — FSM elsewhere)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    expires_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    cooling_off_days: int | None = Field(default=None, ge=0, le=90)
    metadata: dict[str, Any] | None = None


class ReservationResponse(BaseModel):
    """Reservation returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    plot_id: UUID
    lead_id: UUID | None = None
    buyer_id: UUID | None = None
    tenant_id: UUID | None = None
    reservation_number: str
    deposit_amount: Decimal = Decimal("0")
    currency: str = ""
    deposit_paid_at: datetime | None = None
    cooling_off_days: int = 7
    cooling_off_until: str | None = None
    expires_at: str | None = None
    status: str = "active"
    # Pricing-engine snapshot captured at reservation create — see
    # ``property_dev.pricing_engine.PriceQuote``. Empty dict for legacy
    # rows pre-dating the snapshot column.
    price_breakdown_snapshot: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # R8: money fields as plain-decimal strings.
    @field_serializer("deposit_amount", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class ReservationConvertToSpaRequest(BaseModel):
    """Convert a Reservation into a SalesContract (SPA)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    contract_number: str | None = Field(default=None, pattern=_CONTRACT_NUMBER_PATTERN)
    signing_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    governing_law: str = Field(default="", max_length=16)
    language: str = Field(default="en", max_length=10)
    total_value: Decimal = Field(..., ge=0)
    currency: str = Field(..., min_length=3, max_length=3)
    total_price_breakdown: dict[str, Any] = Field(default_factory=dict)
    terms_version: str = Field(default="", max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def _v_currency(cls, v: str) -> str:
        return _strict_currency_validator(v) or ""


# ── SalesContract (SPA) ─────────────────────────────────────────────────


class SalesContractCreate(BaseModel):
    """Create a draft SPA. Multi-buyer parties added via ContractParty."""

    model_config = ConfigDict(str_strip_whitespace=True)

    contract_number: str | None = Field(default=None, pattern=_CONTRACT_NUMBER_PATTERN)
    plot_id: UUID
    reservation_id: UUID | None = None
    tenant_id: UUID | None = None
    signing_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    governing_law: str = Field(default="", max_length=16)
    language: str = Field(default="en", max_length=10)
    total_price_breakdown: dict[str, Any] = Field(default_factory=dict)
    total_value: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=3)
    e_sign_envelope_id: str | None = Field(default=None, max_length=255)
    parent_contract_id: UUID | None = None
    revision_number: int = Field(default=1, ge=1)
    terms_version: str = Field(default="", max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def _v_currency(cls, v: str) -> str:
        return _strict_currency_validator(v) or ""


class SalesContractUpdate(BaseModel):
    """Partial update for a draft SPA."""

    model_config = ConfigDict(str_strip_whitespace=True)

    signing_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    governing_law: str | None = Field(default=None, max_length=16)
    language: str | None = Field(default=None, max_length=10)
    total_price_breakdown: dict[str, Any] | None = None
    total_value: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    e_sign_envelope_id: str | None = Field(default=None, max_length=255)
    terms_version: str | None = Field(default=None, max_length=80)
    metadata: dict[str, Any] | None = None

    @field_validator("currency")
    @classmethod
    def _v_currency(cls, v: str | None) -> str | None:
        return _strict_currency_validator(v)


class SalesContractResponse(BaseModel):
    """SPA returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    contract_number: str
    plot_id: UUID
    reservation_id: UUID | None = None
    tenant_id: UUID | None = None
    signing_date: str | None = None
    governing_law: str = ""
    language: str = "en"
    total_price_breakdown: dict[str, Any] = Field(default_factory=dict)
    total_value: Decimal = Decimal("0")
    currency: str = ""
    e_sign_envelope_id: str | None = None
    status: str = "draft"
    parent_contract_id: UUID | None = None
    revision_number: int = 1
    terms_version: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # R8: money fields as plain-decimal strings.
    @field_serializer("total_value", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class SalesContractSendForSignatureRequest(BaseModel):
    """Trigger envelope creation + email-out to all parties."""

    model_config = ConfigDict(str_strip_whitespace=True)

    e_sign_envelope_id: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SalesContractSignRequest(BaseModel):
    """Countersign — developer side. Buyer-side signing is per-party."""

    model_config = ConfigDict(str_strip_whitespace=True)

    signing_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


# ── PaymentSchedule ─────────────────────────────────────────────────────


class PaymentScheduleCreate(BaseModel):
    """Create a payment schedule attached to an SPA."""

    model_config = ConfigDict(str_strip_whitespace=True)

    sales_contract_id: UUID
    tenant_id: UUID | None = None
    currency: str = Field(..., min_length=3, max_length=3)
    total_amount: Decimal = Field(..., ge=0)
    late_fee_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    grace_period_days: int = Field(default=0, ge=0, le=365)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def _v_currency(cls, v: str) -> str:
        return _strict_currency_validator(v) or ""


class PaymentScheduleUpdate(BaseModel):
    """Partial update for an active schedule (rates, grace)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    late_fee_pct: Decimal | None = Field(default=None, ge=0, le=100)
    grace_period_days: int | None = Field(default=None, ge=0, le=365)
    metadata: dict[str, Any] | None = None


class PaymentScheduleResponse(BaseModel):
    """PaymentSchedule returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    sales_contract_id: UUID
    tenant_id: UUID | None = None
    currency: str = ""
    total_amount: Decimal = Decimal("0")
    late_fee_pct: Decimal = Decimal("0")
    grace_period_days: int = 0
    status: str = "active"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # R8: money fields as plain-decimal strings.
    @field_serializer("total_amount", "late_fee_pct", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


# ── Instalment ──────────────────────────────────────────────────────────


class InstalmentCreate(BaseModel):
    """Create one instalment line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    schedule_id: UUID
    sequence: int = Field(..., ge=1)
    milestone_label: str = Field(default="", max_length=255)
    milestone_event: str = Field(default="", max_length=80)
    due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    amount: Decimal = Field(..., ge=0)
    invoice_ref: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InstalmentUpdate(BaseModel):
    """Partial update for an instalment line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    milestone_label: str | None = Field(default=None, max_length=255)
    milestone_event: str | None = Field(default=None, max_length=80)
    due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    amount: Decimal | None = Field(default=None, ge=0)
    invoice_ref: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] | None = None


class InstalmentResponse(BaseModel):
    """Instalment returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    schedule_id: UUID
    sequence: int
    milestone_label: str = ""
    milestone_event: str = ""
    due_date: str | None = None
    amount: Decimal = Decimal("0")
    amount_paid: Decimal = Decimal("0")
    paid_at: datetime | None = None
    status: str = "pending"
    late_fee_accrued: Decimal = Decimal("0")
    invoice_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # R8: money fields as plain-decimal strings.
    @field_serializer(
        "amount",
        "amount_paid",
        "late_fee_accrued",
        when_used="json",
    )
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class InstalmentMarkPaidRequest(BaseModel):
    """Apply a payment against an instalment."""

    model_config = ConfigDict(str_strip_whitespace=True)

    amount: Decimal = Field(..., gt=0)
    paid_at: datetime | None = None
    invoice_ref: str | None = Field(default=None, max_length=255)


class InstalmentWaiveRequest(BaseModel):
    """Manager waiver of an instalment (e.g. goodwill resolution)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(default="", max_length=500)


# ── ContractParty ───────────────────────────────────────────────────────


class ContractPartyCreate(BaseModel):
    """Add a Buyer to a SalesContract as a party."""

    model_config = ConfigDict(str_strip_whitespace=True)

    sales_contract_id: UUID
    buyer_id: UUID
    ownership_pct: Decimal = Field(..., ge=0, le=100)
    party_role: str = Field(default="primary", pattern=_PARTY_ROLE_PATTERN)
    signing_order: int = Field(default=0, ge=0)
    signature_ref: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ownership_pct")
    @classmethod
    def _v_ownership_decimals(cls, v: Decimal) -> Decimal:
        # Allow up to 2 decimal places.
        q = v.quantize(Decimal("0.01"))
        if q != v:
            raise ValueError("ownership_pct supports at most 2 decimals")
        return v


class ContractPartyUpdate(BaseModel):
    """Mutate a party (typically ownership_pct or signed_at)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    ownership_pct: Decimal | None = Field(default=None, ge=0, le=100)
    party_role: str | None = Field(default=None, pattern=_PARTY_ROLE_PATTERN)
    signing_order: int | None = Field(default=None, ge=0)
    signed_at: datetime | None = None
    signature_ref: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] | None = None


class ContractPartyResponse(BaseModel):
    """ContractParty returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    sales_contract_id: UUID
    buyer_id: UUID
    ownership_pct: Decimal = Decimal("0")
    party_role: str = "primary"
    signing_order: int = 0
    signed_at: datetime | None = None
    signature_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class ReservationExpiryBatchResponse(BaseModel):
    """Result of /reservations/expire-overdue."""

    expired_count: int = 0
    expired_ids: list[UUID] = Field(default_factory=list)


# Marker for tooling — re-export _CURRENCY_PATTERN to suppress lint
# warning about unused module-scope constants when only schemas import.
_USED_SENTINELS = (
    _CURRENCY_PATTERN,
    _LEAD_STATUS_PATTERN,
    _RESERVATION_STATUS_PATTERN,
    _SPA_STATUS_PATTERN,
    _SCHEDULE_STATUS_PATTERN,
    _INSTALMENT_STATUS_PATTERN,
)


# ════════════════════════════════════════════════════════════════════════
# Task #138 — Broker / Commission / Escrow / PriceMatrix / Phase / Block
# ════════════════════════════════════════════════════════════════════════


# ── Common validators ───────────────────────────────────────────────────


_REGULATOR_REFS = (
    "rera_dubai",
    "rera_abu_dhabi",
    "maharera",
    "214_FZ_RU",
    "cma_saudi",
    "section32_au",
    "other",
)
_REGULATOR_REF_PATTERN = r"^(rera_dubai|rera_abu_dhabi|maharera|214_FZ_RU|cma_saudi|section32_au|other)$"

# Loose IBAN format: 15-34 alphanumeric, first 2 letters = country code,
# next 2 = check digits. Real-world IBANs span this range; we do not run
# the mod-97 check here to keep this layer purely structural.
_IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")


def _validate_iban(value: str) -> str:
    """Validate IBAN structurally. Empty string is allowed (no IBAN set)."""
    if not value:
        return value
    normalised = value.replace(" ", "").upper()
    if not _IBAN_RE.match(normalised):
        raise ValueError(
            "Invalid IBAN format — expected 15-34 alphanumeric chars starting "
            "with 2-letter country code + 2-digit checksum"
        )
    return normalised


def _validate_iso_date_order(start: str | None, end: str | None, *, field_pair: str) -> None:
    """Reject ``effective_from > effective_to`` style mistakes."""
    if start and end and start > end:
        raise ValueError(f"{field_pair}: effective_from ({start}) must precede effective_to ({end})")


# ── Phase ───────────────────────────────────────────────────────────────


class PhaseCreate(BaseModel):
    """Create a sales/build Phase within a Development."""

    model_config = ConfigDict(str_strip_whitespace=True)

    development_id: UUID
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(default="", max_length=255)
    sequence: int = Field(default=0, ge=0)
    planned_start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    planned_end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    status: str = Field(
        default="planned",
        pattern=r"^(planned|under_construction|completed)$",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_dates(self) -> PhaseCreate:
        _validate_iso_date_order(self.planned_start, self.planned_end, field_pair="phase")
        return self


class PhaseUpdate(BaseModel):
    """Partial update for a Phase."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    sequence: int | None = Field(default=None, ge=0)
    planned_start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    planned_end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    status: str | None = Field(default=None, pattern=r"^(planned|under_construction|completed)$")
    metadata: dict[str, Any] | None = None


class PhaseResponse(BaseModel):
    """Phase as returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    development_id: UUID
    code: str
    name: str = ""
    sequence: int = 0
    planned_start: str | None = None
    planned_end: str | None = None
    status: str = "planned"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Block ───────────────────────────────────────────────────────────────


class BlockCreate(BaseModel):
    """Create a Block within a Phase."""

    model_config = ConfigDict(str_strip_whitespace=True)

    phase_id: UUID
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(default="", max_length=255)
    levels_count: int = Field(default=1, ge=1, le=400)
    units_per_level: int = Field(default=1, ge=1, le=200)
    orientation: str | None = Field(default=None, max_length=16)
    geo_coordinates: dict[str, Any] | None = None
    status: str = Field(
        default="planned",
        pattern=r"^(planned|under_construction|handed_over)$",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class BlockUpdate(BaseModel):
    """Partial update for a Block."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    levels_count: int | None = Field(default=None, ge=1, le=400)
    units_per_level: int | None = Field(default=None, ge=1, le=200)
    orientation: str | None = Field(default=None, max_length=16)
    geo_coordinates: dict[str, Any] | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(planned|under_construction|handed_over)$",
    )
    metadata: dict[str, Any] | None = None


class BlockResponse(BaseModel):
    """Block as returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    phase_id: UUID
    code: str
    name: str = ""
    levels_count: int = 1
    units_per_level: int = 1
    orientation: str | None = None
    geo_coordinates: dict[str, Any] | None = None
    status: str = "planned"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Broker ──────────────────────────────────────────────────────────────


class BrokerCreate(BaseModel):
    """Create a Broker master record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    tenant_id: UUID | None = None
    name: str = Field(..., min_length=1, max_length=255)
    license_number: str = Field(..., min_length=1, max_length=120)
    # ISO 3166-2 region code such as "AE-DU"; we allow blank for staging.
    jurisdiction: str = Field(default="", max_length=16)
    contact_email: str = Field(default="", max_length=255)
    contact_phone: str | None = Field(default=None, max_length=40)
    default_commission_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    kyc_status: str = Field(default="pending", pattern=r"^(pending|verified|expired|rejected)$")
    active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class BrokerUpdate(BaseModel):
    """Partial update for a Broker."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    license_number: str | None = Field(default=None, min_length=1, max_length=120)
    jurisdiction: str | None = Field(default=None, max_length=16)
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=40)
    default_commission_pct: Decimal | None = Field(default=None, ge=0, le=100)
    kyc_status: str | None = Field(default=None, pattern=r"^(pending|verified|expired|rejected)$")
    active: bool | None = None
    metadata: dict[str, Any] | None = None


class BrokerResponse(BaseModel):
    """Broker as returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tenant_id: UUID | None = None
    name: str
    license_number: str
    jurisdiction: str = ""
    contact_email: str = ""
    contact_phone: str | None = None
    default_commission_pct: Decimal = Decimal("0")
    kyc_status: str = "pending"
    kyc_verified_at: datetime | None = None
    active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Commission structure (discriminated union) ─────────────────────────


class FlatCommissionStructure(BaseModel):
    """Single fixed amount in a given currency."""

    type: Literal["flat"] = "flat"
    amount: Decimal = Field(..., ge=0)
    currency: str = Field(..., min_length=3, max_length=3)


class PercentCommissionStructure(BaseModel):
    """Single percentage of the base amount."""

    type: Literal["percent"] = "percent"
    pct: Decimal = Field(..., ge=0, le=100)


class LadderTier(BaseModel):
    """One tier in a ladder commission structure."""

    threshold: Decimal = Field(..., ge=0)
    pct: Decimal = Field(..., ge=0, le=100)


class LadderCommissionStructure(BaseModel):
    """Tiered commission: highest threshold whose ``base >= threshold`` wins."""

    type: Literal["ladder"] = "ladder"
    tiers: list[LadderTier] = Field(..., min_length=1)


# ── CommissionAgreement ────────────────────────────────────────────────


class CommissionAgreementCreate(BaseModel):
    """Create a CommissionAgreement.

    ``structure`` is a free-form JSON shape; the explicit ``structure_type``
    field tells us which validator to apply when reading it back. We
    validate the shape via :meth:`_check_structure`.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    broker_id: UUID
    development_id: UUID | None = None
    specific_plot_ids: list[UUID] | None = None
    structure_type: str = Field(..., pattern=r"^(flat|percent|ladder)$")
    structure: dict[str, Any] = Field(default_factory=dict)
    accrual_trigger: str = Field(
        default="spa_signed",
        pattern=r"^(lead_qualified|reservation_paid|spa_signed|handover_complete)$",
    )
    payout_terms: str = Field(
        default="net30",
        pattern=r"^(immediate|net30|net60|per_milestone)$",
    )
    withholding_tax_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    currency: str = Field(..., min_length=3, max_length=8)
    effective_from: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    effective_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    status: str = Field(default="draft", pattern=r"^(draft|active|expired|cancelled)$")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_structure(self) -> CommissionAgreementCreate:
        """Validate the JSONB structure with plain-Python checks.

        We *don't* delegate to PercentCommissionStructure.model_validate
        here: when Pydantic raises in a nested validator, the resulting
        ValidationError carries Decimal-typed ``input`` values that
        FastAPI's default JSON serialiser refuses to emit (the 422
        response then 500s with ``Decimal is not JSON serializable``).
        Manual validation keeps every error value as a JSON-safe string.
        """
        try:
            if self.structure_type == "flat":
                amount = self.structure.get("amount")
                currency = self.structure.get("currency")
                if amount is None or currency is None:
                    raise ValueError("flat structure requires {amount, currency}")
                amt_dec = Decimal(str(amount))
                if amt_dec < 0:
                    raise ValueError("amount must be >= 0")
                if not isinstance(currency, str) or len(currency) != 3:
                    raise ValueError("currency must be a 3-letter ISO code")
            elif self.structure_type == "percent":
                pct = self.structure.get("pct")
                if pct is None:
                    raise ValueError("percent structure requires {pct}")
                pct_dec = Decimal(str(pct))
                if pct_dec < 0 or pct_dec > 100:
                    raise ValueError("pct must be between 0 and 100")
            elif self.structure_type == "ladder":
                tiers = self.structure.get("tiers")
                if not tiers or not isinstance(tiers, list):
                    raise ValueError("ladder structure requires non-empty tiers[]")
                for tier in tiers:
                    t = Decimal(str(tier.get("threshold", 0)))
                    p = Decimal(str(tier.get("pct", 0)))
                    if t < 0:
                        raise ValueError("tier.threshold must be >= 0")
                    if p < 0 or p > 100:
                        raise ValueError("tier.pct must be between 0 and 100")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid {self.structure_type!r} commission structure: {exc}") from exc
        _validate_iso_date_order(
            self.effective_from,
            self.effective_to,
            field_pair="commission_agreement",
        )
        return self


class CommissionAgreementUpdate(BaseModel):
    """Partial update for a CommissionAgreement."""

    model_config = ConfigDict(str_strip_whitespace=True)

    development_id: UUID | None = None
    specific_plot_ids: list[UUID] | None = None
    structure_type: str | None = Field(default=None, pattern=r"^(flat|percent|ladder)$")
    structure: dict[str, Any] | None = None
    accrual_trigger: str | None = Field(
        default=None,
        pattern=r"^(lead_qualified|reservation_paid|spa_signed|handover_complete)$",
    )
    payout_terms: str | None = Field(default=None, pattern=r"^(immediate|net30|net60|per_milestone)$")
    withholding_tax_pct: Decimal | None = Field(default=None, ge=0, le=100)
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    effective_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    effective_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    status: str | None = Field(default=None, pattern=r"^(draft|active|expired|cancelled)$")
    metadata: dict[str, Any] | None = None


class CommissionAgreementResponse(BaseModel):
    """CommissionAgreement as returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    broker_id: UUID
    development_id: UUID | None = None
    specific_plot_ids: list[Any] | None = None
    structure_type: str = "percent"
    structure: dict[str, Any] = Field(default_factory=dict)
    accrual_trigger: str = "spa_signed"
    payout_terms: str = "net30"
    withholding_tax_pct: Decimal = Decimal("0")
    currency: str = ""
    effective_from: str = ""
    effective_to: str | None = None
    status: str = "draft"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # R8: percent / money fields as plain-decimal strings.
    @field_serializer("withholding_tax_pct", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


# ── CommissionAccrual ───────────────────────────────────────────────────


class CommissionAccrualResponse(BaseModel):
    """CommissionAccrual as returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    agreement_id: UUID
    broker_id: UUID
    trigger_event: str = ""
    trigger_entity_type: str = ""
    trigger_entity_id: UUID | None = None
    base_amount: Decimal = Decimal("0")
    commission_amount: Decimal = Decimal("0")
    currency: str = ""
    state: str = "accrued"
    accrued_at: datetime | None = None
    approved_at: datetime | None = None
    paid_at: datetime | None = None
    payment_ref: str | None = None
    withholding_amount: Decimal = Decimal("0")
    net_payable: Decimal = Decimal("0")
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # R7: money fields as plain-decimal strings.
    @field_serializer(
        "base_amount",
        "commission_amount",
        "withholding_amount",
        "net_payable",
        when_used="json",
    )
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class CommissionAccrualPayRequest(BaseModel):
    """Payload for /commission-accruals/{id}/pay."""

    model_config = ConfigDict(str_strip_whitespace=True)

    payment_ref: str = Field(..., min_length=1, max_length=255)


# ── EscrowAccount ───────────────────────────────────────────────────────


class EscrowAccountCreate(BaseModel):
    """Create a regulator-supervised EscrowAccount."""

    model_config = ConfigDict(str_strip_whitespace=True)

    development_id: UUID
    regulator_ref: str = Field(..., pattern=_REGULATOR_REF_PATTERN)
    regulator_account_number: str = Field(default="", max_length=120)
    bank_name: str = Field(default="", max_length=255)
    iban: str = Field(default="", max_length=40)
    swift_bic: str = Field(default="", max_length=16)
    currency: str = Field(..., min_length=3, max_length=8)
    opened_at: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("iban")
    @classmethod
    def _iban_format(cls, v: str) -> str:
        return _validate_iban(v)


class EscrowAccountUpdate(BaseModel):
    """Partial update for an EscrowAccount."""

    model_config = ConfigDict(str_strip_whitespace=True)

    regulator_account_number: str | None = Field(default=None, max_length=120)
    bank_name: str | None = Field(default=None, max_length=255)
    iban: str | None = Field(default=None, max_length=40)
    swift_bic: str | None = Field(default=None, max_length=16)
    closed_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("iban")
    @classmethod
    def _iban_format(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_iban(v)


class EscrowAccountResponse(BaseModel):
    """EscrowAccount as returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    development_id: UUID
    regulator_ref: str = "other"
    regulator_account_number: str = ""
    bank_name: str = ""
    iban: str = ""
    swift_bic: str = ""
    currency: str = ""
    opened_at: str = ""
    closed_at: str | None = None
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class EscrowBalanceResponse(BaseModel):
    """Computed balance for an EscrowAccount as of a given date."""

    escrow_account_id: UUID
    currency: str
    as_of_date: str | None = None
    credit_total: Decimal = Decimal("0")
    debit_total: Decimal = Decimal("0")
    balance: Decimal = Decimal("0")
    transaction_count: int = 0
    unreconciled_count: int = 0

    # R7: money fields as plain-decimal strings.
    @field_serializer(
        "credit_total",
        "debit_total",
        "balance",
        when_used="json",
    )
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


# ── EscrowTransaction ───────────────────────────────────────────────────


class EscrowTransactionCreate(BaseModel):
    """Create an EscrowTransaction.

    ``amount`` is typed ``Decimal`` but we run the gt=0 check inside a
    custom validator so a failing input doesn't end up as a Decimal in
    the 422 response body (FastAPI's default JSON encoder raises
    ``TypeError: Decimal is not JSON serializable`` when the error's
    ``input`` field holds a Decimal). Manual validation keeps the
    rejected value as the original string.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    escrow_account_id: UUID
    direction: str = Field(..., pattern=r"^(debit|credit)$")
    amount: Decimal
    currency: str = Field(..., min_length=3, max_length=8)
    source_type: str = Field(
        ...,
        pattern=r"^(instalment|refund|draw_request|bank_charge|interest|transfer)$",
    )
    source_instalment_id: UUID | None = None
    source_reference: str = Field(default="", max_length=255)
    bank_reference: str | None = Field(default=None, max_length=255)
    transaction_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("amount", mode="before")
    @classmethod
    def _amount_positive(cls, v: Any) -> Any:
        try:
            d = Decimal(str(v))
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise ValueError("amount must be a valid decimal") from exc
        if d <= 0:
            raise ValueError("amount must be greater than 0")
        return d


class EscrowTransactionUpdate(BaseModel):
    """Partial update for an EscrowTransaction."""

    model_config = ConfigDict(str_strip_whitespace=True)

    source_reference: str | None = Field(default=None, max_length=255)
    bank_reference: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] | None = None


class EscrowTransactionResponse(BaseModel):
    """EscrowTransaction as returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    escrow_account_id: UUID
    direction: str = "credit"
    amount: Decimal = Decimal("0")
    currency: str = ""
    source_type: str = "instalment"
    source_instalment_id: UUID | None = None
    source_reference: str = ""
    bank_reference: str | None = None
    transaction_date: str = ""
    reconciliation_state: str = "unreconciled"
    reconciled_at: datetime | None = None
    reconciled_by_user_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # R7: money fields as plain-decimal strings.
    @field_serializer("amount", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class EscrowTransactionReconcileRequest(BaseModel):
    """Payload for /escrow-transactions/{id}/reconcile."""

    model_config = ConfigDict(str_strip_whitespace=True)

    bank_reference: str = Field(..., min_length=1, max_length=255)


# ── PriceMatrix ─────────────────────────────────────────────────────────


_PRICE_MATRIX_FACTOR_TYPES = (
    "floor",
    "view",
    "orientation",
    "corner",
    "launch_discount",
    "phase_escalator",
)


class PriceMatrixRule(BaseModel):
    """One pricing rule inside a :class:`PriceMatrix`."""

    factor_type: str = Field(
        ...,
        pattern=(r"^(floor|view|orientation|corner|launch_discount|phase_escalator)$"),
    )
    condition: dict[str, Any] = Field(default_factory=dict)
    multiplier: Decimal = Field(..., gt=0)


class PriceMatrixCreate(BaseModel):
    """Create a PriceMatrix."""

    model_config = ConfigDict(str_strip_whitespace=True)

    development_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    base_price_per_m2: Decimal = Field(..., ge=0)
    currency: str = Field(..., min_length=3, max_length=8)
    effective_from: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    effective_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    rules: list[PriceMatrixRule] = Field(default_factory=list)
    status: str = Field(default="draft", pattern=r"^(draft|active|expired|archived)$")
    version: int = Field(default=1, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_dates(self) -> PriceMatrixCreate:
        _validate_iso_date_order(self.effective_from, self.effective_to, field_pair="price_matrix")
        return self


class PriceMatrixUpdate(BaseModel):
    """Partial update for a PriceMatrix."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    base_price_per_m2: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    effective_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    effective_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    rules: list[PriceMatrixRule] | None = None
    status: str | None = Field(default=None, pattern=r"^(draft|active|expired|archived)$")
    version: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] | None = None


class PriceMatrixResponse(BaseModel):
    """PriceMatrix as returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    development_id: UUID
    name: str
    base_price_per_m2: Decimal = Decimal("0")
    currency: str = ""
    effective_from: str = ""
    effective_to: str | None = None
    rules: list[Any] = Field(default_factory=list)
    status: str = "draft"
    version: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # R7: money fields as plain-decimal strings.
    @field_serializer("base_price_per_m2", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class PriceMatrixPreviewResponse(BaseModel):
    """Pricing breakdown produced by ``service.compute_plot_price``."""

    plot_id: UUID
    matrix_id: UUID | None = None
    currency: str = ""
    base_price_per_m2: Decimal = Decimal("0")
    area_m2: Decimal = Decimal("0")
    base_price: Decimal = Decimal("0")
    applied_rules: list[dict[str, Any]] = Field(default_factory=list)
    combined_multiplier: Decimal = Decimal("1")
    final_price: Decimal = Decimal("0")

    # R7: money fields as plain-decimal strings.
    @field_serializer(
        "base_price_per_m2",
        "area_m2",
        "base_price",
        "combined_multiplier",
        "final_price",
        when_used="json",
    )
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class PriceMatrixBulkRecomputeResponse(BaseModel):
    """Result of /price-matrices/{id}/bulk-recompute."""

    matrix_id: UUID
    development_id: UUID
    plots_updated: int = 0
    plots_unchanged: int = 0


# ── Regulator report ────────────────────────────────────────────────────


class RegulatorReportResponse(BaseModel):
    """JSON envelope returned alongside the generated PDF."""

    development_id: UUID
    regulator: str
    quarter: str
    generated_at: datetime
    currency: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    pdf_size_bytes: int = 0
    pdf_base64: str = ""


# ── Tax / VAT / Stamp-duty quote ────────────────────────────────────────


class TaxQuotePayload(BaseModel):
    """Request body for ``POST /sales-contracts/{id}/tax-quote``."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    jurisdiction: str | None = Field(default=None, max_length=4)
    region_subcode: str | None = Field(default=None, max_length=8)
    is_first_home: bool = False
    is_additional_property: bool = False
    vat_rate_class: str = Field(default="standard", max_length=40)
    absd_buyer_profile: str | None = Field(default=None, max_length=40)
    emirate: str | None = Field(default=None, max_length=40)
    include_overdue: bool = True


class TaxQuoteLineItem(BaseModel):
    """A single breakdown line in a tax quote."""

    model_config = ConfigDict(str_strip_whitespace=True)

    line: str
    amount: Decimal

    # R8: money fields as plain-decimal strings.
    @field_serializer("amount", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class ContractTaxQuote(BaseModel):
    """Response model for ``POST /sales-contracts/{id}/tax-quote``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    jurisdiction: str
    region_subcode: str | None = None
    currency: str = ""
    net: Decimal = Decimal("0")
    vat: Decimal = Decimal("0")
    stamp_duty: Decimal = Decimal("0")
    transfer_fee: Decimal = Decimal("0")
    registration_fee: Decimal = Decimal("0")
    absd: Decimal = Decimal("0")
    late_interest: Decimal = Decimal("0")
    subtotal_taxes: Decimal = Decimal("0")
    grand_total: Decimal = Decimal("0")
    breakdown: list[TaxQuoteLineItem] = Field(default_factory=list)

    # R8: every money field as a plain-decimal string.
    @field_serializer(
        "net",
        "vat",
        "stamp_duty",
        "transfer_fee",
        "registration_fee",
        "absd",
        "late_interest",
        "subtotal_taxes",
        "grand_total",
        when_used="json",
    )
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


# ── Compliance dashboard (task #139) ────────────────────────────────────


class ComplianceRuleResult(BaseModel):
    """A single :class:`ValidationRule` result in the compliance dashboard."""

    rule_id: str
    rule_name: str
    severity: str
    category: str
    passed: bool
    message: str
    element_ref: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    suggestion: str | None = None


class ComplianceDashboardResponse(BaseModel):
    """Traffic-light + drill-down aggregated for a development.

    ``score`` is the engine-computed severity-weighted ratio (``None`` when
    the report contained no compliance results — i.e. nothing was checked).
    """

    development_id: UUID
    status: str
    score: float | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    rule_sets: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0
    generated_at: str
    results: list[ComplianceRuleResult] = Field(default_factory=list)


class ComplianceRegulatorReportResponse(BaseModel):
    """Full JSON envelope for ``GET /compliance/regulator-reports``.

    Distinct from :class:`RegulatorReportResponse` because the compliance
    endpoint returns both PDF + payload base64'd inline so the client can
    decode without a second request. Named ``Compliance*`` to avoid
    collision with the pre-existing single-file regulator report schema.
    """

    regulator: str
    development_id: UUID
    quarter: str
    generated_at: str
    pdf_base64: str
    payload_format: str
    payload_base64: str
    summary: dict[str, Any] = Field(default_factory=dict)


__all_task_138__ = (
    "BlockCreate",
    "BlockResponse",
    "BlockUpdate",
    "BrokerCreate",
    "BrokerResponse",
    "BrokerUpdate",
    "CommissionAccrualPayRequest",
    "CommissionAccrualResponse",
    "CommissionAgreementCreate",
    "CommissionAgreementResponse",
    "CommissionAgreementUpdate",
    "EscrowAccountCreate",
    "EscrowAccountResponse",
    "EscrowAccountUpdate",
    "EscrowBalanceResponse",
    "EscrowTransactionCreate",
    "EscrowTransactionReconcileRequest",
    "EscrowTransactionResponse",
    "EscrowTransactionUpdate",
    "FlatCommissionStructure",
    "LadderCommissionStructure",
    "LadderTier",
    "PercentCommissionStructure",
    "PhaseCreate",
    "PhaseResponse",
    "PhaseUpdate",
    "PriceMatrixBulkRecomputeResponse",
    "PriceMatrixCreate",
    "PriceMatrixPreviewResponse",
    "PriceMatrixResponse",
    "PriceMatrixRule",
    "PriceMatrixUpdate",
    "RegulatorReportResponse",
    # ── Tax engine (jurisdiction-aware) ─────────────────────────────
    "ContractTaxQuote",
    "TaxQuoteLineItem",
    "TaxQuotePayload",
)


# ════════════════════════════════════════════════════════════════════════
# Task #140 — Dashboards (heatmap / velocity / cashflow / ageing / funnel
# / buyer-journey). All sourced from the full R6 schema (Phase / Block /
# Lead / Reservation / SalesContract / Instalment / Escrow).
# ════════════════════════════════════════════════════════════════════════


class HeatmapUnit(BaseModel):
    """One Plot cell inside a Block of the inventory heatmap."""

    plot_id: str
    plot_number: str
    status: str
    area_m2: Decimal = Decimal("0")
    price_base: Decimal = Decimal("0")
    currency: str = ""
    level_in_block: int | None = None
    position_on_floor: str | None = None
    house_type_id: str | None = None

    # R8: money fields as plain-decimal strings.
    @field_serializer("area_m2", "price_base", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class HeatmapBlock(BaseModel):
    """One Block under a Phase."""

    block_id: str | None = None
    code: str = ""
    name: str = ""
    levels_count: int = 1
    units_per_level: int = 1
    orientation: str | None = None
    units: list[HeatmapUnit] = Field(default_factory=list)


class HeatmapPhase(BaseModel):
    """One Phase containing zero or more Blocks."""

    phase_id: str | None = None
    code: str = ""
    name: str = ""
    sequence: int = 0
    status: str = ""
    blocks: list[HeatmapBlock] = Field(default_factory=list)


class InventoryHeatmapResponse(BaseModel):
    """Heatmap: development -> phases -> blocks -> units."""

    development_id: UUID
    currency: str = ""
    phases: list[HeatmapPhase] = Field(default_factory=list)
    total_units: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)


class CurrencyAmount(BaseModel):
    """One currency / amount pair (multi-currency aware totals)."""

    currency: str = ""
    amount: Decimal = Decimal("0")

    # R8: money fields as plain-decimal strings.
    @field_serializer("amount", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class SalesVelocityBucket(BaseModel):
    """One time-bucket on the velocity chart."""

    period: str
    units: int = 0
    area_m2: Decimal = Decimal("0")
    revenue: list[CurrencyAmount] = Field(default_factory=list)

    # R8: money fields as plain-decimal strings.
    @field_serializer("area_m2", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class SalesVelocityTotals(BaseModel):
    units: int = 0
    area_m2: Decimal = Decimal("0")
    revenue: list[CurrencyAmount] = Field(default_factory=list)

    # R8: money fields as plain-decimal strings.
    @field_serializer("area_m2", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class SalesVelocityResponse(BaseModel):
    """Sales velocity time series."""

    development_id: UUID
    granularity: str = "month"
    series: list[SalesVelocityBucket] = Field(default_factory=list)
    currencies: list[str] = Field(default_factory=list)
    totals: SalesVelocityTotals = Field(default_factory=SalesVelocityTotals)


class CashflowMonthBucket(BaseModel):
    """One month bucket on the cash-flow waterfall."""

    month: str  # YYYY-MM
    scheduled: list[CurrencyAmount] = Field(default_factory=list)
    actual_collected: list[CurrencyAmount] = Field(default_factory=list)
    actual_disbursed: list[CurrencyAmount] = Field(default_factory=list)


class CashflowTotals(BaseModel):
    scheduled: list[CurrencyAmount] = Field(default_factory=list)
    actual_collected: list[CurrencyAmount] = Field(default_factory=list)
    actual_disbursed: list[CurrencyAmount] = Field(default_factory=list)


class CashflowWaterfallResponse(BaseModel):
    """Cash-flow waterfall over the requested month window."""

    development_id: UUID
    start_month: str
    months: int = 12
    currencies: list[str] = Field(default_factory=list)
    series: list[CashflowMonthBucket] = Field(default_factory=list)
    totals: CashflowTotals = Field(default_factory=CashflowTotals)


class InventoryAgeingPlot(BaseModel):
    """One Plot in an ageing bucket."""

    plot_id: str
    plot_number: str
    status: str
    days_on_market: int = 0
    block_id: str | None = None
    house_type_id: str | None = None
    price_base: Decimal = Decimal("0")
    currency: str = ""

    # R8: money fields as plain-decimal strings.
    @field_serializer("price_base", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class InventoryAgeingBucket(BaseModel):
    """One days-on-market bucket."""

    label: str
    count: int = 0
    plots: list[InventoryAgeingPlot] = Field(default_factory=list)


class InventoryAgeingResponse(BaseModel):
    """Ageing histogram for unsold inventory."""

    development_id: UUID
    as_of: str
    buckets: list[InventoryAgeingBucket] = Field(default_factory=list)
    total_unsold: int = 0


class FunnelStage(BaseModel):
    """One funnel stage."""

    code: str
    label: str
    count: int = 0
    drop_pct: Decimal = Decimal("0")

    # R8: percent fields as plain-decimal strings.
    @field_serializer("drop_pct", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class FunnelTotals(BaseModel):
    leads: int = 0
    conversion_pct: Decimal = Decimal("0")

    # R8: percent fields as plain-decimal strings.
    @field_serializer("conversion_pct", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class FunnelConversionResponse(BaseModel):
    """Lead -> Reservation -> SPA draft -> SPA signed -> Handover."""

    development_id: UUID
    period_days: int = 90
    stages: list[FunnelStage] = Field(default_factory=list)
    totals: FunnelTotals = Field(default_factory=FunnelTotals)


class BuyerJourneyEvent(BaseModel):
    """One event in a buyer's cross-entity timeline."""

    code: str
    label: str
    timestamp: str | None = None
    state: str = "completed"  # completed | in_progress | upcoming
    entity: str | None = None
    entity_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class BuyerJourneyResponse(BaseModel):
    """Chronological cross-entity events for one buyer."""

    buyer_id: UUID
    development_id: UUID
    full_name: str = ""
    status: str = ""
    events: list[BuyerJourneyEvent] = Field(default_factory=list)
    event_count: int = 0


# ── Sales-analytics dashboards (v3124) ──────────────────────────────────
#
# Five new dashboards aimed at a real-estate sales director:
#   1. cohort-retention      — bookings grouped by reservation-month
#   2. time-to-close         — days Lead → Reservation → Sale → Handover
#   3. lead-source-attribution — conversion + revenue + CPA per source
#   4. conversion-funnel     — Leads → Qualified → Reservation → Sale → Handover
#   5. broker-performance    — per-broker leaderboard
#
# Every money field is a plain-decimal string (R8 convention). Every
# percent field is a plain-decimal string (consistent with FunnelStage).


class CohortRetentionRow(BaseModel):
    """One cohort row on the retention heatmap.

    ``cohort_month`` is the YYYY-MM the reservation was created in.
    Retention percentages are share of the cohort still in a non-terminal
    state (``active`` or ``converted``) at +30/60/90/180 days from
    creation, expressed as 0.0–100.0.
    """

    cohort_month: str = ""
    total: int = 0
    still_active: int = 0
    retention_pct_d30: Decimal = Decimal("0")
    retention_pct_d60: Decimal = Decimal("0")
    retention_pct_d90: Decimal = Decimal("0")
    retention_pct_d180: Decimal = Decimal("0")

    @field_serializer(
        "retention_pct_d30",
        "retention_pct_d60",
        "retention_pct_d90",
        "retention_pct_d180",
        when_used="json",
    )
    @classmethod
    def _ser_pct(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class CohortRetentionResponse(BaseModel):
    """Retention curves per reservation-month cohort."""

    cohort_period: str = "month"
    since: str | None = None
    until: str | None = None
    cohorts: list[CohortRetentionRow] = Field(default_factory=list)
    total_cohorts: int = 0


class StageHistogramBucket(BaseModel):
    """One bucket on the time-to-close histogram for a given stage."""

    label: str = ""
    lo_days: int = 0
    hi_days: int = 0  # inclusive upper bound; -1 marks the open-ended tail
    count: int = 0


class StageDistribution(BaseModel):
    """Days-in-stage distribution + summary stats for one funnel stage."""

    stage: str = ""
    sample_size: int = 0
    mean_days: Decimal = Decimal("0")
    p50_days: Decimal = Decimal("0")
    p90_days: Decimal = Decimal("0")
    buckets: list[StageHistogramBucket] = Field(default_factory=list)

    @field_serializer(
        "mean_days",
        "p50_days",
        "p90_days",
        when_used="json",
    )
    @classmethod
    def _ser_days(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class TimeToCloseResponse(BaseModel):
    """Lead → Reservation → Sale → Handover stage timings."""

    since: str | None = None
    until: str | None = None
    closed_sales: int = 0
    stages: list[StageDistribution] = Field(default_factory=list)


class LeadSourceRow(BaseModel):
    """One row on the lead-source attribution table."""

    source: str = ""
    leads: int = 0
    reservations: int = 0
    sales: int = 0
    conversion_to_reservation_pct: Decimal = Decimal("0")
    conversion_to_sale_pct: Decimal = Decimal("0")
    revenue: list[CurrencyAmount] = Field(default_factory=list)
    total_source_cost: Decimal = Decimal("0")
    cpa: Decimal | None = None
    cpa_currency: str = ""

    @field_serializer(
        "conversion_to_reservation_pct",
        "conversion_to_sale_pct",
        "total_source_cost",
        when_used="json",
    )
    @classmethod
    def _ser_pct(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"

    @field_serializer("cpa", when_used="json")
    @classmethod
    def _ser_cpa(cls, v: Decimal | None) -> str | None:
        if v is None:
            return None
        return _serialize_money_string(v)


class LeadSourceAttributionResponse(BaseModel):
    """Per-source funnel + revenue + CPA rollup."""

    since: str | None = None
    until: str | None = None
    rows: list[LeadSourceRow] = Field(default_factory=list)
    total_leads: int = 0


class ConversionFunnelStep(BaseModel):
    """One step on the sales-director conversion funnel.

    Stages: ``leads`` → ``qualified`` → ``reservation`` → ``sale`` →
    ``handover``. ``drop_pct`` is share of the previous step that did
    NOT proceed (0.0–100.0). The first step's drop_pct is always 0.
    """

    code: str = ""
    label: str = ""
    count: int = 0
    drop_pct: Decimal = Decimal("0")
    conversion_from_top_pct: Decimal = Decimal("0")

    @field_serializer(
        "drop_pct",
        "conversion_from_top_pct",
        when_used="json",
    )
    @classmethod
    def _ser_pct(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class ConversionFunnelResponse(BaseModel):
    """5-step funnel scoped by date window and (optionally) development."""

    since: str | None = None
    until: str | None = None
    dev_id: UUID | None = None
    plot_type: str | None = None
    steps: list[ConversionFunnelStep] = Field(default_factory=list)
    overall_conversion_pct: Decimal = Decimal("0")

    @field_serializer("overall_conversion_pct", when_used="json")
    @classmethod
    def _ser_pct(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class BrokerLeaderboardRow(BaseModel):
    """One broker on the performance leaderboard."""

    broker_id: UUID
    broker_name: str = ""
    leads_assigned: int = 0
    reservations_closed: int = 0
    sales_closed: int = 0
    conversion_rate_pct: Decimal = Decimal("0")
    gmv: list[CurrencyAmount] = Field(default_factory=list)
    commission_earned: list[CurrencyAmount] = Field(default_factory=list)

    @field_serializer("conversion_rate_pct", when_used="json")
    @classmethod
    def _ser_pct(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class BrokerPerformanceResponse(BaseModel):
    """Per-broker leaderboard for the requested window."""

    since: str | None = None
    until: str | None = None
    rows: list[BrokerLeaderboardRow] = Field(default_factory=list)
    total_brokers: int = 0


__all_task_140__ = (
    "BrokerLeaderboardRow",
    "BrokerPerformanceResponse",
    "BuyerJourneyEvent",
    "BuyerJourneyResponse",
    "CashflowMonthBucket",
    "CashflowTotals",
    "CashflowWaterfallResponse",
    "CohortRetentionResponse",
    "CohortRetentionRow",
    "ConversionFunnelResponse",
    "ConversionFunnelStep",
    "CurrencyAmount",
    "FunnelConversionResponse",
    "FunnelStage",
    "FunnelTotals",
    "HeatmapBlock",
    "HeatmapPhase",
    "HeatmapUnit",
    "InventoryAgeingBucket",
    "InventoryAgeingPlot",
    "InventoryAgeingResponse",
    "InventoryHeatmapResponse",
    "LeadSourceAttributionResponse",
    "LeadSourceRow",
    "PropertyDevHouseTypeCreate",
    "PropertyDevHouseTypeResponse",
    "PropertyDevHouseTypeUpdate",
    "SalesVelocityBucket",
    "SalesVelocityResponse",
    "SalesVelocityTotals",
    "StageDistribution",
    "StageHistogramBucket",
    "TimeToCloseResponse",
)


# ── House Type Catalogue (preset + user-created) ────────────────────────


_CONSTRUCTION_TYPES = (
    "brick",
    "timber_frame",
    "concrete",
    "steel",
    "mixed",
    "other",
)
_ENERGY_CLASSES = (
    "A+",
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "not_applicable",
)
_SALES_CHANNELS = ("off_plan", "new_build", "resale")


class PropertyDevHouseTypeCreate(BaseModel):
    """Create a custom house-type catalogue entry.

    ``project_id`` is required for user-created entries — global presets
    are only inserted via the migration seed, never through the API.

    ``country_code`` may be NULL when the operator picks the "Other /
    Custom region" option; in that case ``region_label`` should hold the
    free-text tag (e.g. "EU-wide", "DACH", "Middle East").
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    country_code: str | None = Field(
        default=None,
        min_length=2,
        max_length=2,
        pattern=r"^[A-Z]{2}$",
    )
    region_label: str | None = Field(default=None, max_length=80)
    code: str = Field(..., min_length=1, max_length=40, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    area_typical_m2: Decimal | None = Field(default=None, ge=0)
    floors_typical: int | None = Field(default=None, ge=0, le=200)
    typical_bedrooms: int | None = Field(default=None, ge=0, le=50)
    typical_bathrooms: int | None = Field(default=None, ge=0, le=50)
    parking_spots: int | None = Field(default=None, ge=0, le=10)
    typical_price_min: Decimal | None = Field(default=None, ge=0)
    typical_price_max: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    construction_type: str | None = Field(default=None, max_length=20)
    energy_class: str | None = Field(default=None, max_length=10)
    sales_channel: str | None = Field(default=None, max_length=20)
    image_url: str | None = Field(default=None, max_length=512)
    tags: list[str] = Field(default_factory=list, max_length=40)


class PropertyDevHouseTypeUpdate(BaseModel):
    """Partial update for a user-created house-type catalogue entry.

    The service layer rejects updates on preset rows (``is_preset=True``)
    so this never has to be a no-op on the model side.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    area_typical_m2: Decimal | None = Field(default=None, ge=0)
    floors_typical: int | None = Field(default=None, ge=0, le=200)
    country_code: str | None = Field(
        default=None,
        min_length=2,
        max_length=2,
        pattern=r"^[A-Z]{2}$",
    )
    region_label: str | None = Field(default=None, max_length=80)
    typical_bedrooms: int | None = Field(default=None, ge=0, le=50)
    typical_bathrooms: int | None = Field(default=None, ge=0, le=50)
    parking_spots: int | None = Field(default=None, ge=0, le=10)
    typical_price_min: Decimal | None = Field(default=None, ge=0)
    typical_price_max: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    construction_type: str | None = Field(default=None, max_length=20)
    energy_class: str | None = Field(default=None, max_length=10)
    sales_channel: str | None = Field(default=None, max_length=20)
    image_url: str | None = Field(default=None, max_length=512)
    tags: list[str] | None = Field(default=None, max_length=40)


class PropertyDevHouseTypeResponse(BaseModel):
    """Catalogue entry as returned to the UI."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None = None
    country_code: str | None = None
    region_label: str | None = None
    code: str
    name: str
    description: str | None = None
    area_typical_m2: Decimal | None = None
    floors_typical: int | None = None
    typical_bedrooms: int | None = None
    typical_bathrooms: int | None = None
    parking_spots: int | None = None
    typical_price_min: Decimal | None = None
    typical_price_max: Decimal | None = None
    currency: str | None = None
    construction_type: str | None = None
    energy_class: str | None = None
    sales_channel: str | None = None
    image_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    is_preset: bool = False
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


# ── Pricing engine — PriceList / PriceListEntry / PricingRule ───────────


_PRICE_LIST_STATUS_PATTERN = r"^(draft|active|superseded)$"
_RULE_TYPE_PATTERN = (
    r"^(early_bird|view_premium|floor_premium|corner_premium|"
    r"size_premium|promo_code|friends_family|loyalty|bulk_buy)$"
)


def _validate_condition_for_rule_type(rule_type: str, cond: dict[str, Any]) -> None:
    """Lightweight discriminated-union check for ``condition_json``.

    Pydantic v2's true discriminated unions are awkward when the
    discriminator lives on the parent model; we keep ``condition_json``
    as a free dict at the DB layer and validate the per-type required
    keys here. Each branch enforces the keys documented in
    :mod:`app.modules.property_dev.pricing_engine`.
    """
    if not isinstance(cond, dict):
        raise ValueError("condition_json must be an object")

    if rule_type == "early_bird":
        if not isinstance(cond.get("before"), str):
            raise ValueError("early_bird requires 'before' (ISO date string)")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", cond["before"]):
            raise ValueError("'before' must be YYYY-MM-DD")
        return

    if rule_type == "view_premium":
        attr = cond.get("plot_attribute", "view")
        vals = cond.get("values")
        if not isinstance(attr, str) or not attr:
            raise ValueError("view_premium requires 'plot_attribute'")
        if not isinstance(vals, list) or not vals:
            raise ValueError("view_premium requires a non-empty 'values' list")
        return

    if rule_type == "floor_premium":
        if "min_floor" not in cond and "floor" not in cond:
            raise ValueError("floor_premium requires 'min_floor' or 'floor'")
        for key in ("min_floor", "floor"):
            if key in cond and not isinstance(cond[key], int):
                raise ValueError(f"'{key}' must be an integer")
        return

    if rule_type == "corner_premium":
        # plot_attribute + value both optional (default 'is_corner' / True).
        return

    if rule_type == "size_premium":
        if "min_area_m2" not in cond and "max_area_m2" not in cond:
            raise ValueError("size_premium requires 'min_area_m2' or 'max_area_m2'")
        return

    if rule_type == "promo_code":
        code = cond.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("promo_code requires a non-empty 'code'")
        return

    if rule_type == "friends_family":
        # Optional 'buyer_tag' (defaults to 'ff') — anything goes.
        return

    if rule_type == "loyalty":
        threshold = cond.get("prior_purchases_min", 1)
        if not isinstance(threshold, int) or threshold < 1:
            raise ValueError("loyalty requires 'prior_purchases_min' >= 1")
        return

    if rule_type == "bulk_buy":
        threshold = cond.get("min_plots", 2)
        if not isinstance(threshold, int) or threshold < 2:
            raise ValueError("bulk_buy requires 'min_plots' >= 2")
        return

    raise ValueError(f"unknown rule_type: {rule_type}")


class PricingRuleCreate(BaseModel):
    """Create a PricingRule under a PriceList."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    rule_type: str = Field(..., pattern=_RULE_TYPE_PATTERN)
    condition_json: dict[str, Any] = Field(default_factory=dict)
    adjustment_pct: Decimal = Field(default=Decimal("0"))
    adjustment_fixed: Decimal | None = None
    priority: int = Field(default=100, ge=0, le=10000)
    active: bool = True
    effective_from: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    effective_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    max_uses: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _check_condition(self) -> PricingRuleCreate:
        _validate_condition_for_rule_type(self.rule_type, self.condition_json)
        return self


class PricingRuleUpdate(BaseModel):
    """Partial update for a PricingRule."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    rule_type: str | None = Field(default=None, pattern=_RULE_TYPE_PATTERN)
    condition_json: dict[str, Any] | None = None
    adjustment_pct: Decimal | None = None
    adjustment_fixed: Decimal | None = None
    priority: int | None = Field(default=None, ge=0, le=10000)
    active: bool | None = None
    effective_from: str | None = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    effective_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    max_uses: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _check_condition(self) -> PricingRuleUpdate:
        if self.rule_type is not None and self.condition_json is not None:
            _validate_condition_for_rule_type(self.rule_type, self.condition_json)
        return self


# ════════════════════════════════════════════════════════════════════════
# Inventory Map — sales-floor block / floor / unit grid.
# ════════════════════════════════════════════════════════════════════════
#
# Differs from the analytics ``InventoryHeatmapResponse`` (task #140) on
# three axes: (a) flat blocks[] (skips the Phase grouping for sales-desk
# clarity), (b) explicit floor grouping inside each block (the analytics
# heatmap is one flat strip per block), (c) tighter shape with a
# top-level ``summary`` counter ribbon. Used by
# /developments/{dev_id}/inventory-map/ and the React InventoryMapPage.


class InventoryMapPlot(BaseModel):
    """One Plot cell inside a floor strip of the inventory map."""

    id: UUID
    unit_code: str
    status: str
    plot_type: str | None = None
    block_code: str | None = None
    floor: int | None = None
    base_price: Decimal = Decimal("0")
    area_m2: Decimal = Decimal("0")
    currency: str = ""
    bedrooms: int = 0
    bathrooms: int = 0

    # R7 money-as-string convention (BUG-B-011).
    @field_serializer("base_price", "area_m2", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class InventoryMapFloor(BaseModel):
    """One floor row within a Block (descending floor numbers in UI)."""

    floor: int
    plots: list[InventoryMapPlot] = Field(default_factory=list)


class InventoryMapBlock(BaseModel):
    """One Block card on the map (collapsible in UI)."""

    block_code: str
    block_id: UUID | None = None
    name: str = ""
    floors: list[InventoryMapFloor] = Field(default_factory=list)


class InventoryMapSummary(BaseModel):
    """KPI ribbon counters — one entry per Plot.status (incl. ``total``)."""

    total: int = 0
    available: int = 0
    reserved: int = 0
    sold: int = 0
    handed_over: int = 0
    held: int = 0
    blocked: int = 0
    under_construction: int = 0
    ready: int = 0


class InventoryMapResponse(BaseModel):
    """``GET /developments/{dev_id}/inventory-map/`` envelope."""

    development_id: UUID
    currency: str = ""
    blocks: list[InventoryMapBlock] = Field(default_factory=list)
    summary: InventoryMapSummary = Field(default_factory=InventoryMapSummary)


class InventoryMapBulkHoldRequest(BaseModel):
    """``POST /inventory-map/bulk-hold/`` payload.

    ``plot_ids`` is non-empty (server rejects empty list with 422 so the
    caller doesn't accidentally fire a no-op + audit-log noise).
    ``hold_reason`` is free-text but capped at 500 chars (audit-row column
    width); ``hold_until`` is an optional ISO-8601 date (YYYY-MM-DD).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    plot_ids: list[UUID] = Field(..., min_length=1, max_length=500)
    hold_reason: str = Field(default="", max_length=500)
    hold_until: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class InventoryMapBulkReleaseRequest(BaseModel):
    """``POST /inventory-map/bulk-release/`` payload."""

    model_config = ConfigDict(str_strip_whitespace=True)

    plot_ids: list[UUID] = Field(..., min_length=1, max_length=500)


class InventoryMapBulkResult(BaseModel):
    """Outcome of a bulk hold / release call."""

    updated_count: int = 0
    skipped_count: int = 0
    updated_plot_ids: list[UUID] = Field(default_factory=list)
    skipped: list[dict[str, str]] = Field(default_factory=list)


# ════════════════════════════════════════════════════════════════════════
# Bulk-operations admin console (sales-ops batch endpoints)
# ════════════════════════════════════════════════════════════════════════
#
# Distinct from ``InventoryMapBulkResult`` above (which scopes hold /
# release on the inventory map) — this envelope is shared by the five
# sales-ops bulk endpoints under /bulk/*:
#   * plot status flips OTHER than hold/release
#   * reservation expiry extensions
#   * document regenerations
#   * lead-from-CSV imports
#   * buyer merges
#
# A single ``BulkResult`` keeps the frontend renderer trivial. ``skipped``
# captures soft no-ops (IDOR collapses to silent skip, terminal-state
# reservations); ``failed`` captures per-item errors that didn't poison
# the rest of the batch (illegal FSM transitions, render failures).

BULK_MAX_ITEMS: int = 500


class BulkSkipped(BaseModel):
    """A single skip entry inside a bulk-result envelope."""

    model_config = ConfigDict(str_strip_whitespace=True)

    entity_id: str = Field(..., description="Stringified UUID or other identifier.")
    reason: str = Field(..., max_length=500)
    code: str = Field(..., max_length=80)


class BulkFailed(BaseModel):
    """A single failure entry inside a bulk-result envelope."""

    model_config = ConfigDict(str_strip_whitespace=True)

    entity_id: str = Field(..., description="Stringified UUID or other identifier.")
    error_message: str = Field(..., max_length=1000)
    error_code: str = Field(..., max_length=80)


class BulkResult(BaseModel):
    """Envelope returned by every bulk-operation endpoint."""

    model_config = ConfigDict(from_attributes=True)

    requested: int = Field(..., ge=0)
    succeeded: int = Field(..., ge=0)
    skipped: list[BulkSkipped] = Field(default_factory=list)
    failed: list[BulkFailed] = Field(default_factory=list)
    dry_run: bool = False


# ── Plot bulk status change ─────────────────────────────────────────────

_PLOT_STATUS_PATTERN = r"^(planned|reserved|under_construction|ready|sold|handed_over)$"


class PlotBulkStatusChange(BaseModel):
    """Bulk-flip a set of plots to a target status.

    NOTE: this endpoint is for transitions OTHER than hold / release —
    those live on the inventory-map module (``bulk-hold`` / ``bulk-release``).
    Use this for milestone-driven flips (reserved → sold after deposit
    cleared) or remediation (sold → ready when an SPA fell through).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    plot_ids: list[UUID] = Field(..., min_length=1, max_length=BULK_MAX_ITEMS)
    target_status: str = Field(..., pattern=_PLOT_STATUS_PATTERN)
    reason: str = Field(default="", max_length=500)


# ── Reservation bulk-extend-expiry ──────────────────────────────────────


class ReservationBulkExtendExpiry(BaseModel):
    """Bulk-extend the ``expires_at`` of a set of active reservations."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reservation_ids: list[UUID] = Field(..., min_length=1, max_length=BULK_MAX_ITEMS)
    new_expiry: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str = Field(default="", max_length=500)


# ── Documents bulk-regenerate ───────────────────────────────────────────
#
# Subset of _VALID_DOC_TYPES (see service.py). Payment receipts are
# per-instalment and don't belong in the sales-ops bulk console.

_BULK_DOC_TYPE_PATTERN = (
    r"^(reservation_receipt|sales_contract|handover_certificate|"
    r"warranty_certificate|noc)$"
)


class DocumentsBulkRegenerate(BaseModel):
    """Re-render PDFs for a set of reservations OR sales contracts.

    Exactly one of ``reservation_ids`` / ``sales_contract_ids`` is required
    depending on ``document_type``: reservation_receipt accepts
    reservation_ids; sales_contract / noc / handover_certificate /
    warranty_certificate accept sales_contract_ids.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    document_type: str = Field(..., pattern=_BULK_DOC_TYPE_PATTERN)
    reservation_ids: list[UUID] | None = Field(default=None, max_length=BULK_MAX_ITEMS)
    sales_contract_ids: list[UUID] | None = Field(default=None, max_length=BULK_MAX_ITEMS)
    locale: str = Field(default="en", max_length=10)

    @model_validator(mode="after")
    def _check_payload_target(self) -> DocumentsBulkRegenerate:
        if not self.reservation_ids and not self.sales_contract_ids:
            raise ValueError("Provide at least one of reservation_ids or sales_contract_ids.")
        if self.reservation_ids and self.sales_contract_ids:
            raise ValueError("Provide only ONE of reservation_ids / sales_contract_ids per request.")
        if self.document_type == "reservation_receipt" and not self.reservation_ids:
            raise ValueError("reservation_receipt requires reservation_ids.")
        if self.document_type != "reservation_receipt" and not self.sales_contract_ids:
            raise ValueError(f"{self.document_type} requires sales_contract_ids.")
        return self


class PricingRuleResponse(BaseModel):
    """PricingRule returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    price_list_id: UUID
    name: str
    rule_type: str
    condition_json: dict[str, Any] = Field(default_factory=dict)
    adjustment_pct: Decimal = Decimal("0")
    adjustment_fixed: Decimal | None = None
    priority: int = 100
    active: bool = True
    effective_from: str = ""
    effective_to: str | None = None
    max_uses: int | None = None
    times_used: int = 0
    created_at: datetime
    updated_at: datetime

    @field_serializer("adjustment_pct", "adjustment_fixed", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal | None) -> str | None:
        return _serialize_money_string(v)


class PriceListEntryInput(BaseModel):
    """Per-plot base price input on PriceListCreate."""

    model_config = ConfigDict(str_strip_whitespace=True)

    plot_id: UUID
    base_price: Decimal = Field(..., ge=0)


class PriceListEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    price_list_id: UUID
    plot_id: UUID
    base_price: Decimal = Decimal("0")

    @field_serializer("base_price", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class PriceListCreate(BaseModel):
    """Create a new PriceList (status starts as 'draft')."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    effective_from: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    effective_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    currency: str = Field(..., min_length=3, max_length=3)
    notes: str | None = None
    entries: list[PriceListEntryInput] = Field(default_factory=list)
    rules: list[PricingRuleCreate] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def _v_currency(cls, v: str) -> str:
        return _strict_currency_validator(v) or ""


class PriceListUpdate(BaseModel):
    """Partial update for a PriceList (status changes go via /activate)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    effective_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    effective_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    notes: str | None = None

    @field_validator("currency")
    @classmethod
    def _v_currency(cls, v: str | None) -> str | None:
        return _strict_currency_validator(v)


class PriceListResponse(BaseModel):
    """A PriceList row as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    development_id: UUID
    name: str
    effective_from: str = ""
    effective_to: str | None = None
    currency: str = ""
    status: str = "draft"
    created_by: UUID | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class PriceQuoteLineResponse(BaseModel):
    """A single line in a price quote (used inside :class:`PriceQuoteResponse`)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    rule_id: UUID | None = None
    rule_name: str = ""
    rule_type: str = "base"
    pct: Decimal | None = None
    fixed: Decimal | None = None
    amount: Decimal = Decimal("0")

    @field_serializer("amount", "pct", "fixed", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal | None) -> str | None:
        return _serialize_money_string(v)


class PriceQuoteResponse(BaseModel):
    """A computed price quote for a plot."""

    model_config = ConfigDict(str_strip_whitespace=True)

    plot_id: UUID
    base_price: Decimal = Decimal("0")
    lines: list[PriceQuoteLineResponse] = Field(default_factory=list)
    total: Decimal = Decimal("0")
    currency: str = ""
    computed_at: datetime
    price_list_id: UUID | None = None

    @field_serializer("base_price", "total", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class PriceQuoteBasketRequest(BaseModel):
    """Request body for ``POST /price-lists/{id}/quote-basket/``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    plot_ids: list[UUID] = Field(..., min_length=1)
    promo_code: str | None = None
    buyer_id: UUID | None = None
    quote_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class PriceQuoteBasketResponse(BaseModel):
    """Response for ``POST /price-lists/{id}/quote-basket/``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    quotes: list[PriceQuoteResponse] = Field(default_factory=list)
    total: Decimal = Decimal("0")
    currency: str = ""

    @field_serializer("total", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class EffectiveRulesResponse(BaseModel):
    """``GET /price-lists/{id}/rules/effective/?date=`` response."""

    model_config = ConfigDict(str_strip_whitespace=True)

    price_list_id: UUID
    on_date: str
    rules: list[PricingRuleResponse] = Field(default_factory=list)


# ── Buyer bulk-merge ────────────────────────────────────────────────────


class BuyerBulkMerge(BaseModel):
    """Merge a set of duplicate buyers into a single primary buyer.

    Re-points all FK references (reservations, sales_contracts, contract
    parties, warranty claims, buyer selections) from duplicates → primary,
    then soft-deletes the duplicate rows. Atomic — all reps roll back if
    any single repoint fails.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    primary_buyer_id: UUID
    duplicate_buyer_ids: list[UUID] = Field(..., min_length=1, max_length=BULK_MAX_ITEMS)
    reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _check_distinct(self) -> BuyerBulkMerge:
        if self.primary_buyer_id in self.duplicate_buyer_ids:
            raise ValueError("primary_buyer_id must not appear in duplicate_buyer_ids.")
        if len(set(self.duplicate_buyer_ids)) != len(self.duplicate_buyer_ids):
            raise ValueError("duplicate_buyer_ids must not contain duplicates.")
        return self
