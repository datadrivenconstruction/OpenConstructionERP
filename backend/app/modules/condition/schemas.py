# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Condition assessment request and response schemas.

Money and quantities travel as decimal strings, never floats.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

_ASSET_KIND = r"^(bim_element|plant_item|element)$"
_ACTION_TYPE = r"^(inspect|maintain|repair|replace)$"
_ACTION_STATUS = r"^(proposed|approved|done|rejected)$"
_CURRENCY = r"^[A-Z]{3}$"


def _dec_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


# ── Scales ───────────────────────────────────────────────────────────────────


class ScaleLevel(BaseModel):
    """One level of a condition scale (level 1 is the best condition)."""

    level: int = Field(..., ge=1, le=10)
    label: str = Field(..., min_length=1, max_length=80)
    label_key: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    color: str | None = Field(default=None, max_length=20)
    action: dict[str, Any] | None = None


class ScaleCreate(BaseModel):
    """A project-defined condition scale."""

    key: str = Field(..., min_length=1, max_length=60, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    action_threshold: int | None = Field(default=None, ge=1, le=10)
    levels: list[ScaleLevel] = Field(..., min_length=2, max_length=10)


class ScaleResponse(BaseModel):
    """A condition scale from any source (builtin, pack, custom)."""

    key: str
    name: str
    description: str | None = None
    action_threshold: int
    levels: list[dict[str, Any]]
    source: str
    pack_slug: str | None = None
    id: uuid.UUID | None = None


# ── Assessments ──────────────────────────────────────────────────────────────


class AssessmentBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    inspection_id: str | None = Field(default=None, max_length=36)
    asset_kind: str = Field(default="element", pattern=_ASSET_KIND)
    asset_ref: str | None = Field(default=None, max_length=100)
    element_name: str = Field(..., min_length=1, max_length=255)
    element_code: str | None = Field(default=None, max_length=60)
    area: str | None = Field(default=None, max_length=255)
    scale_key: str = Field(default="default_6", min_length=1, max_length=60)
    rating: int = Field(..., ge=1, le=10)
    severity: int | None = Field(default=None, ge=1, le=4)
    extent_pct: float | None = Field(default=None, ge=0, le=100)
    intensity: int | None = Field(default=None, ge=1, le=4)
    defect_description: str | None = Field(default=None, max_length=5000)
    recommended_action: str | None = Field(default=None, max_length=2000)
    quantity: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    unit: str | None = Field(default=None, max_length=20)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency: str | None = Field(default=None, pattern=_CURRENCY)
    assessed_at: date | None = None
    notes: str | None = Field(default=None, max_length=5000)


class AssessmentCreate(AssessmentBase):
    """Record a condition rating."""

    project_id: uuid.UUID


class AssessmentUpdate(BaseModel):
    """Partial update of an assessment."""

    model_config = ConfigDict(str_strip_whitespace=True)

    asset_kind: str | None = Field(default=None, pattern=_ASSET_KIND)
    asset_ref: str | None = Field(default=None, max_length=100)
    element_name: str | None = Field(default=None, min_length=1, max_length=255)
    element_code: str | None = Field(default=None, max_length=60)
    area: str | None = Field(default=None, max_length=255)
    rating: int | None = Field(default=None, ge=1, le=10)
    severity: int | None = Field(default=None, ge=1, le=4)
    extent_pct: float | None = Field(default=None, ge=0, le=100)
    intensity: int | None = Field(default=None, ge=1, le=4)
    defect_description: str | None = Field(default=None, max_length=5000)
    recommended_action: str | None = Field(default=None, max_length=2000)
    quantity: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    unit: str | None = Field(default=None, max_length=20)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency: str | None = Field(default=None, pattern=_CURRENCY)
    assessed_at: date | None = None
    notes: str | None = Field(default=None, max_length=5000)


class AssessmentResponse(BaseModel):
    """A stored condition rating."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    project_id: uuid.UUID
    inspection_id: str | None = None
    asset_kind: str
    asset_ref: str | None = None
    element_name: str
    element_code: str | None = None
    area: str | None = None
    scale_key: str
    rating: int
    suggested_rating: int | None = None
    suggestion_confidence: float | None = None
    severity: int | None = None
    extent_pct: float | None = None
    intensity: int | None = None
    defect_description: str | None = None
    recommended_action: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    unit_cost: Decimal | None = None
    currency: str | None = None
    assessed_at: date | None = None
    assessed_by: str | None = None
    photos: list[Any] = Field(default_factory=list)
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("quantity", "unit_cost")
    def _ser_dec(self, value: Decimal | None) -> str | None:
        return _dec_str(value)


class RatingSuggestionRequest(BaseModel):
    """Ask for a rating proposal from a defect record."""

    scale_key: str = Field(default="default_6", max_length=60)
    project_id: uuid.UUID | None = None
    severity: int | None = Field(default=None, ge=1, le=4)
    extent_pct: float | None = Field(default=None, ge=0, le=100)
    intensity: int | None = Field(default=None, ge=1, le=4)


class RatingSuggestionResponse(BaseModel):
    """A proposed rating; the inspector decides."""

    rating: int | None = None
    confidence: float = 0.0
    level: dict[str, Any] | None = None


# ── Maintenance actions ──────────────────────────────────────────────────────


class ActionCreate(BaseModel):
    """A manually planned maintenance action."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: uuid.UUID
    assessment_id: uuid.UUID | None = None
    asset_kind: str = Field(default="element", pattern=_ASSET_KIND)
    asset_ref: str | None = Field(default=None, max_length=100)
    element_name: str = Field(..., min_length=1, max_length=255)
    area: str | None = Field(default=None, max_length=255)
    action_type: str = Field(..., pattern=_ACTION_TYPE)
    description: str = Field(default="", max_length=500)
    first_year: int = Field(..., ge=1900, le=2300)
    interval_years: int | None = Field(default=None, ge=1, le=100)
    quantity: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    unit: str | None = Field(default=None, max_length=20)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency: str | None = Field(default=None, pattern=_CURRENCY)
    priority: int = Field(default=3, ge=1, le=4)
    notes: str | None = Field(default=None, max_length=5000)


class ActionUpdate(BaseModel):
    """Partial update of an action (status changes are the human decision)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    action_type: str | None = Field(default=None, pattern=_ACTION_TYPE)
    description: str | None = Field(default=None, max_length=500)
    first_year: int | None = Field(default=None, ge=1900, le=2300)
    interval_years: int | None = Field(default=None, ge=1, le=100)
    quantity: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    unit: str | None = Field(default=None, max_length=20)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency: str | None = Field(default=None, pattern=_CURRENCY)
    priority: int | None = Field(default=None, ge=1, le=4)
    status: str | None = Field(default=None, pattern=_ACTION_STATUS)
    notes: str | None = Field(default=None, max_length=5000)


class ActionResponse(BaseModel):
    """A stored maintenance action."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    assessment_id: uuid.UUID | None = None
    asset_kind: str
    asset_ref: str | None = None
    element_name: str
    area: str | None = None
    action_type: str
    description: str
    first_year: int
    interval_years: int | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    unit_cost: Decimal | None = None
    currency: str | None = None
    priority: int
    status: str
    source: str
    confidence: float | None = None
    decided_by: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("quantity", "unit_cost")
    def _ser_dec(self, value: Decimal | None) -> str | None:
        return _dec_str(value)


class DeriveRequest(BaseModel):
    """Propose actions from the latest rating of each asset or element."""

    base_year: int | None = Field(default=None, ge=1900, le=2300)


class DeriveResponse(BaseModel):
    """Proposals created by a derive run."""

    created: int
    skipped: int
    actions: list[ActionResponse] = Field(default_factory=list)


class ApplyToAssetsResponse(BaseModel):
    """Result of writing plan figures into the asset register."""

    updated: int
    skipped: int
    asset_refs: list[str] = Field(default_factory=list)


class ScaleListResponse(BaseModel):
    """A page of ScaleResponse with the count of rows the filters matched."""

    items: list[ScaleResponse]
    total: int
    offset: int = 0
    limit: int = 50


class AssessmentListResponse(BaseModel):
    """A page of AssessmentResponse with the count of rows the filters matched."""

    items: list[AssessmentResponse]
    total: int
    offset: int = 0
    limit: int = 50


class ActionListResponse(BaseModel):
    """A page of ActionResponse with the count of rows the filters matched."""

    items: list[ActionResponse]
    total: int
    offset: int = 0
    limit: int = 50
