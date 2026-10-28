# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic request/response schemas for the Design Options module.

Base request/response shapes for design-option sets and the individual options
inside them. The side-by-side comparison shapes (per-option columns, by-trade
delta rows, the recommendation and the fairness banner) are appended by the
comparison phase at the clearly marked section at the end of this file.

Monetary, quantity and ratio values follow the platform contract: they are
Decimal in Python and stored / sent as plain decimal *strings* so large totals
round-trip without binary-float drift and stay locale-neutral. The option ORM
columns are already strings, so these read schemas type them as ``str`` and no
float ever appears on the wire.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Requests ─────────────────────────────────────────────────────────────────


class DesignOptionSetCreate(BaseModel):
    """Create a new design-option set for a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID = Field(description="Project the option set belongs to.")
    name: str = Field(..., min_length=1, max_length=255, description="Human name for the option set.")
    comparison_currency: str = Field(
        default="",
        max_length=10,
        description=(
            "Optional ISO currency that every option is rebased to for a fair "
            "comparison. Blank uses the project base currency."
        ),
    )


class DesignOptionCreate(BaseModel):
    """Create a new option inside a set (starts empty, in draft status)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255, description="Human name for the option, e.g. 'Steel frame'.")


# ── Responses ────────────────────────────────────────────────────────────────


class DesignOptionResponse(BaseModel):
    """One design option: its references, priced totals and validation state.

    Money, quantity and ratio fields are plain decimal strings (never floats).
    ``breakdown`` is the by-element cost snapshot (RomElementBreakdown shape).
    ``duration_days`` / ``finish_date`` are read off the linked schedule and
    ``embodied_carbon_kg`` / ``carbon_per_m2`` off the linked carbon inventory;
    they stay zero and blank while nothing is linked, which is the difference
    between "this option finishes on day zero" and "nobody has programmed it".
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    set_id: UUID
    project_id: UUID
    name: str = ""
    sort_order: int = 0
    source_document_id: UUID | None = None
    bim_model_id: UUID | None = None
    boq_id: UUID | None = None
    match_session_id: UUID | None = None
    schedule_id: UUID | None = None
    carbon_inventory_id: UUID | None = None
    boq_source: str = ""
    status: str = "draft"
    error: str = ""
    direct_cost: str = "0"
    markups_total: str = "0"
    grand_total: str = "0"
    cost_per_m2: str = "0"
    duration_days: str = "0"
    finish_date: str = ""
    embodied_carbon_kg: str = "0"
    carbon_per_m2: str = "0"
    gfa: str = "0"
    gfa_unit: str = "m2"
    currency: str = ""
    element_count: int = 0
    position_count: int = 0
    breakdown: list = Field(default_factory=list)
    validation_status: str = "pending"
    validation_score: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DesignOptionSetResponse(BaseModel):
    """A design-option set with its options ordered by sort order."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str = ""
    status: str = "draft"
    baseline_option_id: UUID | None = None
    comparison_currency: str = ""
    decision_criteria: dict = Field(default_factory=dict)
    created_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    options: list[DesignOptionResponse] = Field(default_factory=list)


# ── Attach-model + generate shapes (P1: orchestration) ───────────────────────


class AttachModelRequest(BaseModel):
    """Attach a source to an option: link an existing BIM model or a document.

    Exactly one of ``bim_model_id`` or ``source_document_id`` must be provided.
    The heavy CAD upload and conversion stays in the BIM hub (its upload-cad /
    upload / from-document endpoints); this call only records the resulting model
    (or the document to convert) on the option and moves its lifecycle forward, so
    nothing about the conversion pipeline is re-implemented here.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    bim_model_id: UUID | None = Field(
        default=None,
        description="Existing converted BIM model to pair with this option.",
    )
    source_document_id: UUID | None = Field(
        default=None,
        description=(
            "Existing project document (an uploaded CAD/BIM file) to pair with this "
            "option. When the document already has a converted BIM model that model "
            "is adopted; otherwise the document is recorded so the BIM hub can convert "
            "it and the option re-attached to the resulting model."
        ),
    )


class DesignOptionLinkRequest(BaseModel):
    """Point an option at things the project already holds.

    A design option is a whole alternative, so it is not only a model: the
    estimate that prices it, the programme that dates it and the carbon inventory
    that weighs it may all exist in the project already. This links them instead
    of asking anyone to upload or retype what is on the platform.

    Presence, not value, decides what changes. A field left out of the request
    body is left alone; a field sent as ``null`` clears that reference. That
    distinction is read off Pydantic's ``model_fields_set``, so unlinking a
    schedule and leaving one alone are two different requests rather than the
    same one, and a partial update can never silently drop a reference it did not
    mention.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    boq_id: UUID | None = Field(
        default=None,
        description=(
            "Bill of quantities in the same project to price this option from. "
            "Linking one prices the option immediately - no model is required."
        ),
    )
    schedule_id: UUID | None = Field(
        default=None,
        description="Schedule in the same project giving this option its duration and finish date.",
    )
    carbon_inventory_id: UUID | None = Field(
        default=None,
        description="Carbon inventory in the same project giving this option its embodied carbon.",
    )


