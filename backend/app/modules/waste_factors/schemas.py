# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Waste-factor Pydantic schemas (request / response).

Factors and quantities are ``Decimal`` on input and JSON *strings* on output,
matching the platform-wide "Decimal as string" contract so a precise multiplier
or a large takeoff quantity never loses digits through a JS ``Number``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.modules.waste_factors.waste_math import quantize_qty

# A stored factor is a multiplier >= 1; the upper bound is a fat-finger guard
# (entering 110 for "1.10" is far more likely than a genuine 10x coverage).
_FACTOR = Field(default=Decimal("1"), ge=1, le=10)


def _dec_to_str(value: Decimal | None) -> str | None:
    """Render a Decimal verbatim as a fixed-point string (``None`` -> ``None``)."""
    if value is None:
        return None
    return format(Decimal(value), "f")


# -- WasteFactor CRUD ------------------------------------------------------


class WasteFactorCreate(BaseModel):
    """Create a new waste-factor library row."""

    model_config = ConfigDict(str_strip_whitespace=True)

    category: str = Field(..., min_length=1, max_length=120)
    label: str = Field(default="", max_length=200)
    factor: Decimal = _FACTOR
    note: str | None = None
    tenant_id: UUID | None = None


class WasteFactorUpdate(BaseModel):
    """Partial update for a waste-factor library row."""

    model_config = ConfigDict(str_strip_whitespace=True)

    category: str | None = Field(default=None, min_length=1, max_length=120)
    label: str | None = Field(default=None, max_length=200)
    factor: Decimal | None = Field(default=None, ge=1, le=10)
    note: str | None = None


class WasteFactorResponse(BaseModel):
    """A waste-factor library row as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category: str
    label: str
    factor: Decimal
    note: str | None = None
    tenant_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("factor")
    def _ser_factor(self, v: Decimal) -> str:
        return _dec_to_str(v)  # type: ignore[return-value]


class WasteFactorSeedResult(BaseModel):
    """Response payload for ``POST /seed-defaults``."""

    inserted: int
    skipped: int
    total_after: int


# -- Apply (net -> gross) --------------------------------------------------


class ApplyLineInput(BaseModel):
    """One net line to convert: a category and its net measured quantity."""

    model_config = ConfigDict(str_strip_whitespace=True)

    category: str = Field(..., min_length=1, max_length=120)
    net_qty: Decimal = Field(..., ge=0)


class ApplyRequest(BaseModel):
    """A batch of net lines to convert to gross procurement quantities."""

    lines: list[ApplyLineInput] = Field(default_factory=list, max_length=2000)


class ApplyLineResult(BaseModel):
    """One converted line: the resolved factor and the gross quantity.

    ``matched`` is ``False`` when the category had no library entry and the
    pass-through default factor (1.0) was applied.
    """

    category: str
    net_qty: Decimal
    factor: Decimal
    gross_qty: Decimal
    matched: bool

    @field_serializer("net_qty", "gross_qty", "factor")
    def _ser_qty(self, v: Decimal) -> str:
        return format(quantize_qty(v), "f")


class ApplyResponse(BaseModel):
    """The per-line result of a net-to-gross apply.

    There is deliberately no cross-line total: lines can carry different units
    (m3 of concrete, kg of rebar), so a single summed quantity would be
    meaningless.
    """

    lines: list[ApplyLineResult]
