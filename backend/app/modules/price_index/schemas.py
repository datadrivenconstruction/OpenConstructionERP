# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic v2 schemas for the price-index module.

Factors and money are carried as :class:`~decimal.Decimal` and emitted as
plain decimal *strings* on the wire (via :data:`DecimalStr`) so a precise value
never loses digits through a JSON ``float`` bridge - the platform-wide
"money / factor as string" convention.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator

# Upper bound shared by every numeric input. 1e12 is far beyond any real index
# value / money amount yet keeps each pairwise product finite in Decimal, so an
# adjusted amount can never overflow to a non-finite value.
_NUM_MAX: Decimal = Decimal("1000000000000")

# ISO year-month, ``YYYY-MM`` with a real month 01-12.
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _decimal_to_str(value: Decimal | None) -> str | None:
    """Serialise a ``Decimal`` as a fixed-point string (never exponent form)."""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    if not value.is_finite():
        return None
    return format(value, "f")


# Decimal that JSON-serialises to a plain string. Reused for every factor and
# money field on the response models.
DecimalStr = Annotated[Decimal, PlainSerializer(_decimal_to_str, return_type=str)]


def _validate_period(value: str) -> str:
    """Reject anything that is not a ``YYYY-MM`` string with a real month."""
    text = value.strip()
    if not PERIOD_RE.match(text):
        raise ValueError("period must be an ISO year-month string, e.g. '2026-01'")
    return text


def _reject_non_finite(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("value must be finite (no NaN / Infinity)")
    return value


# ── Cost-index series ────────────────────────────────────────────────────────


class CostIndexSeriesCreate(BaseModel):
    """Create a new cost-index series."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)


class CostIndexSeriesUpdate(BaseModel):
    """Partial update for a cost-index series."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)


class CostIndexSeriesResponse(BaseModel):
    """A cost-index series header as returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    name: str
    description: str
    point_count: int = 0
    created_at: datetime
    updated_at: datetime


# ── Cost-index points ────────────────────────────────────────────────────────


class CostIndexPointCreate(BaseModel):
    """Add one ``(period, factor)`` point to a series."""

    model_config = ConfigDict(str_strip_whitespace=True)

    period: str = Field(..., description="ISO year-month, e.g. '2026-01'")
    factor: Decimal = Field(..., gt=0, le=_NUM_MAX)

    @field_validator("period")
    @classmethod
    def _check_period(cls, value: str) -> str:
        return _validate_period(value)

    @field_validator("factor")
    @classmethod
    def _check_factor(cls, value: Decimal) -> Decimal:
        return _reject_non_finite(value)


class CostIndexPointUpdate(BaseModel):
    """Update the factor (and optionally the period) of a point."""

    model_config = ConfigDict(str_strip_whitespace=True)

    period: str | None = Field(default=None)
    factor: Decimal | None = Field(default=None, gt=0, le=_NUM_MAX)

    @field_validator("period")
    @classmethod
    def _check_period(cls, value: str | None) -> str | None:
        return _validate_period(value) if value is not None else None

    @field_validator("factor")
    @classmethod
    def _check_factor(cls, value: Decimal | None) -> Decimal | None:
        return _reject_non_finite(value) if value is not None else None


class CostIndexPointResponse(BaseModel):
    """A single index point as returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    series_id: UUID
    period: str
    factor: DecimalStr = Decimal("1")
    created_at: datetime
    updated_at: datetime


class CostIndexSeriesDetail(CostIndexSeriesResponse):
    """A series header plus all of its points, ordered by period."""

    points: list[CostIndexPointResponse] = Field(default_factory=list)


# ── Location factors ─────────────────────────────────────────────────────────


class LocationFactorCreate(BaseModel):
    """Create a regional cost factor."""

    model_config = ConfigDict(str_strip_whitespace=True)

    region_code: str = Field(..., min_length=1, max_length=64)
    label: str = Field(default="", max_length=255)
    factor: Decimal = Field(..., gt=0, le=_NUM_MAX)

    @field_validator("factor")
    @classmethod
    def _check_factor(cls, value: Decimal) -> Decimal:
        return _reject_non_finite(value)


class LocationFactorUpdate(BaseModel):
    """Partial update for a regional cost factor."""

    model_config = ConfigDict(str_strip_whitespace=True)

    region_code: str | None = Field(default=None, min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=255)
    factor: Decimal | None = Field(default=None, gt=0, le=_NUM_MAX)

    @field_validator("factor")
    @classmethod
    def _check_factor(cls, value: Decimal | None) -> Decimal | None:
        return _reject_non_finite(value) if value is not None else None


class LocationFactorResponse(BaseModel):
    """A regional cost factor as returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    region_code: str
    label: str
    factor: DecimalStr = Decimal("1")
    created_at: datetime
    updated_at: datetime


# ── Adjust ───────────────────────────────────────────────────────────────────


class AdjustLine(BaseModel):
    """One amount to bring from a base period/region to a target period/region."""

    model_config = ConfigDict(str_strip_whitespace=True)

    amount: Decimal = Field(..., ge=0, le=_NUM_MAX)
    base_period: str = Field(..., description="ISO year-month the amount is expressed in")
    target_period: str = Field(..., description="ISO year-month to bring the amount to")
    base_region: str | None = Field(default=None, max_length=64)
    target_region: str | None = Field(default=None, max_length=64)

    @field_validator("amount")
    @classmethod
    def _check_amount(cls, value: Decimal) -> Decimal:
        return _reject_non_finite(value)

    @field_validator("base_period", "target_period")
    @classmethod
    def _check_period(cls, value: str) -> str:
        return _validate_period(value)


class AdjustRequest(BaseModel):
    """Adjust a batch of amounts against one chosen cost-index series."""

    model_config = ConfigDict(str_strip_whitespace=True)

    series_id: UUID
    lines: list[AdjustLine] = Field(..., min_length=1, max_length=1000)


class AdjustLineResult(BaseModel):
    """The adjustment outcome for one input line.

    ``temporal_factor``, ``location_factor``, ``applied_factor`` and
    ``adjusted_amount`` are ``null`` when ``error`` is set (for example a
    period missing from the series), so a single bad line never voids the
    whole batch.
    """

    amount: DecimalStr
    base_period: str
    target_period: str
    base_region: str | None = None
    target_region: str | None = None
    temporal_factor: DecimalStr | None = None
    location_factor: DecimalStr | None = None
    applied_factor: DecimalStr | None = None
    adjusted_amount: DecimalStr | None = None
    note: str | None = None
    error: str | None = None


class AdjustResponse(BaseModel):
    """The full result of an :class:`AdjustRequest`."""

    series_id: UUID
    series_name: str
    results: list[AdjustLineResult] = Field(default_factory=list)


# ── Escalate stored rates (preview) ───────────────────────────────────────────


class EscalatePreviewRequest(BaseModel):
    """Select stored cost items and preview their rates escalated to a date.

    The escalation is purely temporal: each selected item's own stored rate is
    brought from the period of its ``price_as_of`` capture date to the period of
    ``target_date`` using the chosen index series. This is a read-only preview -
    nothing is ever written back to the cost items or the BOQ.

    Two scopes decide *which* rates are escalated:

    * **Catalogue** (default): pass explicit ``cost_item_ids`` and / or a
      ``region`` / ``category`` filter; every supplied constraint is applied
      together (AND). It escalates cost-database rows regardless of any project.
    * **Project**: pass ``project_id`` to escalate exactly the rates the
      project's BOQ actually references (the DISTINCT cost items its positions
      link to via ``metadata.cost_item_id``). A supplied ``region`` /
      ``category`` narrows that project set further (AND); ``cost_item_ids`` is
      ignored in this scope.

    At least one selector (``project_id``, ``cost_item_ids`` or a ``region`` /
    ``category`` filter) is required so the whole catalogue is never escalated
    by accident. When ``series_id`` is omitted and exactly one series exists,
    that series is used; with several series ``series_id`` must be given.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    target_date: date = Field(..., description="Calendar date to bring the stored rates to")
    series_id: UUID | None = Field(
        default=None,
        description="Index series to escalate against; optional when only one series exists",
    )
    project_id: UUID | None = Field(
        default=None,
        description="Escalate the rates this project's BOQ actually references (the DISTINCT cost items "
        "its positions link to); narrowed by any region / category filter",
    )
    region: str | None = Field(default=None, max_length=50, description="Filter items by region")
    category: str | None = Field(
        default=None,
        max_length=255,
        description="Filter items by classification collection (the top classification level)",
    )
    cost_item_ids: list[UUID] | None = Field(
        default=None,
        max_length=5000,
        description="Explicit cost items to escalate (catalogue scope only)",
    )

    @model_validator(mode="after")
    def _require_a_selector(self) -> EscalatePreviewRequest:
        has_project = self.project_id is not None
        has_ids = bool(self.cost_item_ids)
        has_filter = bool((self.region or "").strip() or (self.category or "").strip())
        if not has_project and not has_ids and not has_filter:
            raise ValueError("provide project_id, cost_item_ids and / or a region / category filter to select items")
        return self


