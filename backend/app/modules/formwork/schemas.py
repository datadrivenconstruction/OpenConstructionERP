"""Formwork Pydantic schemas - request / response models.

Money fields use ``Decimal`` on input and ``str`` on output to match the
project's v3 §10 "Decimal as string" contract. Returning a float would
let JavaScript clients lose precision on large unit rates.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

# ── enum-like patterns ───────────────────────────────────────────────────

SYSTEM_TYPES = "wall|slab|column|beam|foundation|climbing|custom"
MATERIALS = "plywood|steel|aluminium|composite|timber|other"

# Annotated Decimal that serialises to a JSON string (preserves precision).
MoneyStr = Annotated[Decimal, Field(default=Decimal("0"))]


def _money_to_str(v: Decimal | None) -> str | None:
    """Serialise a Decimal to a fixed 2-dp string (None → None)."""
    if v is None:
        return None
    # ``Decimal.quantize`` would round; we keep ``str()`` to preserve any
    # extra precision the DB rounded into the column itself.
    return format(Decimal(v), "f")


# ── FormworkSystem ───────────────────────────────────────────────────────


class FormworkSystemCreate(BaseModel):
    """Create a new formwork system catalogue row."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    system_type: str = Field(default="wall", pattern=rf"^({SYSTEM_TYPES})$")
    supplier: str | None = Field(default=None, max_length=255)
    material: str = Field(default="plywood", pattern=rf"^({MATERIALS})$")
    reuses_max: int = Field(default=30, ge=1, le=10_000)
    unit_rate: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=3)
    notes: str | None = None
    tenant_id: UUID | None = None


class FormworkSystemUpdate(BaseModel):
    """Partial update for a formwork system."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    system_type: str | None = Field(default=None, pattern=rf"^({SYSTEM_TYPES})$")
    supplier: str | None = Field(default=None, max_length=255)
    material: str | None = Field(default=None, pattern=rf"^({MATERIALS})$")
    reuses_max: int | None = Field(default=None, ge=1, le=10_000)
    unit_rate: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    notes: str | None = None


class FormworkSystemResponse(BaseModel):
    """A formwork catalogue row as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    system_type: str
    supplier: str | None = None
    material: str
    reuses_max: int
    unit_rate: Decimal
    currency: str
    notes: str | None = None
    tenant_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("unit_rate")
    def _ser_unit_rate(self, v: Decimal) -> str:
        return _money_to_str(v)  # type: ignore[return-value]


class FormworkSystemSeedResult(BaseModel):
    """Response payload for ``POST /systems/seed-defaults``."""

    inserted: int
    skipped: int
    total_after: int


# ── FormworkAssignment ───────────────────────────────────────────────────


class FormworkAssignmentCreate(BaseModel):
    """Create a new formwork assignment.

    ``computed_unit_cost`` and ``computed_total`` are derived server-side
    from ``unit_rate`` × waste × reuse_count - they are NOT accepted in
    the request body even if the client sends them (they would be a lie
    until they go through the service-layer recomputation).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    boq_position_id: UUID | None = None
    formwork_system_id: UUID
    area_m2: Decimal = Field(default=Decimal("0"), ge=0)
    reuse_count: int = Field(default=1, ge=1, le=10_000)
    waste_pct: Decimal = Field(default=Decimal("5.00"), ge=0, le=100)
    notes: str | None = None
    tenant_id: UUID | None = None


class FormworkAssignmentUpdate(BaseModel):
    """Partial update for a formwork assignment."""

    model_config = ConfigDict(str_strip_whitespace=True)

    boq_position_id: UUID | None = None
    formwork_system_id: UUID | None = None
    area_m2: Decimal | None = Field(default=None, ge=0)
    reuse_count: int | None = Field(default=None, ge=1, le=10_000)
    waste_pct: Decimal | None = Field(default=None, ge=0, le=100)
    notes: str | None = None


class FormworkAssignmentResponse(BaseModel):
    """A formwork assignment row as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    boq_position_id: UUID | None = None
    formwork_system_id: UUID
    area_m2: Decimal
    reuse_count: int
    waste_pct: Decimal
    computed_unit_cost: Decimal
    computed_total: Decimal
    notes: str | None = None
    tenant_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("area_m2", "waste_pct", "computed_unit_cost", "computed_total")
    def _ser_money(self, v: Decimal) -> str:
        return _money_to_str(v)  # type: ignore[return-value]


