# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Punch List Pydantic schemas - request/response models.

Defines create, update, response, status transition, and summary schemas
for punch list items.
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.calendar_day import CalendarDay

# Upper bound for money fields - far above any realistic rework cost yet within
# Decimal's precision so quantize() below can never raise InvalidOperation on a
# finite-but-absurd input. Mirrors changeorders/schemas.py:_MONEY_MAX.
_MONEY_MAX = Decimal("1e15")

_CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")


def _normalise_rework_currency(v: str | None) -> str:
    """Upper-case an ISO 4217 code and refuse anything that is not one.

    The column is NOT NULL and QMS groups rework money by this code, so a null
    would fail at flush as a 500 and a lower-case spelling would split one
    currency into two buckets. Omitting the field keeps the stored code.
    """
    if v is None:
        raise ValueError("rework_cost_currency cannot be null; omit it to keep the current currency")
    code = v.strip().upper()
    if not _CURRENCY_CODE_RE.match(code):
        raise ValueError(f"rework_cost_currency must be a three-letter ISO 4217 code, got {v!r}")
    return code


# ── Punch Item schemas ──────────────────────────────────────────────────


class PunchItemCreate(BaseModel):
    """Create a new punch list item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    document_id: str | None = Field(default=None, max_length=36)
    page: int | None = Field(default=None, ge=1)
    location_x: float | None = Field(default=None, ge=0.0, le=1.0)
    location_y: float | None = Field(default=None, ge=0.0, le=1.0)
    priority: str = Field(
        default="medium",
        pattern=r"^(low|medium|high|critical)$",
    )
    assigned_to: str | None = Field(default=None, max_length=36)
    due_date: CalendarDay | None = None
    category: str | None = Field(
        default=None,
        pattern=r"^(structural|mechanical|electrical|architectural|fire_safety|plumbing|finishing|hvac|exterior|landscaping|general)$",
    )
    trade: str | None = Field(default=None, max_length=100)
    # WGS84 world-space pin (companion to the sheet-pinned location_x/y).
    # Optional - punch items without a map pin still work end-to-end.
    geo_lat: float | None = Field(default=None, ge=-90, le=90)
    geo_lon: float | None = Field(default=None, ge=-180, le=180)
    # Rework cost as Decimal string (never float - avoids binary rounding on money).
    rework_cost: str | None = Field(default=None, max_length=40)
    rework_cost_currency: str = Field(default="USD", max_length=3)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("rework_cost")
    @classmethod
    def _validate_rework_cost(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            d = Decimal(v)
        except InvalidOperation as exc:
            raise ValueError(f"rework_cost must be a valid decimal string, got {v!r}") from exc
        # Reject non-finite FIRST: Decimal("NaN") < 0 itself raises
        # InvalidOperation, and "Infinity" / "1e400" would otherwise reach
        # quantize() and raise there - either way a non-ValueError escapes
        # Pydantic as an opaque 500 instead of a clean 422.
        if not d.is_finite():
            raise ValueError("rework_cost must be a finite number (no NaN/Infinity)")
        if d < 0:
            raise ValueError("rework_cost must be non-negative")
        if d >= _MONEY_MAX:
            raise ValueError("rework_cost is outside the supported range")
        # Normalise: round to 4 dp, drop trailing zeros. Fixed-point format,
        # because str() of a normalised 900 is "9E+2".
        return format(d.quantize(Decimal("0.0001")).normalize(), "f")

    @field_validator("rework_cost_currency")
    @classmethod
    def _validate_rework_cost_currency(cls, v: str) -> str:
        return _normalise_rework_currency(v)


class PunchItemUpdate(BaseModel):
    """Partial update for a punch list item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    document_id: str | None = Field(default=None, max_length=36)
    page: int | None = Field(default=None, ge=1)
    location_x: float | None = Field(default=None, ge=0.0, le=1.0)
    location_y: float | None = Field(default=None, ge=0.0, le=1.0)
    priority: str | None = Field(
        default=None,
        pattern=r"^(low|medium|high|critical)$",
    )
    assigned_to: str | None = Field(default=None, max_length=36)
    due_date: CalendarDay | None = None
    category: str | None = Field(
        default=None,
        pattern=r"^(structural|mechanical|electrical|architectural|fire_safety|plumbing|finishing|hvac|exterior|landscaping|general)$",
    )
    trade: str | None = Field(default=None, max_length=100)
    resolution_notes: str | None = Field(default=None, max_length=5000)
    geo_lat: float | None = Field(default=None, ge=-90, le=90)
    geo_lon: float | None = Field(default=None, ge=-180, le=180)
    rework_cost: str | None = Field(default=None, max_length=40)
    rework_cost_currency: str | None = Field(default=None, max_length=3)
    metadata: dict[str, Any] | None = None

    @field_validator("rework_cost")
    @classmethod
    def _validate_rework_cost(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            d = Decimal(v)
        except InvalidOperation as exc:
            raise ValueError(f"rework_cost must be a valid decimal string, got {v!r}") from exc
        if not d.is_finite():
            raise ValueError("rework_cost must be a finite number (no NaN/Infinity)")
        if d < 0:
            raise ValueError("rework_cost must be non-negative")
        if d >= _MONEY_MAX:
            raise ValueError("rework_cost is outside the supported range")
        return format(d.quantize(Decimal("0.0001")).normalize(), "f")

    @field_validator("rework_cost_currency")
    @classmethod
    def _validate_rework_cost_currency(cls, v: str | None) -> str:
        return _normalise_rework_currency(v)


class PunchItemResponse(BaseModel):
    """Punch list item returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    title: str
    description: str = ""
    document_id: str | None = None
    page: int | None = None
    location_x: float | None = None
    location_y: float | None = None
    priority: str = "medium"
    status: str = "open"
    assigned_to: str | None = None
    #: Who ``assigned_to`` names, when it carries a contact id rather than a
    #: name someone typed. Null when the raw value is already a name, when it
    #: points at no contact, and when the contacts module is not installed.
    assigned_to_name: str | None = None
    due_date: CalendarDay | None = None
    category: str | None = None
    trade: str | None = None
    photos: list[str] = Field(default_factory=list)
    geo_lat: float | None = None
    geo_lon: float | None = None
    rework_cost: str | None = None
    rework_cost_currency: str = "USD"
    resolution_notes: str | None = None
    resolved_at: datetime | None = None
    verified_at: datetime | None = None
    verified_by: str | None = None
    #: Who ``verified_by`` names - same rule as ``assigned_to_name``.
    verified_by_name: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    reopen_history: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PunchItemListResponse(BaseModel):
    """Paginated list of punch items."""

    items: list[PunchItemResponse]
    total: int
    offset: int
    limit: int


# ── Status transition schema ────────────────────────────────────────────


class PunchStatusTransition(BaseModel):
    """Request body for a status transition.

    Allowed states (full FSM):
        open → assigned → in_progress → resolved → verified → closed
        Any state → open  (reopen, also via the ``reopened`` alias)
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    new_status: str = Field(
        ...,
        pattern=r"^(open|assigned|in_progress|resolved|verified|closed|reopened)$",
    )
    notes: str | None = Field(default=None, max_length=5000)


# ── Summary schema ──────────────────────────────────────────────────────


class PunchListSummary(BaseModel):
    """Aggregated punch list stats for a project.

    Every field here is computed over the whole project. The KPI band used to
    derive the last three from whatever rows the list endpoint happened to
    return, which is one page, so a project with more items than fit a page
    reported numbers that were simply wrong.
    """

    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_priority: dict[str, int] = Field(default_factory=dict)
    overdue: int = 0
    avg_days_to_close: float | None = None
    #: Critical or high priority items that are still open or in progress.
    urgent_open: int = 0
    #: Items closed or verified within the last seven days.
    closed_last_7_days: int = 0
    #: Mean age in days of items still open or in progress, None when none are.
    avg_open_age_days: float | None = None


# ── Bulk close schema ──────────────────────────────────────────────────


class PunchBulkCloseRequest(BaseModel):
    """Request body for bulk-closing multiple punch items at once."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    ids: list[UUID] = Field(..., min_length=1, max_length=500)
    comment: str | None = Field(default=None, max_length=2000)


class PunchBulkCloseError(BaseModel):
    """Per-item error entry returned by the bulk-close endpoint."""

    id: UUID
    error: str


class PunchBulkCloseResponse(BaseModel):
    """Response summary from the bulk-close endpoint."""

    closed: int = 0
    skipped: int = 0
    errors: list[PunchBulkCloseError] = Field(default_factory=list)


# ── Pin-to-sheet schema ────────────────────────────────────────────────


class PinToSheetRequest(BaseModel):
    """Request body for pinning a punch item to a document sheet location."""

    model_config = ConfigDict(str_strip_whitespace=True)

    sheet_id: str | None = Field(default=None, description="Sheet UUID (optional if document_id provided)")
    document_id: str | None = Field(default=None, description="Document UUID (optional if sheet_id provided)")
    page: int = Field(..., ge=1, description="Page number on the document/sheet")
    location_x: float = Field(..., ge=0.0, le=1.0, description="Normalised X coordinate (0.0–1.0)")
    location_y: float = Field(..., ge=0.0, le=1.0, description="Normalised Y coordinate (0.0–1.0)")