class EscalatePreviewLine(BaseModel):
    """One cost item's stored rate previewed at the target date.

    ``base_date``, ``base_period``, ``factor`` and ``escalated_rate`` are
    ``null`` and ``escalatable`` is ``False`` when the rate cannot be escalated -
    most commonly because ``price_as_of`` is null, the stored rate is not a
    number, or the base / target period is absent from the series. ``note`` then
    explains why, so a single unescalatable item never voids the batch.
    """

    cost_item_id: UUID
    code: str
    unit: str = ""
    region: str | None = None
    currency: str = ""
    base_rate: DecimalStr | None = None
    base_date: date | None = None
    base_period: str | None = None
    factor: DecimalStr | None = None
    escalated_rate: DecimalStr | None = None
    escalatable: bool = False
    note: str | None = None


class EscalatePreviewResponse(BaseModel):
    """The full result of an :class:`EscalatePreviewRequest`.

    ``scope`` records which selection ran: ``"catalogue"`` (region / category /
    explicit ids) or ``"project"`` (the rates a project's BOQ references). In
    project scope ``project_id`` / ``project_name`` identify the project and
    ``project_fallback`` is ``True`` when no position carried a typed
    ``cost_item_id`` link so the project's own region was used as the proxy
    instead (see the service for the documented fallback).
    """

    series_id: UUID
    series_name: str
    target_date: date
    target_period: str
    item_count: int
    escalatable_count: int
    scope: str = "catalogue"
    project_id: UUID | None = None
    project_name: str | None = None
    project_fallback: bool = False
    results: list[EscalatePreviewLine] = Field(default_factory=list)