class DesignOptionGenerateRequest(BaseModel):
    """Generate, or preview, an option's priced BOQ from its attached model.

    ``dry_run`` is the AI-augmented, human-confirmed gate: when true the match runs
    and a full preview is returned but nothing is written to the option's bill of
    quantities. Set it false to apply the confirmed matches and price the option.
    ``auto_confirm_threshold`` decides which AI matches are confident enough to be
    applied without a manual pick.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    dry_run: bool = Field(default=True, description="Preview only; write no positions when true.")
    method: str = Field(
        default="vector",
        max_length=20,
        description="Match method: vector, lexical, resources or llm.",
    )
    catalogue_id: str | None = Field(
        default=None,
        max_length=120,
        description="Optional cost-catalogue region id to price against (blank auto-binds the project default).",
    )
    catalogue_ids: list[str] | None = Field(
        default=None,
        description="Optional ordered list of catalogue regions to rank side by side.",
    )
    auto_confirm_threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Confidence at or above which AI matches are auto-confirmed for apply.",
    )
    max_groups: int = Field(default=200, ge=1, le=200, description="Cap on element groups matched per generate run.")
    top_k: int = Field(default=10, ge=1, le=50, description="Candidate rates fetched per element group.")


class DesignOptionGeneratePreviewLine(BaseModel):
    """One would-be (dry run) or applied BOQ line. Money and quantity are strings."""

    group_key: str = ""
    description: str = ""
    unit: str = ""
    quantity: str = "0"
    unit_rate: str = "0"
    currency: str = ""
    line_total: str = "0"
    section_path: list[str] = Field(default_factory=list)


class DesignOptionGenerateResponse(BaseModel):
    """Result of a generate call: a dry-run preview or an applied pricing.

    Every money, quantity and ratio field is a plain decimal string, never a float.
    On a dry run nothing is persisted and the totals describe the preview; on an
    apply the option's headline totals, cost per m2 and by-trade breakdown are
    persisted and echoed back here.
    """

    option_id: UUID
    dry_run: bool
    boq_id: UUID | None = None
    method: str = "vector"
    status: str = "draft"
    positions_created: int = 0
    element_count: int = 0
    position_count: int = 0
    groups_total: int = 0
    groups_confirmed: int = 0
    direct_cost: str = "0"
    markups_total: str = "0"
    grand_total: str = "0"
    cost_per_m2: str = "0"
    gfa: str = "0"
    gfa_unit: str = "m2"
    currency: str = ""
    is_mixed_currency: bool = False
    breakdown: list = Field(default_factory=list)
    preview: list[DesignOptionGeneratePreviewLine] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DesignOptionBaselineRequest(BaseModel):
    """Mark one option in a set as the baseline every other option's delta is measured against."""

    option_id: UUID = Field(description="Option in this set to use as the baseline.")


# ── comparison shapes appended by comparison phase ───────────────────────────
# The comparison phase appends DesignOptionComparisonResponse, DesignOptionColumn,
# TradeDeltaRow and the recommendation / fairness shapes below this marker.
# Append only; do not rewrite the base shapes above and do not remove this marker.


