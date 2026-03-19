"""BOQ Pydantic schemas — request/response models.

Defines create, update, and response schemas for BOQs, positions, markups,
structured (sectioned) BOQ responses, templates, and activity log entries.

Numeric values (quantity, unit_rate, total) are exposed as floats in the API
but stored as strings in SQLite-compatible models.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── BOQ schemas ───────────────────────────────────────────────────────────────


class BOQCreate(BaseModel):
    """Create a new Bill of Quantities."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""


class BOQUpdate(BaseModel):
    """Partial update for a BOQ."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: str | None = Field(default=None, pattern=r"^(draft|final|archived)$")
    metadata: dict[str, Any] | None = None


class BOQResponse(BaseModel):
    """BOQ returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    description: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Position schemas ──────────────────────────────────────────────────────────


class PositionCreate(BaseModel):
    """Create a new BOQ position."""

    model_config = ConfigDict(str_strip_whitespace=True)

    boq_id: UUID
    parent_id: UUID | None = None
    ordinal: str = Field(..., min_length=1, max_length=50)
    description: str = Field(default="")
    unit: str = Field(..., min_length=1, max_length=20)
    quantity: float = Field(default=0.0, ge=0.0)
    unit_rate: float = Field(default=0.0, ge=0.0)
    classification: dict[str, Any] = Field(default_factory=dict)
    source: str = "manual"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    cad_element_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SectionCreate(BaseModel):
    """Create a BOQ section (header row without pricing).

    Sections are top-level grouping rows.  They have an ordinal and
    description but no unit, quantity, or unit_rate.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    ordinal: str = Field(..., min_length=1, max_length=50)
    description: str = Field(default="")
    metadata: dict[str, Any] = Field(default_factory=dict)


class PositionUpdate(BaseModel):
    """Partial update for a BOQ position."""

    model_config = ConfigDict(str_strip_whitespace=True)

    parent_id: UUID | None = None
    ordinal: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None)
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    quantity: float | None = Field(default=None, ge=0.0)
    unit_rate: float | None = Field(default=None, ge=0.0)
    classification: dict[str, Any] | None = None
    source: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    cad_element_ids: list[str] | None = None
    validation_status: str | None = None
    metadata: dict[str, Any] | None = None
    sort_order: int | None = None


class PositionResponse(BaseModel):
    """Position returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    boq_id: UUID
    parent_id: UUID | None
    ordinal: str
    description: str
    unit: str
    quantity: float
    unit_rate: float
    total: float
    classification: dict[str, Any]
    source: str
    confidence: float | None
    cad_element_ids: list[str]
    validation_status: str
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    sort_order: int
    created_at: datetime
    updated_at: datetime


# ── Markup schemas ────────────────────────────────────────────────────────────


class MarkupCreate(BaseModel):
    """Create a markup/overhead line on a BOQ."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    markup_type: str = Field(
        default="percentage", pattern=r"^(percentage|fixed|per_unit)$"
    )
    category: str = Field(
        default="overhead",
        pattern=r"^(overhead|profit|tax|contingency|insurance|bond|other)$",
    )
    percentage: float = Field(default=0.0, ge=0.0, le=100.0)
    fixed_amount: float = Field(default=0.0, ge=0.0)
    apply_to: str = Field(
        default="direct_cost", pattern=r"^(direct_cost|subtotal|cumulative)$"
    )
    sort_order: int = Field(default=0, ge=0)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarkupUpdate(BaseModel):
    """Partial update for a BOQ markup."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    markup_type: str | None = Field(
        default=None, pattern=r"^(percentage|fixed|per_unit)$"
    )
    category: str | None = Field(
        default=None,
        pattern=r"^(overhead|profit|tax|contingency|insurance|bond|other)$",
    )
    percentage: float | None = Field(default=None, ge=0.0, le=100.0)
    fixed_amount: float | None = Field(default=None, ge=0.0)
    apply_to: str | None = Field(
        default=None, pattern=r"^(direct_cost|subtotal|cumulative)$"
    )
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


