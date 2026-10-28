# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Preliminaries Pydantic schemas - request / response models.

Money contract (matches costs / cvr): every monetary value is a
``decimal.Decimal`` in Python and on the database (``NUMERIC(18, 4)``), and is
emitted on the wire as a plain decimal *string* through :data:`DecimalMoney` so a
large total round-trips without JSON's float bridge silently rounding it. Inputs
accept any JSON number or numeric string - Pydantic v2 promotes them to
``Decimal`` and ``ge=0`` rejects a negative. Money is never a float.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

# Money fields ride the wire as strings (mirrors the DecimalMoney alias in
# costs / cvr) so a precision-critical amount never rides through a JSON float.
DecimalMoney = Annotated[
    Decimal,
    PlainSerializer(lambda v: str(v) if v is not None else None, return_type=str),
]

# Accepted item types.
ITEM_TYPE_PATTERN = r"^(time_related|fixed)$"


class PrelimItemCreate(BaseModel):
    """Create one preliminaries item on a project."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    project_id: UUID
    label: str = Field(default="", max_length=255)
    category: str = Field(default="general", max_length=80)
    item_type: str = Field(default="time_related", pattern=ITEM_TYPE_PATTERN)
    rate_per_period: DecimalMoney = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    periods: DecimalMoney = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    fixed_amount: DecimalMoney = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    sort_order: int = Field(default=0, ge=0)


class PrelimItemUpdate(BaseModel):
    """Partial update of a preliminaries item."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    label: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=80)
    item_type: str | None = Field(default=None, pattern=ITEM_TYPE_PATTERN)
    rate_per_period: DecimalMoney | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    periods: DecimalMoney | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    fixed_amount: DecimalMoney | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    sort_order: int | None = Field(default=None, ge=0)


class PrelimItemResponse(BaseModel):
    """A preliminaries item returned from the API, with its priced line total."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    label: str = ""
    category: str = "general"
    item_type: str = "time_related"
    rate_per_period: DecimalMoney = Decimal("0")
    periods: DecimalMoney = Decimal("0")
    fixed_amount: DecimalMoney = Decimal("0")
    sort_order: int = 0
    # Derived, read-only: rate_per_period * periods (time-related) or fixed_amount.
    line_total: DecimalMoney = Decimal("0")
    created_at: datetime
    updated_at: datetime


class PrelimCategorySummary(BaseModel):
    """The priced roll-up for one preliminaries category."""

    category: str
    time_related_total: DecimalMoney = Decimal("0")
    fixed_total: DecimalMoney = Decimal("0")
    total: DecimalMoney = Decimal("0")
    item_count: int = 0


class PreliminariesSummary(BaseModel):
    """Project-level preliminaries roll-up: per category and grand total."""

    project_id: UUID
    categories: list[PrelimCategorySummary] = Field(default_factory=list)
    time_related_total: DecimalMoney = Decimal("0")
    fixed_total: DecimalMoney = Decimal("0")
    grand_total: DecimalMoney = Decimal("0")
    item_count: int = 0


class StarterChecklistItem(BaseModel):
    """A suggested preliminaries item label (amounts are entered by the user)."""

    label: str
    category: str
    item_type: str = "time_related"


class StarterChecklistResponse(BaseModel):
    """The starter checklist of common preliminaries items."""

    items: list[StarterChecklistItem] = Field(default_factory=list)
