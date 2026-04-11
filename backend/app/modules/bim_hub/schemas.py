"""BIM Hub Pydantic schemas — request/response models.

Defines create, update, and response schemas for BIM models, elements,
BOQ links, quantity maps, and model diffs.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── BIMModel schemas ─────────────────────────────────────────────────────────


class BIMModelCreate(BaseModel):
    """Create a new BIM model record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    discipline: str | None = Field(default=None, max_length=50)
    model_format: str | None = Field(default=None, max_length=20)
    version: str = Field(default="1", max_length=20)
    import_date: str | None = Field(default=None, max_length=20)
    status: str = Field(default="processing", max_length=50)
    bounding_box: dict[str, Any] | None = None
    original_file_id: str | None = Field(default=None, max_length=36)
    canonical_file_path: str | None = Field(default=None, max_length=500)
    parent_model_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BIMModelUpdate(BaseModel):
    """Partial update for a BIM model."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    discipline: str | None = Field(default=None, max_length=50)
    model_format: str | None = Field(default=None, max_length=20)
    version: str | None = Field(default=None, max_length=20)
    import_date: str | None = Field(default=None, max_length=20)
    status: str | None = Field(default=None, max_length=50)
    element_count: int | None = None
    storey_count: int | None = None
    bounding_box: dict[str, Any] | None = None
    original_file_id: str | None = Field(default=None, max_length=36)
    canonical_file_path: str | None = Field(default=None, max_length=500)
    parent_model_id: UUID | None = None
    error_message: str | None = None
    metadata: dict[str, Any] | None = None


class BIMModelResponse(BaseModel):
    """BIM model returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    discipline: str | None = None
    model_format: str | None = None
    version: str
    import_date: str | None = None
    status: str
    element_count: int
    storey_count: int
    bounding_box: dict[str, Any] | None = None
    original_file_id: str | None = None
    canonical_file_path: str | None = None
    parent_model_id: UUID | None = None
    error_message: str | None = None
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class BIMModelListResponse(BaseModel):
    """Paginated list of BIM models."""

    items: list[BIMModelResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


# ── BIMElement schemas ───────────────────────────────────────────────────────


class BIMElementCreate(BaseModel):
    """Create a single BIM element."""

    model_config = ConfigDict(str_strip_whitespace=True)

    stable_id: str = Field(..., min_length=1, max_length=255)
    element_type: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=500)
    storey: str | None = Field(default=None, max_length=255)
    discipline: str | None = Field(default=None, max_length=50)
    properties: dict[str, Any] = Field(default_factory=dict)
    quantities: dict[str, Any] = Field(default_factory=dict)
    geometry_hash: str | None = Field(default=None, max_length=64)
    bounding_box: dict[str, Any] | None = None
    mesh_ref: str | None = Field(default=None, max_length=500)
    lod_variants: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BIMElementBulkImport(BaseModel):
    """Bulk import of elements for a model."""

    model_config = ConfigDict(str_strip_whitespace=True)

    elements: list[BIMElementCreate] = Field(..., min_length=1, max_length=50000)