class MarkupResponse(BaseModel):
    """Markup line returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    boq_id: UUID
    name: str
    markup_type: str
    category: str
    percentage: float
    fixed_amount: float
    apply_to: str
    sort_order: int
    is_active: bool
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


class MarkupCalculated(MarkupResponse):
    """Markup response enriched with the computed amount."""

    amount: float = 0.0


# ── Composite schemas ─────────────────────────────────────────────────────────


class BOQWithPositions(BOQResponse):
    """BOQ with all its positions and computed grand total."""

    positions: list[PositionResponse] = Field(default_factory=list)
    grand_total: float = 0.0


class SectionResponse(BaseModel):
    """A BOQ section (header) with its child positions and subtotal."""

    id: UUID
    ordinal: str
    description: str
    positions: list[PositionResponse] = Field(default_factory=list)
    subtotal: float = 0.0


class BOQWithSections(BOQResponse):
    """BOQ with hierarchical sections, positions, subtotals, and markups.

    ``sections`` — grouped positions under section headers.
    ``positions`` — ungrouped positions that have no parent (and are not sections).
    ``direct_cost`` — sum of all position totals (items only, not sections).
    ``markups`` — ordered list of markup lines with computed amounts.
    ``net_total`` — direct_cost + sum of markup amounts.
    ``grand_total`` — alias for net_total (reserved for future tax logic).
    """

    sections: list[SectionResponse] = Field(default_factory=list)
    positions: list[PositionResponse] = Field(default_factory=list)
    direct_cost: float = 0.0
    markups: list[MarkupCalculated] = Field(default_factory=list)
    net_total: float = 0.0
    grand_total: float = 0.0


# ── Template schemas ─────────────────────────────────────────────────────────


class TemplatePositionInfo(BaseModel):
    """Summary of a single template position (used in template listing)."""

    ordinal: str
    description: str
    unit: str
    qty_factor: float
    rate: float


class TemplateSectionInfo(BaseModel):
    """Summary of a single template section (used in template listing)."""

    ordinal: str
    description: str
    position_count: int


class TemplateInfo(BaseModel):
    """Summary of a BOQ template returned by GET /boqs/templates."""

    id: str
    name: str
    description: str
    icon: str
    section_count: int
    position_count: int


class BOQFromTemplateRequest(BaseModel):
    """Request body for creating a BOQ from a template."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    template_id: str = Field(..., min_length=1, max_length=50)
    area_m2: float = Field(..., gt=0.0, description="Gross floor area in m2")
    boq_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Custom BOQ name. Defaults to template name if omitted.",
    )


# ── Activity log schemas ─────────────────────────────────────────────────────


# ── AI Chat schemas ──────────────────────────────────────────────────────────


class AIChatContext(BaseModel):
    """Context about the current BOQ for AI chat prompts."""

    project_name: str = ""
    currency: str = "EUR"
    standard: str = "din276"
    existing_positions_count: int = 0


class AIChatRequest(BaseModel):
    """Request body for AI chat within the BOQ editor."""

    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(..., min_length=1, max_length=2000)
    context: AIChatContext = Field(default_factory=AIChatContext)


class AIChatItem(BaseModel):
    """A single BOQ position suggested by AI chat."""

    ordinal: str
    description: str
    unit: str
    quantity: float
    unit_rate: float
    total: float


class AIChatResponse(BaseModel):
    """Response from AI chat with generated BOQ items."""

    items: list[AIChatItem] = Field(default_factory=list)
    message: str = ""


# ── Activity log schemas ─────────────────────────────────────────────────────


class ActivityLogResponse(BaseModel):
    """Activity log entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID | None
    boq_id: UUID | None
    user_id: UUID
    action: str
    target_type: str
    target_id: UUID | None
    description: str
    changes: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime


class ActivityLogList(BaseModel):
    """Paginated list of activity log entries."""

    items: list[ActivityLogResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50
