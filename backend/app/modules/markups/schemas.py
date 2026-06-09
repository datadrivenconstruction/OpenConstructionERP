"""‌⁠‍Markups & Annotations Pydantic schemas - request/response models.

Defines create, update, and response schemas for markups, scale configs,
and stamp templates.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Bound ints at PostgreSQL INT4 max; a PDF with > ~100k pages is obviously junk.
_INT32_MAX = 2_147_483_647
_MAX_PAGE = 100_000
_MAX_MEASUREMENT = 1e12  # m, m², m³ - no real drawing needs higher
_MAX_LENGTH = 500

# ── Markup schemas ──────────────────────────────────────────────────────


class MarkupCreate(BaseModel):
    """‌⁠‍Create a new markup annotation."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    project_id: UUID
    document_id: str | None = Field(default=None, max_length=_MAX_LENGTH)
    # Epic C - explicit version pin. When omitted the service resolves
    # the current chain head for ``document_id``. Clients can pin to a
    # historical version to draw on an old revision.
    file_version_id: UUID | None = None
    page: int = Field(default=1, ge=1, le=_MAX_PAGE)
    type: str = Field(
        ...,
        max_length=50,
        pattern=r"^(cloud|arrow|text|rectangle|highlight|distance|area|count|stamp|polygon)$",
    )
    geometry: dict[str, Any] = Field(default_factory=dict)
    text: str | None = Field(default=None, max_length=10_000)
    color: str = Field(default="#3b82f6", max_length=20)
    line_width: int = Field(default=2, ge=1, le=50)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0, allow_inf_nan=False)
    author_id: str | None = Field(default=None, max_length=255)
    # M3: optional follow-up owner.
    assignee_id: UUID | None = None
    status: str = Field(
        default="active",
        pattern=r"^(active|resolved|archived)$",
    )
    label: str | None = Field(default=None, max_length=255)
    measurement_value: float | None = Field(
        default=None, ge=-_MAX_MEASUREMENT, le=_MAX_MEASUREMENT, allow_inf_nan=False
    )
    measurement_unit: str | None = Field(default=None, max_length=20)
    stamp_template_id: UUID | None = None
    linked_boq_position_id: str | None = Field(default=None, max_length=255)
    layer: str = Field(default="default", max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarkupUpdate(BaseModel):
    """‌⁠‍Partial update for a markup annotation."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    document_id: str | None = Field(default=None, max_length=_MAX_LENGTH)
    page: int | None = Field(default=None, ge=1, le=_MAX_PAGE)
    type: str | None = Field(
        default=None,
        max_length=50,
        pattern=r"^(cloud|arrow|text|rectangle|highlight|distance|area|count|stamp|polygon)$",
    )
    geometry: dict[str, Any] | None = None
    text: str | None = Field(default=None, max_length=10_000)
    color: str | None = Field(default=None, max_length=20)
    line_width: int | None = Field(default=None, ge=1, le=50)
    opacity: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    status: str | None = Field(
        default=None,
        pattern=r"^(active|resolved|archived)$",
    )
    label: str | None = Field(default=None, max_length=255)
    measurement_value: float | None = Field(
        default=None, ge=-_MAX_MEASUREMENT, le=_MAX_MEASUREMENT, allow_inf_nan=False
    )
    measurement_unit: str | None = Field(default=None, max_length=20)
    stamp_template_id: UUID | None = None
    linked_boq_position_id: str | None = Field(default=None, max_length=255)
    layer: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] | None = None
    # M3: re-assign / unassign. ``None`` here means "not in the patch";
    # to clear an assignee explicitly the client sends an empty string,
    # which the router translates to None on the model. Bare ``None``
    # default keeps PATCH semantics intact.
    assignee_id: UUID | None = None


class MarkupResponse(BaseModel):
    """Markup annotation returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    document_id: str | None = None
    file_version_id: UUID | None = None
    page: int = 1
    type: str
    geometry: dict[str, Any] = Field(default_factory=dict)
    text: str | None = None
    color: str = "#3b82f6"
    line_width: int = 2
    opacity: float = 1.0
    author_id: str
    assignee_id: UUID | None = None
    status: str = "active"
    label: str | None = None
    # Stored as Numeric(18, 6) in the model - calibration / measurement
    # values flow into BOQ quantities, so we keep them as ``Decimal`` here
    # rather than ``float``. Typing the field ``float`` made Pydantic coerce
    # the ORM ``Decimal`` through a binary float on serialization, dropping
    # precision (e.g. 12.345678 drifting). ``Decimal`` round-trips exactly
    # and still emits a JSON number, so the client contract is unchanged.
    measurement_value: Decimal | None = None
    measurement_unit: str | None = None
    stamp_template_id: UUID | None = None
    linked_boq_position_id: str | None = None
    layer: str = "default"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_by: str = ""
    created_at: datetime
    updated_at: datetime


class MarkupBulkCreate(BaseModel):
    """Bulk create multiple markups at once."""

    markups: list[MarkupCreate] = Field(..., min_length=1, max_length=500)


class MarkupSummary(BaseModel):
    """Aggregated markup stats for a project."""

    total_markups: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)