class BOQElementLinkBrief(BaseModel):
    """Lightweight BOQ link summary embedded in a BIM element response.

    Contains just enough data for the viewer to render a link badge and
    navigate to the linked BOQ position without a second round trip.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    boq_position_id: UUID
    boq_position_ordinal: str | None = None
    boq_position_description: str | None = None
    link_type: str
    confidence: str | None = None


class BIMElementResponse(BaseModel):
    """BIM element returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    model_id: UUID
    stable_id: str
    element_type: str | None = None
    name: str | None = None
    storey: str | None = None
    discipline: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    quantities: dict[str, Any] = Field(default_factory=dict)
    geometry_hash: str | None = None
    bounding_box: dict[str, Any] | None = None
    mesh_ref: str | None = None
    lod_variants: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    boq_links: list[BOQElementLinkBrief] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class BIMElementListResponse(BaseModel):
    """Paginated list of BIM elements."""

    items: list[BIMElementResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 200


# ── BOQElementLink schemas ───────────────────────────────────────────────────


class BOQElementLinkCreate(BaseModel):
    """Create a link between a BOQ position and a BIM element."""

    model_config = ConfigDict(str_strip_whitespace=True)

    boq_position_id: UUID
    bim_element_id: UUID
    link_type: str = Field(default="manual", max_length=50)
    confidence: str | None = Field(default=None, max_length=10)
    rule_id: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BOQElementLinkResponse(BaseModel):
    """BOQ-BIM link returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    boq_position_id: UUID
    bim_element_id: UUID
    link_type: str
    confidence: str | None = None
    rule_id: str | None = None
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class BOQElementLinkListResponse(BaseModel):
    """List of BOQ-BIM links."""

    items: list[BOQElementLinkResponse] = Field(default_factory=list)
    total: int = 0


# ── BIMQuantityMap schemas ───────────────────────────────────────────────────


class BIMQuantityMapCreate(BaseModel):
    """Create a quantity mapping rule."""

    model_config = ConfigDict(str_strip_whitespace=True)

    org_id: UUID | None = None
    project_id: UUID | None = None
    name: str = Field(..., min_length=1, max_length=255)
    name_translations: dict[str, str] | None = None
    element_type_filter: str | None = Field(default=None, max_length=100)
    property_filter: dict[str, Any] | None = None
    quantity_source: str = Field(..., min_length=1, max_length=100)
    multiplier: str = Field(default="1", max_length=20)
    unit: str | None = Field(default=None, max_length=20)
    waste_factor_pct: str = Field(default="0", max_length=10)
    boq_target: dict[str, Any] | None = None
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class BIMQuantityMapUpdate(BaseModel):
    """Partial update for a quantity mapping rule."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    name_translations: dict[str, str] | None = None
    element_type_filter: str | None = Field(default=None, max_length=100)
    property_filter: dict[str, Any] | None = None
    quantity_source: str | None = Field(default=None, min_length=1, max_length=100)
    multiplier: str | None = Field(default=None, max_length=20)
    unit: str | None = Field(default=None, max_length=20)
    waste_factor_pct: str | None = Field(default=None, max_length=10)
    boq_target: dict[str, Any] | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


class BIMQuantityMapResponse(BaseModel):
    """Quantity mapping rule returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    org_id: UUID | None = None
    project_id: UUID | None = None
    name: str
    name_translations: dict[str, str] | None = None
    element_type_filter: str | None = None
    property_filter: dict[str, Any] | None = None
    quantity_source: str
    multiplier: str
    unit: str | None = None
    waste_factor_pct: str
    boq_target: dict[str, Any] | None = None
    is_active: bool
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class BIMQuantityMapListResponse(BaseModel):
    """List of quantity mapping rules."""

    items: list[BIMQuantityMapResponse] = Field(default_factory=list)
    total: int = 0


class QuantityMapApplyRequest(BaseModel):
    """Request to apply quantity mapping rules to a model's elements."""

    model_config = ConfigDict(str_strip_whitespace=True)

    model_id: UUID
    dry_run: bool = Field(
        default=True,
        description=(
            "If True (default), return the preview without creating any "
            "BOQElementLink or BOQPosition rows. Set to False to actually "
            "persist links and auto-created positions."
        ),
    )


class QuantityMapApplyResult(BaseModel):
    """Result of applying quantity mapping rules.

    ``links_created`` and ``positions_created`` are always reported — they
    stay at 0 on a ``dry_run`` so the caller can safely display them as
    "would-be" counters without extra branching.
    """

    matched_elements: int = 0
    rules_applied: int = 0
    links_created: int = 0
    positions_created: int = 0
    results: list[dict[str, Any]] = Field(default_factory=list)


# ── BIMModelDiff schemas ─────────────────────────────────────────────────────


class BIMModelDiffResponse(BaseModel):
    """Model diff returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    old_model_id: UUID
    new_model_id: UUID
    diff_summary: dict[str, Any]
    diff_details: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
