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

    project_id: UUID = Field(..., description="UUID of the parent project")
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="BOQ name (must be at least 1 character)",
        examples=["Detailed Estimate Phase 1"],
    )
    description: str = Field(
        default="",
        description="Optional description of the BOQ scope",
        examples=["Full BOQ for structural and architectural works"],
    )
    estimate_type: str | None = Field(
        default=None,
        max_length=50,
        description="Estimate type (e.g. detailed, budget, order_of_magnitude)",
        examples=["detailed"],
    )
    base_date: str | None = Field(
        default=None,
        max_length=20,
        description="Base date / price level reference (e.g. 2026-Q2)",
        examples=["2026-Q2"],
    )


class BOQUpdate(BaseModel):
    """Partial update for a BOQ."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: str | None = Field(default=None, pattern=r"^(draft|final|archived)$")
    metadata: dict[str, Any] | None = None
    estimate_type: str | None = Field(default=None, max_length=50)
    base_date: str | None = Field(default=None, max_length=20)


class BOQResponse(BaseModel):
    """BOQ returned from the API."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        json_schema_extra={"x-build": "oe-443"},
    )

    id: UUID
    project_id: UUID
    name: str
    description: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # Phase 12.2 lock & revision fields
    base_date: str | None = None
    estimate_type: str | None = None
    is_locked: bool = False
    parent_estimate_id: UUID | None = None
    approved_by: str | None = None
    approved_at: str | None = None


class BOQListItem(BOQResponse):
    """BOQ summary returned from list endpoints, includes computed grand_total."""

    grand_total: float = 0.0
    position_count: int = 0


# ── Position schemas ───────────────────────────────────────────────────────


