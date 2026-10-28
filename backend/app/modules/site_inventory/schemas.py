# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Site-inventory Pydantic v2 schemas (request / response models).

Money and quantities cross the wire as canonical Decimal STRINGS, never floats:
create schemas accept a string and validate it parses to a non-negative
``Decimal``; response schemas coerce the ``Decimal`` handed back by the ORM to a
string in a ``mode="before"`` validator.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MovementTypeLiteral = Literal["INBOUND", "CONSUMPTION", "WASTE", "TRANSFER"]


def _parse_decimal(value: str) -> Decimal:
    """Parse a string into a ``Decimal`` or raise a clear ``ValueError``."""
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def _validate_non_negative(value: str) -> str:
    """Validate that a string is a non-negative decimal, returning it unchanged."""
    if _parse_decimal(value) < 0:
        raise ValueError(f"Value must be non-negative, got {value!r}")
    return value


def _validate_positive(value: str) -> str:
    """Validate that a string is a strictly positive decimal."""
    if _parse_decimal(value) <= 0:
        raise ValueError(f"Value must be greater than zero, got {value!r}")
    return value


def _coerce_optional_str(value: Any) -> str | None:
    """Render an ORM ``Decimal`` (or anything) as a string, keeping ``None``."""
    if value is None:
        return None
    return str(value)


def _coerce_str(value: Any) -> str:
    """Render an ORM ``Decimal`` (or anything) as a string, ``None`` -> ``'0'``."""
    if value is None:
        return "0"
    return str(value)


# -- Storage location --------------------------------------------------------


class LocationCreate(BaseModel):
    """Create a geo-tagged storage location."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=64)
    latitude: str | None = Field(default=None, max_length=32)
    longitude: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=500)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("latitude", "longitude")
    @classmethod
    def _check_coord(cls, v: str | None) -> str | None:
        if v is None:
            return None
        _parse_decimal(v)  # must parse; range is not enforced here
        return v


class LocationResponse(BaseModel):
    """A storage location returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    code: str | None = None
    latitude: str | None = None
    longitude: str | None = None
    address: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def _coord_to_str(cls, v: Any) -> str | None:
        return _coerce_optional_str(v)


# -- Stock item --------------------------------------------------------------


class StockItemCreate(BaseModel):
    """Create a stock item / material record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    sku: str | None = Field(default=None, max_length=64)
    unit: str = Field(default="", max_length=20)
    boq_position_id: UUID | None = None
    procurement_req_item_id: UUID | None = None
    default_location_id: UUID | None = None
    standard_unit_cost: str | None = Field(default=None, max_length=50)
    currency: str = Field(default="", max_length=10)
    reorder_point: str | None = Field(default=None, max_length=50)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("standard_unit_cost", "reorder_point")
    @classmethod
    def _check_non_negative_optional(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_non_negative(v)


class StockItemUpdate(BaseModel):
    """Patch a stock item: only the fields sent are written.

    Every field is optional and ``exclude_unset`` is what the service reads, so
    an omitted link is left alone while an explicit ``null`` clears it. That
    distinction is the whole point of the schema: linking an item to the BoQ
    position that priced it must not blank the rest of the record, and a wrong
    link must still be correctable.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    sku: str | None = Field(default=None, max_length=64)
    unit: str | None = Field(default=None, max_length=20)
    boq_position_id: UUID | None = None
    procurement_req_item_id: UUID | None = None
    default_location_id: UUID | None = None
    standard_unit_cost: str | None = Field(default=None, max_length=50)
    currency: str | None = Field(default=None, max_length=10)
    reorder_point: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None

    @field_validator("standard_unit_cost", "reorder_point")
    @classmethod
    def _check_non_negative_optional(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_non_negative(v)


class StockItemResponse(BaseModel):
    """A stock item returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    sku: str | None = None
    unit: str
    boq_position_id: UUID | None = None
    procurement_req_item_id: UUID | None = None
    default_location_id: UUID | None = None
    standard_unit_cost: str | None = None
    currency: str
    reorder_point: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("standard_unit_cost", "reorder_point", mode="before")
    @classmethod
    def _money_to_str(cls, v: Any) -> str | None:
        return _coerce_optional_str(v)


# -- Stock movement ----------------------------------------------------------


class MovementCreate(BaseModel):
    """Record a stock movement.

    ``quantity`` is a positive magnitude; the direction is derived from
    ``movement_type`` by the ledger. A ``TRANSFER`` must carry both a source
    ``location_id`` and a distinct destination ``to_location_id``.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    item_id: UUID
    movement_type: MovementTypeLiteral
    quantity: str = Field(..., max_length=50)
    unit_cost: str = Field(default="0", max_length=50)
    currency: str = Field(default="", max_length=10)
    location_id: UUID | None = None
    to_location_id: UUID | None = None
    boq_position_id: UUID | None = None
    goods_receipt_id: UUID | None = None
    occurred_at: datetime | None = None
    note: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("quantity")
    @classmethod
    def _check_quantity(cls, v: str) -> str:
        return _validate_positive(v)

    @field_validator("unit_cost")
    @classmethod
    def _check_unit_cost(cls, v: str) -> str:
        return _validate_non_negative(v)

    @model_validator(mode="after")
    def _check_transfer_locations(self) -> MovementCreate:
        if self.movement_type == "TRANSFER":
            if self.location_id is None or self.to_location_id is None:
                raise ValueError("A TRANSFER requires both location_id and to_location_id")
            if self.location_id == self.to_location_id:
                raise ValueError("A TRANSFER source and destination must differ")
        return self


class MovementResponse(BaseModel):
    """A stock movement returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    item_id: UUID
    movement_type: str
    quantity: str
    unit_cost: str
    currency: str
    location_id: UUID | None = None
    to_location_id: UUID | None = None
    boq_position_id: UUID | None = None
    goods_receipt_id: UUID | None = None
    occurred_at: datetime
    actor_id: str | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("quantity", "unit_cost", mode="before")
    @classmethod
    def _num_to_str(cls, v: Any) -> str:
        return _coerce_str(v)


# -- Derived views (returned as plain dicts by the router, typed here for docs) -


class StockOnHandRow(BaseModel):
    """Stock on hand for a single item."""

    item_id: UUID
    name: str
    unit: str
    on_hand: str


class StockOnHandResponse(BaseModel):
    """Per-item stock on hand for a project (optionally within one location)."""

    project_id: UUID
    location_id: UUID | None = None
    item_count: int
    rows: list[StockOnHandRow] = Field(default_factory=list)