class BoqLinkRequest(BaseModel):
    """Request body for linking a markup to a BOQ position."""

    position_id: str = Field(..., min_length=1, max_length=255)


# ── Scale Config schemas ────────────────────────────────────────────────


class ScaleConfigCreate(BaseModel):
    """Create or update a scale calibration config."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    document_id: str = Field(..., max_length=255)
    page: int = Field(default=1, ge=1, le=_MAX_PAGE)
    pixels_per_unit: float = Field(..., gt=0.0, le=1e9, allow_inf_nan=False)
    unit_label: str = Field(default="m", max_length=20)
    calibration_points: Any = Field(default_factory=dict)
    real_distance: float = Field(..., gt=0.0, le=1e9, allow_inf_nan=False)


class ScaleConfigResponse(BaseModel):
    """Scale config returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: str
    page: int = 1
    # Numeric(18, 6) in the model. Typed ``Decimal`` (not ``float``) so the
    # ORM value is not coerced through a binary float on serialization,
    # which would drift the calibration ratio that scales every measurement.
    # Pydantic still emits a JSON number, so the client contract is unchanged.
    pixels_per_unit: Decimal
    unit_label: str = "m"
    calibration_points: Any = Field(default_factory=dict)
    real_distance: Decimal
    created_by: str = ""
    created_at: datetime
    updated_at: datetime


# ── Stamp Template schemas ──────────────────────────────────────────────


class StampTemplateCreate(BaseModel):
    """Create a new stamp template."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None
    name: str = Field(..., min_length=1, max_length=255)
    category: str = Field(
        default="custom",
        pattern=r"^(predefined|custom)$",
    )
    text: str = Field(..., min_length=1, max_length=500)
    color: str = Field(default="#22c55e", max_length=20)
    background_color: str | None = Field(default=None, max_length=20)
    icon: str | None = Field(default=None, max_length=100)
    include_date: bool = True
    include_name: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class StampTemplateUpdate(BaseModel):
    """Partial update for a stamp template."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    # Category is validated on update too, mirroring StampTemplateCreate.
    # Without this field a stamp seeded with an out-of-contract category
    # could never be corrected through the API, and an arbitrary value
    # could be patched in. ``None`` keeps PATCH semantics (field absent).
    category: str | None = Field(
        default=None,
        pattern=r"^(predefined|custom)$",
    )
    text: str | None = Field(default=None, min_length=1, max_length=500)
    color: str | None = Field(default=None, max_length=20)
    background_color: str | None = Field(default=None, max_length=20)
    icon: str | None = Field(default=None, max_length=100)
    include_date: bool | None = None
    include_name: bool | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


class StampTemplateResponse(BaseModel):
    """Stamp template returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID | None = None
    owner_id: str
    name: str
    category: str = "custom"
    text: str
    color: str = "#22c55e"
    background_color: str | None = None
    icon: str | None = None
    include_date: bool = True
    include_name: bool = True
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Markup Comment schemas ──────────────────────────────────────────────


class MarkupCommentCreate(BaseModel):
    """Create a new threaded comment on a markup."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    body: str = Field(..., min_length=1, max_length=10_000)


class MarkupCommentResponse(BaseModel):
    """Threaded comment returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    markup_id: UUID
    user_id: str
    body: str
    created_at: datetime
    updated_at: datetime