class PositionCreate(BaseModel):
    """Create a new BOQ position."""

    model_config = ConfigDict(str_strip_whitespace=True)

    boq_id: UUID = Field(..., description="UUID of the parent BOQ")
    parent_id: UUID | None = Field(
        default=None, description="Parent position UUID for hierarchical grouping"
    )
    ordinal: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Position number / ordinal code (e.g. 01.02.003)",
        examples=["01.02.003"],
    )
    description: str = Field(
        default="",
        description="Position description / specification text",
        examples=["Reinforced concrete wall C30/37, 24cm, formwork both sides"],
    )
    unit: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Unit of measurement (m, m2, m3, kg, pcs, lsum, etc.)",
        examples=["m3"],
    )
    quantity: float = Field(
        default=0.0, ge=0.0, description="Measured quantity", examples=[125.5]
    )
    unit_rate: float = Field(
        default=0.0, ge=0.0, description="Price per unit", examples=[285.00]
    )
    classification: dict[str, Any] = Field(
        default_factory=dict,
        description="Classification codes (e.g. din276, nrm, masterformat)",
        examples=[{"din276": "330"}],
    )
    source: str = Field(
        default="manual",
        pattern=r"^(manual|cad_import|ai_takeoff|gaeb_import|excel_import|takeoff|smart_import|smart_import_ai|cad_import_ai)$",
        description="Data source. Must be: manual, cad_import, ai_takeoff, gaeb_import, excel_import, or takeoff",
        examples=["manual"],
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="AI confidence score (0.0-1.0). Only for AI-sourced positions",
    )
    cad_element_ids: list[str] = Field(
        default_factory=list, description="Linked CAD element IDs from canonical format"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")
    wbs_id: str | None = Field(default=None, description="Linked WBS node ID")
    cost_code_id: str | None = Field(default=None, description="Linked cost code ID")


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
    source: str | None = Field(
        default=None,
        pattern=r"^(manual|cad_import|ai_takeoff|gaeb_import|excel_import|takeoff|smart_import|smart_import_ai|cad_import_ai)$",
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    cad_element_ids: list[str] | None = None
    validation_status: str | None = Field(
        default=None,
        pattern=r"^(pending|passed|warnings|errors)$",
    )
    metadata: dict[str, Any] | None = None
    sort_order: int | None = None
    wbs_id: str | None = None
    cost_code_id: str | None = None


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
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    sort_order: int
    created_at: datetime
    updated_at: datetime
    wbs_id: str | None = None
    cost_code_id: str | None = None


# ── Markup schemas ────────────────────────────────────────────────────────────


class MarkupCreate(BaseModel):
    """Create a markup/overhead line on a BOQ."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    markup_type: str = Field(default="percentage", pattern=r"^(percentage|fixed|per_unit)$")
    category: str = Field(
        default="overhead",
        pattern=r"^(overhead|profit|tax|contingency|insurance|bond|other)$",
    )
    percentage: float = Field(default=0.0, ge=0.0, le=100.0)
    fixed_amount: float = Field(default=0.0, ge=0.0)
    apply_to: str = Field(default="direct_cost", pattern=r"^(direct_cost|subtotal|cumulative)$")
    sort_order: int = Field(default=0, ge=0)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarkupUpdate(BaseModel):
    """Partial update for a BOQ markup."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    markup_type: str | None = Field(default=None, pattern=r"^(percentage|fixed|per_unit)$")
    category: str | None = Field(
        default=None,
        pattern=r"^(overhead|profit|tax|contingency|insurance|bond|other)$",
    )
    percentage: float | None = Field(default=None, ge=0.0, le=100.0)
    fixed_amount: float | None = Field(default=None, ge=0.0)
    apply_to: str | None = Field(default=None, pattern=r"^(direct_cost|subtotal|cumulative)$")
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
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
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
    locale: str = Field(default="en", max_length=10)


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
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime


class ActivityLogList(BaseModel):
    """Paginated list of activity log entries."""

    items: list[ActivityLogResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


# ── Snapshot schemas ─────────────────────────────────────────────────────────


class SnapshotCreate(BaseModel):
    """Create a point-in-time snapshot of a BOQ."""

    name: str = ""


class SnapshotResponse(BaseModel):
    """A BOQ snapshot returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    boq_id: UUID
    name: str
    created_at: datetime
    created_by: UUID | None = None


class SnapshotDetail(SnapshotResponse):
    """Full snapshot including data payload."""

    snapshot_data: dict[str, Any] = Field(default_factory=dict)


# ── Sustainability / CO2 schemas ─────────────────────────────────────────────


class CostBreakdownCategory(BaseModel):
    """A single cost category in the breakdown (e.g. material, labor)."""

    type: str
    amount: float
    percentage: float
    item_count: int


class CostBreakdownMarkup(BaseModel):
    """A markup line in the cost breakdown."""

    name: str
    percentage: float
    amount: float


class CostBreakdownResource(BaseModel):
    """A top resource by cost in the breakdown."""

    name: str
    type: str
    total_cost: float
    positions_count: int


class CostBreakdownResponse(BaseModel):
    """Full cost breakdown response for a BOQ."""

    boq_id: str
    grand_total: float
    direct_cost: float
    categories: list[CostBreakdownCategory] = Field(default_factory=list)
    markups: list[CostBreakdownMarkup] = Field(default_factory=list)
    top_resources: list[CostBreakdownResource] = Field(default_factory=list)


# ── Resource Summary schemas ─────────────────────────────────────────────────


class ResourceSummaryItem(BaseModel):
    """A single aggregated resource across all positions in a BOQ."""

    name: str
    type: str
    unit: str
    total_quantity: float
    avg_unit_rate: float
    total_cost: float
    positions_used: int


class ResourceTypeSummary(BaseModel):
    """Summary statistics for a single resource type."""

    count: int
    total_cost: float


class ResourceSummaryResponse(BaseModel):
    """Full resource summary for a BOQ — aggregated across all positions."""

    total_resources: int
    by_type: dict[str, ResourceTypeSummary] = Field(default_factory=dict)
    resources: list[ResourceSummaryItem] = Field(default_factory=list)


class CO2MaterialBreakdown(BaseModel):
    """CO2 breakdown for a single material category."""

    material: str
    category: str = ""
    quantity: float
    unit: str
    co2_kg: float
    percentage: float
    positions_count: int = 0


class PositionCO2Detail(BaseModel):
    """CO2 data for a single BOQ position."""

    position_id: str
    ordinal: str
    description: str
    quantity: float
    unit: str
    epd_id: str | None = None
    epd_name: str | None = None
    gwp_per_unit: float = 0.0
    gwp_total: float = 0.0
    category: str = ""
    source: str = "none"  # "enriched" | "auto-detected" | "none"


class SustainabilityResponse(BaseModel):
    """Sustainability / CO2 analysis result for a BOQ."""

    total_co2_kg: float
    total_co2_tons: float
    breakdown: list[CO2MaterialBreakdown] = Field(default_factory=list)
    benchmark_per_m2: float | None = None
    rating: str = ""
    rating_label: str = ""
    project_area_m2: float | None = None
    positions_analyzed: int = 0
    positions_matched: int = 0
    lifecycle_stages: str = "A1-A3"
    data_quality: str = "estimated"  # "enriched" | "estimated" | "mixed"
    positions_detail: list[PositionCO2Detail] = Field(default_factory=list)
    eu_cpr_compliance: str = ""  # "excellent" | "good" | "acceptable" | "non-compliant" | ""
    eu_cpr_gwp_per_m2_year: float | None = None


class CO2EnrichResponse(BaseModel):
    """Response from the CO2 enrichment endpoint."""

    enriched: int = 0
    skipped: int = 0
    total: int = 0


class CO2AssignRequest(BaseModel):
    """Request to manually assign an EPD material to a position."""

    epd_id: str = Field(..., min_length=1, max_length=100)


# ── AACE Estimate Classification schemas ────────────────────────────────────


class EstimateClassificationMetrics(BaseModel):
    """Raw metrics used to determine the AACE estimate class."""

    total_positions: int = 0
    positions_with_rates: int = 0
    positions_with_resources: int = 0
    positions_with_classification: int = 0
    rate_completeness_pct: float = 0.0
    resource_completeness_pct: float = 0.0
    classification_completeness_pct: float = 0.0


class EstimateClassificationResponse(BaseModel):
    """AACE 18R-97 estimate classification result for a BOQ.

    See AACE International Recommended Practice 18R-97 for the full standard.
    Classes range from 5 (least defined) to 1 (most defined).
    """

    estimate_class: int = Field(..., ge=1, le=5, description="AACE class 1-5")
    class_label: str = Field(default="", description="Human-readable label (e.g. 'Screening')")
    accuracy_low: str = Field(default="", description="Lower accuracy bound (e.g. '-50%')")
    accuracy_high: str = Field(default="", description="Upper accuracy bound (e.g. '+100%')")
    definition_level_low: int = Field(default=0, ge=0, le=100, description="Lower definition level %")
    definition_level_high: int = Field(default=0, ge=0, le=100, description="Upper definition level %")
    methodology: str = Field(default="", description="Typical estimation methodology for this class")
    metrics: EstimateClassificationMetrics = Field(default_factory=EstimateClassificationMetrics)


# ── Sensitivity Analysis schemas ────────────────────────────────────────────


class SensitivityItem(BaseModel):
    """A single item in the sensitivity / tornado chart analysis."""

    ordinal: str
    description: str
    total: float
    share_pct: float
    impact_low: float
    impact_high: float


class SensitivityResponse(BaseModel):
    """Sensitivity analysis (tornado chart) result for a BOQ.

    Shows which positions have the biggest impact on the total cost when
    their cost varies by ``variation_pct`` percent.
    """

    base_total: float
    variation_pct: float = 10.0
    items: list[SensitivityItem] = Field(default_factory=list)


# ── Monte Carlo Cost Risk Analysis schemas ────────────────────────────────


class CostRiskHistogramBin(BaseModel):
    """A single bin in the Monte Carlo histogram."""

    bin_start: float
    bin_end: float
    count: int


class CostRiskDriver(BaseModel):
    """A position contributing to total cost variance in Monte Carlo simulation."""

    ordinal: str
    description: str
    contribution_pct: float


class CostRiskPercentiles(BaseModel):
    """Percentile values from the Monte Carlo simulation."""

    p10: float
    p25: float
    p50: float
    p75: float
    p80: float
    p90: float


class CostRiskResponse(BaseModel):
    """Monte Carlo cost risk simulation result for a BOQ.

    Runs N iterations of PERT-distributed cost sampling per position,
    collects total costs, and returns percentiles, histogram, contingency,
    and risk drivers (positions contributing most to variance).
    """

    iterations: int
    base_total: float
    percentiles: CostRiskPercentiles
    contingency_p80: float
    contingency_pct: float
    recommended_budget: float
    histogram: list[CostRiskHistogramBin] = Field(default_factory=list)
    risk_drivers: list[CostRiskDriver] = Field(default_factory=list)


# ── AI Classification schemas ─────────────────────────────────────────────


class ClassifyRequest(BaseModel):
    """Request body for AI-powered classification code suggestion."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(..., min_length=1, max_length=1000)
    unit: str = ""
    project_standard: str = Field(default="din276", pattern=r"^(din276|nrm|masterformat)$")


class ClassificationSuggestion(BaseModel):
    """A single classification code suggestion with confidence score."""

    standard: str
    code: str
    label: str
    confidence: float = Field(ge=0.0, le=1.0)


class ClassifyResponse(BaseModel):
    """Response containing ranked classification code suggestions."""

    suggestions: list[ClassificationSuggestion] = Field(default_factory=list)


# ── CAD Element Classification schemas ─────────────────────────────────────


class CADElementInput(BaseModel):
    """A single CAD/BIM element for classification mapping."""

    id: str | None = None
    category: str = Field(..., min_length=1, max_length=255)
    classification: dict[str, str] = Field(default_factory=dict)


class ClassifyElementsRequest(BaseModel):
    """Request body for deterministic CAD element classification mapping.

    Takes a list of CAD elements (with Revit/IFC categories) and maps them
    to the requested construction classification standard using lookup tables.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    elements: list[CADElementInput] = Field(..., min_length=1, max_length=10000)
    standard: str = Field(default="din276", pattern=r"^(din276|nrm|masterformat)$")


class ClassifiedElement(BaseModel):
    """A CAD element with classification codes added."""

    id: str | None = None
    category: str
    classification: dict[str, str] = Field(default_factory=dict)
    mapped: bool = False


class ClassifyElementsResponse(BaseModel):
    """Response for CAD element classification mapping."""

    elements: list[ClassifiedElement] = Field(default_factory=list)
    standard: str
    total: int = 0
    mapped_count: int = 0
    unmapped_count: int = 0


# ── AI Rate Suggestion schemas ─────────────────────────────────────────────


class SuggestRateRequest(BaseModel):
    """Request body for AI-powered market rate suggestion."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(..., min_length=1, max_length=1000)
    unit: str = ""
    classification: dict[str, Any] = Field(default_factory=dict)
    region: str | None = None


class RateMatch(BaseModel):
    """A single rate match from vector search results."""

    code: str
    description: str
    rate: float
    region: str
    score: float


class SuggestRateResponse(BaseModel):
    """Response containing a suggested market rate with supporting matches."""

    suggested_rate: float
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = "vector_search"
    matches: list[RateMatch] = Field(default_factory=list)


# ── Anomaly Detection schemas ──────────────────────────────────────────────


class PricingAnomaly(BaseModel):
    """A pricing anomaly detected in a BOQ position."""

    position_id: str
    field: str = "unit_rate"
    current_value: float
    market_range: dict[str, float] = Field(
        default_factory=dict,
        description="Market rate percentiles: p25, median, p75",
    )
    severity: str = Field(pattern=r"^(warning|error)$")
    message: str
    suggestion: float


class AnomalyCheckResponse(BaseModel):
    """Response from a BOQ pricing anomaly check."""

    anomalies: list[PricingAnomaly] = Field(default_factory=list)
    positions_checked: int = 0


# ── AI Cost Finder (vector search) ──────────────────────────────────────────


class CostItemSearchRequest(BaseModel):
    """Request body for AI-powered cost item search."""

    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(..., min_length=1, max_length=500)
    unit: str | None = Field(default=None, max_length=20)
    region: str | None = Field(default=None, max_length=50)
    limit: int = Field(default=15, ge=1, le=30)
    min_score: float = Field(default=0.3, ge=0.0, le=1.0)


class CostItemSearchResult(BaseModel):
    """A single cost item result from vector search."""

    id: str
    code: str
    description: str
    unit: str
    rate: float
    region: str
    score: float = Field(ge=0.0, le=1.0)
    classification: dict[str, str] = Field(default_factory=dict)
    components: list[dict[str, Any]] = Field(default_factory=list)
    currency: str = "EUR"


class CostItemSearchResponse(BaseModel):
    """Response from AI cost item search."""

    results: list[CostItemSearchResult] = Field(default_factory=list)
    total_found: int = 0
    query_embedding_ms: float = 0.0
    search_ms: float = 0.0


# ── LLM-powered AI features ─────────────────────────────────────────────────


class EnhanceDescriptionRequest(BaseModel):
    """Request to enhance a BOQ position description via LLM."""

    description: str = Field(..., min_length=2, max_length=500)
    unit: str = "m2"
    classification: dict[str, str] = Field(default_factory=dict)
    locale: str = Field(default="en", max_length=10)


class EnhanceDescriptionResponse(BaseModel):
    """Enhanced description with specs and standards."""

    enhanced_description: str
    specifications: list[str] = Field(default_factory=list)
    standards: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    model_used: str = ""
    tokens_used: int = 0


class SuggestPrerequisitesRequest(BaseModel):
    """Request to suggest prerequisite/related positions."""

    description: str = Field(..., min_length=2, max_length=500)
    unit: str = "m2"
    classification: dict[str, str] = Field(default_factory=dict)
    existing_descriptions: list[str] = Field(default_factory=list)
    locale: str = Field(default="en", max_length=10)


class PrerequisiteItem(BaseModel):
    """A single suggested prerequisite/companion position."""

    description: str
    unit: str
    typical_rate_eur: float = 0.0
    relationship: str = "companion"  # prerequisite | companion | successor
    reason: str = ""


class SuggestPrerequisitesResponse(BaseModel):
    """List of suggested prerequisite positions."""

    suggestions: list[PrerequisiteItem] = Field(default_factory=list)
    model_used: str = ""
    tokens_used: int = 0


class CheckScopeRequest(BaseModel):
    """Request to check BOQ scope completeness."""

    project_type: str = "general"  # residential, commercial, industrial, infrastructure
    region: str = "DACH"
    currency: str = "EUR"
    locale: str = Field(default="en", max_length=10)


class ScopeMissingItem(BaseModel):
    """A single missing scope item."""

    description: str
    category: str = ""
    priority: str = "medium"  # high | medium | low
    reason: str = ""
    estimated_rate: float = 0.0
    unit: str = "lsum"


class CheckScopeResponse(BaseModel):
    """Scope completeness analysis result."""

    completeness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    missing_items: list[ScopeMissingItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: str = ""
    model_used: str = ""
    tokens_used: int = 0


class BOQStatisticsResponse(BaseModel):
    """Aggregated statistics for a BOQ."""

    boq_id: str
    boq_name: str
    status: str
    position_count: int = 0
    section_count: int = 0
    direct_cost: float = 0.0
    grand_total: float = 0.0
    avg_unit_rate: float = 0.0
    completion_pct: float = Field(
        default=0.0,
        description="Percentage of positions with both quantity > 0 and unit_rate > 0",
    )
    unit_breakdown: dict[str, int] = Field(
        default_factory=dict,
        description="Count of positions per unit type (m2, m3, kg, etc.)",
    )
    source_breakdown: dict[str, int] = Field(
        default_factory=dict,
        description="Count of positions per source (manual, template, gaeb_import, etc.)",
    )
    classification_coverage_pct: float = Field(
        default=0.0,
        description="Percentage of positions with at least one classification code",
    )
    created_at: datetime
    updated_at: datetime


class EscalateRateRequest(BaseModel):
    """Request to escalate a rate to current prices."""

    description: str = Field(..., min_length=2, max_length=500)
    unit: str = "m2"
    rate: float = Field(..., gt=0)
    currency: str = "EUR"
    base_year: int = Field(default=2023, ge=2000, le=2030)
    target_year: int = Field(default=2026, ge=2000, le=2035)
    region: str = "DACH"
    locale: str = Field(default="en", max_length=10)


class EscalationFactors(BaseModel):
    """Breakdown of escalation factors."""

    material_inflation: float = 0.0
    labor_cost_change: float = 0.0
    regional_adjustment: float = 0.0


class EscalateRateResponse(BaseModel):
    """Rate escalation result."""

    original_rate: float
    escalated_rate: float
    escalation_percent: float
    factors: EscalationFactors = Field(default_factory=EscalationFactors)
    confidence: str = "medium"  # high | medium | low
    reasoning: str = ""
    model_used: str = ""
    tokens_used: int = 0