class DesignOptionColumn(BaseModel):
    """One option rendered as a column in the side-by-side comparison.

    Every option in a set is rebased to the set's single comparison currency, so
    the columns are directly comparable. Money and ratio fields are plain decimal
    strings (never floats). ``delta_vs_baseline`` and ``delta_pct`` are measured
    against the set's baseline option; ``delta_pct`` is ``null`` when there is no
    baseline or the baseline total is zero (no meaningful percentage). A draft
    option that has not been priced yet still appears here with zero totals so the
    full set of options is always visible.

    Beyond cost the column answers the other two questions asked of a design
    alternative, and only from what the option really references. ``duration_days``
    / ``finish_date`` come from the linked schedule and ``embodied_carbon_kg`` /
    ``carbon_per_m2`` from the linked carbon inventory. ``has_programme`` and
    ``has_carbon`` say whether anything is linked at all, because a zero and an
    unanswered question look identical in a number and must not read the same on
    screen. The deltas against the baseline are ``null`` whenever either side of
    the subtraction is unanswered rather than being quietly measured from zero.
    """

    option_id: UUID
    name: str = ""
    direct_cost: str = "0"
    markups_total: str = "0"
    grand_total: str = "0"
    delta_vs_baseline: str = "0"
    delta_pct: str | None = None
    cost_per_m2: str = "0"
    gfa: str = "0"
    currency: str = ""
    element_count: int = 0
    position_count: int = 0
    validation_status: str = "pending"
    boq_source: str = ""
    has_programme: bool = False
    duration_days: str = "0"
    finish_date: str = ""
    delta_days_vs_baseline: str | None = None
    has_carbon: bool = False
    embodied_carbon_kg: str = "0"
    carbon_per_m2: str = "0"
    carbon_unit: str = "kgCO2e"
    delta_carbon_vs_baseline: str | None = None


class TradeDeltaOptionCell(BaseModel):
    """One option's quantity and cost for a single trade row (comparison currency)."""

    option_id: UUID
    quantity: str = "0"
    unit: str = ""
    cost: str = "0"


class TradeDeltaRow(BaseModel):
    """One trade bucket across all options, with the baseline for delta reference.

    A trade is a classification bucket: a DIN 276 cost group, a MasterFormat
    division or a free-form trade tag (``classification_system`` records which).
    ``key`` is stable so the UI localises ``label`` via
    ``t('designOptions.trade.<key>')`` while the backend keeps an honest English
    default. ``baseline_quantity`` / ``baseline_cost`` come from the set's
    baseline option; ``per_option`` carries the same figures for every option so
    the UI can show the per-trade delta. Quantity and cost are decimal strings.
    """

    key: str = ""
    label: str = ""
    classification_system: str = ""
    baseline_quantity: str = "0"
    baseline_cost: str = "0"
    per_option: list[TradeDeltaOptionCell] = Field(default_factory=list)


class DesignOptionRecommendation(BaseModel):
    """The transparently chosen recommended option.

    The rule is deliberately explainable: the option with the lowest normalised
    cost per m2 that is priced and passes the currency fairness checks wins
    (falling back to the lowest grand total when no option carries a cost per m2).
    ``confidence`` is the winner's relative margin over the runner-up (0..1, a
    decimal string), so a clear winner reads high and a near-tie reads low.
    ``reason_key`` is an i18n key naming why it won; ``option_id`` is ``null`` when
    no option can be recommended (none priced).
    """

    option_id: UUID | None = None
    confidence: str = "0"
    reason_key: str = ""


class DesignOptionFairnessWarning(BaseModel):
    """One fairness notice on the comparison as a whole.

    ``key`` is an i18n key (``designOptions.fairness.<name>``); ``severity`` is
    ``info`` / ``warning`` / ``error`` and drives the banner traffic light;
    ``context`` carries interpolation values (e.g. a count or a currency code) for
    the localised message.
    """

    key: str
    severity: str = "warning"
    context: dict = Field(default_factory=dict)


class DesignOptionFairness(BaseModel):
    """Set-level fairness banner: a traffic-light status plus the notices behind it.

    ``status`` is ``ok`` (green), ``warnings`` (amber) or ``error`` (red), derived
    from the highest severity in ``warnings``. The comparison stays honest about
    what would make a straight cost comparison misleading: options not yet priced,
    an option whose own bill mixes currencies, a requested comparison currency that
    could not be applied, a missing or inconsistent gross floor area, or no chosen
    baseline.
    """

    status: str = "ok"
    warnings: list[DesignOptionFairnessWarning] = Field(default_factory=list)


class DesignOptionComparisonResponse(BaseModel):
    """The full side-by-side comparison of the options in a set.

    Confirms one comparison currency for the whole set (``comparison_currency``),
    one column per option, the by-trade delta table, a transparent recommendation
    and the fairness banner. Every monetary, quantity and ratio value nested inside
    is a plain decimal string, so no float ever appears on the wire.
    """

    set_id: UUID
    set_name: str = ""
    comparison_currency: str = ""
    baseline_option_id: UUID | None = None
    options: list[DesignOptionColumn] = Field(default_factory=list)
    by_trade: list[TradeDeltaRow] = Field(default_factory=list)
    recommendation: DesignOptionRecommendation = Field(default_factory=DesignOptionRecommendation)
    fairness: DesignOptionFairness = Field(default_factory=DesignOptionFairness)