# ── FormworkScheduleLine ─────────────────────────────────────────────────


class FormworkScheduleLineCreate(BaseModel):
    """Append one pour-cycle line under a FormworkAssignment.

    ``project_id`` is derived from the parent assignment server-side, so
    callers do not need to (and should not) pass it.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    pour_no: int = Field(default=1, ge=1, le=10_000)
    pour_date: date | None = None
    level_label: str = Field(default="", max_length=120)
    area_m2: Decimal = Field(default=Decimal("0"), ge=0)
    notes: str | None = None


class FormworkScheduleLineUpdate(BaseModel):
    """Partial update for a pour-cycle schedule line.

    ``project_id`` and ``assignment_id`` are immutable (a line cannot be
    moved to a different parent), so they are deliberately absent here.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    pour_no: int | None = Field(default=None, ge=1, le=10_000)
    pour_date: date | None = None
    level_label: str | None = Field(default=None, max_length=120)
    area_m2: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None


class FormworkScheduleLineResponse(BaseModel):
    """A pour-cycle schedule line as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    assignment_id: UUID
    pour_no: int
    pour_date: date | None = None
    level_label: str
    area_m2: Decimal
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("area_m2")
    def _ser_area(self, v: Decimal) -> str:
        return _money_to_str(v)  # type: ignore[return-value]


# ── helpers ──────────────────────────────────────────────────────────────


def default_seed_systems() -> list[dict[str, Any]]:
    """Return the catalogue of starter formwork systems.

    Idempotent insert (``/systems/seed-defaults``) walks this list and
    skips any name that already exists for the calling tenant. Currency
    deliberately left blank so each tenant can localise on first use.
    """
    return [
        {
            "name": "Doka Framax Xlife",
            "system_type": "wall",
            "supplier": "Doka",
            "material": "steel",
            "reuses_max": 100,
            "unit_rate": Decimal("65.00"),
        },
        {
            "name": "Doka Dokadek 30",
            "system_type": "slab",
            "supplier": "Doka",
            "material": "aluminium",
            "reuses_max": 80,
            "unit_rate": Decimal("48.00"),
        },
        {
            "name": "PERI MAXIMO",
            "system_type": "wall",
            "supplier": "PERI",
            "material": "steel",
            "reuses_max": 100,
            "unit_rate": Decimal("70.00"),
        },
        {
            "name": "PERI SKYDECK",
            "system_type": "slab",
            "supplier": "PERI",
            "material": "aluminium",
            "reuses_max": 80,
            "unit_rate": Decimal("52.00"),
        },
        {
            "name": "MEVA Mammut 350",
            "system_type": "wall",
            "supplier": "MEVA",
            "material": "steel",
            "reuses_max": 100,
            "unit_rate": Decimal("68.00"),
        },
        {
            "name": "Hünnebeck MANTO",
            "system_type": "wall",
            "supplier": "Hünnebeck",
            "material": "steel",
            "reuses_max": 100,
            "unit_rate": Decimal("60.00"),
        },
        {
            "name": "Ulma ENKOFORM V-100",
            "system_type": "wall",
            "supplier": "Ulma",
            "material": "steel",
            "reuses_max": 100,
            "unit_rate": Decimal("58.00"),
        },
        {
            "name": "PERI ACS climbing",
            "system_type": "climbing",
            "supplier": "PERI",
            "material": "steel",
            "reuses_max": 50,
            "unit_rate": Decimal("120.00"),
        },
        {
            "name": "Generic plywood + studs",
            "system_type": "custom",
            "supplier": None,
            "material": "plywood",
            "reuses_max": 8,
            "unit_rate": Decimal("18.00"),
        },
        {
            "name": "Generic timber forms",
            "system_type": "foundation",
            "supplier": None,
            "material": "timber",
            "reuses_max": 5,
            "unit_rate": Decimal("14.00"),
        },
    ]
