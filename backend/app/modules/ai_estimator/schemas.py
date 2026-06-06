# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic schemas for the AI Estimate Builder REST API.

Conventions mirror ``app.modules.match_elements.schemas``:

* Money is accepted/held as ``Decimal`` and emitted as a plain decimal
  *string* in JSON via ``_serialise_money`` (float drops precision and
  colours numbers by locale).
* Confidence is a real model/retrieval-derived float in ``[0, 1]`` or
  ``None`` - never a fabricated placeholder.
* Currencies are never blended: totals carry per-currency subtotals.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


# ── Money serialisation helper (mirrors match_elements / boq) ─────────────
def _serialise_money(v: Decimal | None) -> str | None:
    if v is None:
        return None
    if not isinstance(v, Decimal):
        try:
            v = Decimal(str(v))
        except (InvalidOperation, ValueError):
            return "0"
    if not v.is_finite():
        return "0"
    return format(v, "f")


# ── Enumerations ──────────────────────────────────────────────────────────

# The source kinds the run can ingest.
SourceKind = Literal[
    "text",
    "excel",
    "gaeb",
    "bim",
    "dwg",
    "pdf",
    "photo",
    "documents",
    # An existing artifact already in the system, referenced by id:
    "takeoff",  # measured items from PDF + DWG takeoff
    "boq",  # existing BOQ positions (re-estimate flow)
]

# Run FSM status.
RunStatus = Literal[
    "draft",
    # The conversational intake (v2) runs in front of the analyze stage. The
    # status column is a free String(24) so this is a value-only addition - no
    # enum DB migration is needed (mirrors Position.source being a free string).
    "intake",
    "analyzing",
    "grouping",
    "matching",
    "review",
    "applied",
    "failed",
    "cancelled",
]

# The intake (v2) dialogue phases (see service._INTAKE_PHASES).
IntakePhase = Literal[
    "collect_request",
    "extract",
    "clarify_round_1",
    "clarify_round_2",
    "clarify_round_3",
    "parameter_sheet",
    "compose_groups",
    "group_board",
    "done",
]

# How the dialogue is driven: AI-phrased conversation vs the curated form.
IntakeMode = Literal["ai", "offline"]

# A composed package's grounding coverage from the live vector probe.
CoverageBand = Literal["grounded", "weak", "gap"]

# The four pipeline stages (the wizard steps).
StageName = Literal["source", "grouping", "matching", "assembly"]

# Per-group lifecycle status.
GroupStatus = Literal[
    "unmatched",
    "suggested",
    "confirmed",
    "overridden",
    "skipped",
    "tbd",
    "needs_human",
    "applied",
]

ConfidenceBand = Literal["high", "medium", "low", "none"]

# The per-match-call group cap: how many groups one match-all pass processes
# when the caller does not override ``max_groups``. Single source of truth -
# the ``RunMatchRequest`` default, the service's selection logic and the
# ``/meta`` endpoint all read this one definition.
DEFAULT_MATCH_GROUP_CAP = 25

# The 12 OmniClass-aligned construction stages (match-elements parity).
ConstructionStage = Literal[
    "02_Demolition",
    "03_Earthwork",
    "04_Foundations",
    "05_Substructure",
    "06_Superstructure",
    "07_Envelope",
    "08_Interior",
    "09_MEP",
    "10_Finishes",
    "11_FixedFurnishings",
    "12_Equipment",
    "13_Sitework",
]

# The closed set of valid construction-stage values, derived from the Literal so
# the enum is defined exactly once. Used as the single source of truth for both
# the ``/meta`` endpoint payload and the run/group construction_stage validator.
CONSTRUCTION_STAGES: tuple[str, ...] = get_args(ConstructionStage)


# ── Run create / list / read ──────────────────────────────────────────────


class RunCreate(BaseModel):
    """Create a run and kick off stage 1 (source understanding).

    Exactly one of the source-bearing fields is read according to ``source``:
    ``text`` -> ``text_input``; ``excel`` / ``gaeb`` / ``pdf`` -> ``file_refs``
    (already-uploaded refs) or ``rows`` (pre-parsed); ``bim`` -> ``bim_model_ids``;
    ``documents`` -> ``document_ids``; ``photo`` -> ``file_refs``;
    ``takeoff`` -> measured items of the project (no id needed); ``boq`` ->
    ``boq_ids`` (re-estimate existing positions; empty = all BOQs in project).
    """

    project_id: uuid.UUID
    name: str | None = None
    source: SourceKind = "text"
    # The user-selected agent slug driving stage-3 reasoning. None = the
    # deterministic (no-agent) fallback path. Default resolves to the user's
    # preferred agent server-side.
    agent_name: str | None = None

    # Source payloads (read per ``source``).
    text_input: str | None = None
    file_refs: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    bim_model_ids: list[uuid.UUID] = Field(default_factory=list)
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    # Existing BOQ ids to re-estimate (empty = every BOQ in the project).
    boq_ids: list[uuid.UUID] = Field(default_factory=list)

    # Optional config hints; when omitted the AI suggests them at checkpoint #1.
    catalogue_id: str | None = None
    region: str | None = None
    currency: str | None = None
    construction_stage: ConstructionStage | None = None


class StageState(BaseModel):
    """One stage entry in the run stepper."""

    stage: StageName
    title: str
    status: Literal["pending", "active", "complete", "error"]
    accepted_at: datetime | None = None


class RunRead(BaseModel):
    """Full run state for the wizard."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    name: str | None = None
    agent_name: str | None = None
    status: RunStatus
    current_stage: StageName
    checkpoints: dict[str, Any] = Field(default_factory=dict)
    source_inputs: dict[str, Any] = Field(default_factory=dict)
    detected_source: dict[str, Any] = Field(default_factory=dict)
    suggested_config: dict[str, Any] = Field(default_factory=dict)
    catalogue_id: str | None = None
    region: str | None = None
    currency: str | None = None
    group_by: list[str] = Field(default_factory=list)
    construction_stage: ConstructionStage | None = None
    provider: str | None = None
    model_used: str | None = None
    total_tokens: int = 0
    cost_usd_estimate: float = 0.0
    duration_ms: int = 0
    validation_report: dict[str, Any] | None = None
    # Decimal-as-string in JSON.
    grand_total: Decimal | None = None
    currency_subtotals: dict[str, str] = Field(default_factory=dict)
    completeness_score: float | None = None
    boq_id: uuid.UUID | None = None
    failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("grand_total", when_used="json")
    def _ser_grand_total(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class RunSummary(BaseModel):
    """Compact run row for the run list / resume picker."""

    id: uuid.UUID
    project_id: uuid.UUID
    name: str | None
    source: SourceKind | None = None
    status: RunStatus
    current_stage: StageName
    group_count: int = 0
    confirmed_count: int = 0
    applied_count: int = 0
    model_used: str | None = None
    grand_total: Decimal | None = None
    currency: str | None = None
    # The applied BOQ id (null until the run is applied); mirrors the detail
    # endpoint so the list can deep-link a finished run to its BOQ.
    boq_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("grand_total", when_used="json")
    def _ser_grand_total(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class RunListResponse(BaseModel):
    total: int
    runs: list[RunSummary] = Field(default_factory=list)


# ── Source attach + analyze ───────────────────────────────────────────────


class AddSourcesRequest(BaseModel):
    """Attach additional sources to a draft run before analysis.

    Same payload shape as :class:`RunCreate` source fields; the service
    coalesces them with whatever the run was created with.
    """

    source: SourceKind
    text_input: str | None = None
    file_refs: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    bim_model_ids: list[uuid.UUID] = Field(default_factory=list)
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    boq_ids: list[uuid.UUID] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    """Run stage 1 - normalise sources to envelopes + AI classification.

    ``use_ai`` lets the caller force the deterministic path even when a key is
    present (useful for tests / cost control). When no key is configured the
    run silently degrades regardless of this flag.
    """

    use_ai: bool = True


# ── Stage confirm (the four human-confirm checkpoints) ────────────────────


class StageConfirmRequest(BaseModel):
    """Accept a checkpoint, optionally editing the stage's outputs.

    Stage ``source``: ``edits`` may carry ``catalogue_id`` / ``region`` /
    ``currency`` / ``group_by`` / ``construction_stage`` overriding the
    AI-suggested config before grouping. Other stages accept the checkpoint
    as-is (group / match edits go through the dedicated group endpoints).
    """

    stage: StageName
    edits: dict[str, Any] = Field(default_factory=dict)

    @field_validator("edits")
    @classmethod
    def _validate_edits_construction_stage(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Reject an unknown ``construction_stage`` in the free-form edits.

        ``edits`` is an open dict (it carries several optional config overrides),
        so ``construction_stage`` arrives untyped here. The taxonomy defines a
        closed enum; validate against it (allowing null / absent) so a typo never
        silently lands an unrenderable stage on the run - returning a clear 422.
        """
        if not isinstance(v, dict) or "construction_stage" not in v:
            return v
        stage = v["construction_stage"]
        if stage is None or stage in CONSTRUCTION_STAGES:
            return v
        raise ValueError(f"construction_stage must be one of {list(CONSTRUCTION_STAGES)} or null, got {stage!r}")


# ── Groups (stage 2 + 3) ──────────────────────────────────────────────────


class CandidateOut(BaseModel):
    """One ranked rate candidate (grounded - always from the cost DB)."""

    candidate_id: str | None = None
    code: str = ""
    description: str = ""
    unit: str = ""
    # Decimal-as-string in JSON.
    unit_rate: Decimal = Decimal("0")
    currency: str = ""
    score: float = 0.0
    confidence_band: ConfidenceBand = "low"
    # Set by the multi-pass mapping's rate-sanity pass when this candidate's
    # per-base-unit rate sits outside the per-run benchmark band. The rate is
    # never altered; this only flags it for human review in the override UI.
    rate_outlier: bool = False

    @field_serializer("unit_rate", when_used="json")
    def _ser_unit_rate(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class ResourceOut(BaseModel):
    """One resource sub-row of a chosen candidate's breakdown."""

    name: str = ""
    code: str = ""
    unit: str = ""
    # factor per unit of the parent position (ratio, not currency).
    factor: float = 0.0
    quantity: float = 0.0
    # Decimal-as-string in JSON.
    unit_rate: Decimal = Decimal("0")
    # labor | material | equipment | operator | electricity | other
    type: str = "other"

    @field_serializer("unit_rate", when_used="json")
    def _ser_unit_rate(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class GroupSummary(BaseModel):
    """One row in the groups grid (stage 2/3 review)."""

    id: uuid.UUID
    group_key: str
    description: str | None = None
    trade: str | None = None
    signature: str | None = None
    element_count: int = 0
    quantities: dict[str, float] = Field(default_factory=dict)
    chosen_unit: str | None = None
    primary_quantity: float = 0.0
    # Chosen grounded rate (None until matched).
    chosen_code: str | None = None
    unit_rate: Decimal | None = None
    currency: str | None = None
    score: float | None = None
    confidence: float | None = None
    confidence_band: ConfidenceBand = "none"
    match_method: str | None = None
    status: GroupStatus
    boq_position_id: uuid.UUID | None = None
    sort_order: int = 0

    @field_serializer("unit_rate", when_used="json")
    def _ser_unit_rate(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class GroupDetail(GroupSummary):
    """Full detail for the per-group slide-over / match-review card.

    The WorkGroup provenance fields (design section 3.1) are surfaced read-only
    from the group ``metadata_``: ``source`` (how the group originated),
    ``derivation`` (a short human formula sentence), ``assumptions`` (the
    proxies applied) and ``mapping_trace`` (the multi-pass mapping log the
    matcher writes). They are display-only; the UI never writes them back.
    """

    run_id: uuid.UUID
    element_ids: list[str] = Field(default_factory=list)
    envelope: dict[str, Any] = Field(default_factory=dict)
    resources: list[ResourceOut] = Field(default_factory=list)
    candidates: list[CandidateOut] = Field(default_factory=list)
    confirmed_by: uuid.UUID | None = None
    confirmed_at: datetime | None = None
    notes: str | None = None
    # WorkGroup provenance (read-only, from metadata_).
    source: str | None = None
    derivation: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    mapping_trace: dict[str, Any] | None = None


class GroupListResponse(BaseModel):
    run_id: uuid.UUID
    total: int
    groups: list[GroupSummary] = Field(default_factory=list)
    # {"unmatched": 47, "suggested": 12, "confirmed": 5, ...}
    summary: dict[str, int] = Field(default_factory=dict)
    # Confidence-band thresholds the matchers use, exposed so the UI never
    # replicates the magic numbers.
    confidence_high_threshold: float
    confidence_medium_threshold: float


class GroupUpdate(BaseModel):
    """Edit a group at stage 2 (quantities/unit) or override at stage 3.

    Stage 2: ``chosen_unit`` / ``description`` / ``quantities`` edits.
    Stage 3 override: pass ``candidate_id`` to pick a different real candidate
    from ``candidates`` (the LLM never fabricates a code, and neither can the
    user here - the id must already exist in the candidate list), or
    ``status='skipped'`` to drop the group.
    """

    chosen_unit: str | None = None
    description: str | None = None
    quantities: dict[str, float] | None = None
    candidate_id: str | None = None
    status: GroupStatus | None = None
    notes: str | None = None


class GroupMergeRequest(BaseModel):
    """Merge a set of groups into one at stage 2."""

    group_ids: list[uuid.UUID]
    new_description: str | None = None


class GroupSplitRequest(BaseModel):
    """Split a subset of elements out of a group into a new group at stage 2."""

    element_ids: list[str]
    new_description: str | None = None


# ── Matching (stage 3) ────────────────────────────────────────────────────


class RunMatchRequest(BaseModel):
    """Run stage 3 - find a grounded rate per group.

    Caps how many groups a single pass processes (vector search over hundreds
    of groups blocks the UI). When ``group_ids`` is omitted the service picks
    the N largest groups by element count.
    """

    group_ids: list[uuid.UUID] | None = None
    top_k: int = Field(default=10, ge=1, le=50)
    use_reranker: bool = True
    # Force the deterministic top-1 path even with a key configured.
    use_agent: bool = True
    max_groups: int = Field(default=DEFAULT_MATCH_GROUP_CAP, ge=1, le=500)


class ConfirmGroupRequest(BaseModel):
    """Confirm a single group's chosen candidate as the human decision."""

    candidate_id: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class BulkConfirmRequest(BaseModel):
    """Confirm every suggested group at or above ``threshold`` confidence."""

    threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    group_ids: list[uuid.UUID] | None = None  # None = all suggested


class BulkConfirmResponse(BaseModel):
    confirmed: int
    skipped: int
    group_ids: list[uuid.UUID] = Field(default_factory=list)


# ── Assembly preview (stage 4) ────────────────────────────────────────────


class PreviewResourceRow(BaseModel):
    description: str
    factor: float  # ratio per parent unit, not currency
    quantity: float  # factor x parent quantity, measurement
    unit: str
    unit_rate: Decimal = Decimal("0")
    type: str = "other"

    @field_serializer("unit_rate", when_used="json")
    def _ser_unit_rate(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class PreviewPositionRow(BaseModel):
    """One proposed BOQ position - confirmed:False until apply."""

    group_id: uuid.UUID
    group_key: str
    section_path: list[str] = Field(default_factory=list)
    description: str
    unit: str
    quantity: float  # measurement, not money
    unit_rate: Decimal = Decimal("0")
    currency: str
    line_total: Decimal = Decimal("0")
    confidence: float | None = None
    confidence_band: ConfidenceBand = "none"
    resources: list[PreviewResourceRow] = Field(default_factory=list)
    confirmed: bool = False

    @field_serializer("unit_rate", "line_total", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class ValidationResultOut(BaseModel):
    rule_id: str
    status: Literal["pass", "warning", "error"]
    severity: Literal["error", "warning", "info"]
    message: str
    element_ref: str | None = None


class ValidationReportOut(BaseModel):
    status: Literal["passed", "warnings", "errors", "skipped"]
    score: float | None = None  # None when skipped, NOT 1.0
    rule_set: str = ""
    passed: list[ValidationResultOut] = Field(default_factory=list)
    warnings: list[ValidationResultOut] = Field(default_factory=list)
    errors: list[ValidationResultOut] = Field(default_factory=list)


class PreviewResponse(BaseModel):
    """The assembled-estimate preview - NOT yet written to the BOQ."""

    run_id: uuid.UUID
    positions: list[PreviewPositionRow] = Field(default_factory=list)
    grand_total: Decimal = Decimal("0")
    currency: str | None = None
    # Per-currency subtotals so currencies are never blended.
    currency_subtotals: dict[str, str] = Field(default_factory=dict)
    validation: ValidationReportOut | None = None
    completeness_score: float | None = None
    missing_items: list[str] = Field(default_factory=list)
    # True only when every position passes (no ERROR-severity rule) so the UI
    # can gate the apply button.
    can_apply: bool = False

    @field_serializer("grand_total", when_used="json")
    def _ser_grand_total(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Apply (stage 4 write) ─────────────────────────────────────────────────


class ApplyRequest(BaseModel):
    """Write the assembled estimate to a BOQ. Never auto-applies."""

    # None = create a new BOQ on the project; set = append to an existing one.
    target_boq_id: uuid.UUID | None = None
    boq_name: str | None = None
    append: bool = False
    organize_by_classification: bool = True
    # Only confirmed groups are written; pass to restrict further.
    group_ids: list[uuid.UUID] | None = None


class ApplyResponse(BaseModel):
    run_id: uuid.UUID
    boq_id: uuid.UUID
    positions_created: int
    grand_total: Decimal = Decimal("0")
    currency: str | None = None
    currency_subtotals: dict[str, str] = Field(default_factory=dict)

    @field_serializer("grand_total", when_used="json")
    def _ser_grand_total(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Progress (poll) ───────────────────────────────────────────────────────


class StepOut(BaseModel):
    """One entry in the run timeline."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    stage: StageName
    step_idx: int
    role: Literal["thought", "tool_call", "observation", "answer", "error", "stage_complete"]
    content: dict[str, Any] | list[Any] | str | None = None
    token_count: int = 0
    took_ms: int | None = None
    created_at: datetime


class ProgressResponse(BaseModel):
    """Poll target - run status + stepper + recent timeline.

    The frontend polls this on an interval while a stage runs (no streaming -
    ``call_ai`` returns full text).
    """

    run_id: uuid.UUID
    status: RunStatus
    current_stage: StageName
    stages: list[StageState] = Field(default_factory=list)
    # Counts so the UI can show "12 of 60 groups matched" without listing.
    group_count: int = 0
    matched_count: int = 0
    confirmed_count: int = 0
    failure_reason: str | None = None
    # AI connection status banner: ai_connected, vector_ready (>100 vectors),
    # degraded_reason ("no_ai_key" | "no_vectors" | "no_catalogue" | None).
    ai_connected: bool = False
    vector_ready: bool = False
    degraded_reason: str | None = None
    provider: str | None = None
    model_used: str | None = None
    # The most-recent N timeline steps (full history via GET /runs/{id}/steps).
    recent_steps: list[StepOut] = Field(default_factory=list)


class ReadinessResponse(BaseModel):
    """Pre-flight check surfaced before the user starts a run.

    Honest about graceful degradation: a run still works with no AI key or no
    vectors, but the UI explains what the user gives up and links to settings.
    """

    ai_connected: bool = False
    provider: str | None = None
    model_used: str | None = None
    vector_ready: bool = False
    vector_count: int = 0
    catalogues_available: int = 0
    # Plain-prose guidance when something is missing (re-enter key, etc.).
    message: str | None = None


# ── Catalogues (reuse of cwicr_v3_catalogue registry) ─────────────────────


class CatalogueOption(BaseModel):
    """One selectable CWICR v3 region in the source-config step."""

    id: str
    label: str
    currency: str
    region: str | None = None
    default_classification_standard: str | None = None


# ── Meta (UI-facing constants contract) ───────────────────────────────────


class ScoreThresholds(BaseModel):
    """The confidence-band cutoffs the matchers use, surfaced for the UI."""

    high: float
    low: float


class MetaResponse(BaseModel):
    """Module constants the frontend reads instead of hardcoding magic numbers.

    Every value is sourced from the single existing definition in the module
    (no duplication): the confidence thresholds from the service, the stage set
    from the ``ConstructionStage`` Literal, the group cap from
    ``DEFAULT_MATCH_GROUP_CAP``.
    """

    score_thresholds: ScoreThresholds
    construction_stages: list[str] = Field(default_factory=list)
    match_group_cap: int
    # The rate-sanity band factor (decision 2 of the v3 design): a mapping
    # candidate whose per-base-unit rate is more than this multiple away from
    # the per-run catalogue median for its (trade, unit) is flagged a low-
    # confidence outlier for human review. Never replaces a real DB rate.
    rate_sanity_band_factor: float


# ── Intake v2 (conversational intake in front of stage 1) ──────────────────


class IntakeQuestionOption(BaseModel):
    """One selectable option for a ``choice`` parameter question."""

    value: str
    # i18n key (``aiest.choice.<value>``); the UI falls back to ``value``.
    label_key: str


class IntakeQuestion(BaseModel):
    """One question in the current clarification round.

    ``prompt`` is the human question text (LLM-phrased on the AI path, or the
    curated i18n-keyed default on the offline path). ``why`` is the
    "unlocks" justification (an i18n key plus the formula ids it feeds) so the
    UI can always show the payoff of answering. ``current_value`` is prefilled
    when the value is already known from the free text.
    """

    param_key: str
    kind: Literal["number", "choice", "bool", "length"]
    unit: str | None = None
    required: bool = False
    options: list[IntakeQuestionOption] = Field(default_factory=list)
    prompt: str
    why: str
    current_value: Any | None = None


class ComposedPackage(BaseModel):
    """One work package on the editable group board (after compose_groups).

    ``coverage`` and ``best_score`` are the REAL live-probe result (never a
    placeholder): ``grounded`` (green) when the best probe scored >= MEDIUM,
    ``weak`` (amber) below MEDIUM but above the LOW floor, ``gap`` (red) when no
    phrasing returned a usable candidate. A gap package is still created so the
    user can edit or add a manual rate - the board never silently drops work.
    """

    package_key: str
    trade: str
    selected: bool = True
    stages: list[str] = Field(default_factory=list)
    group_ids: list[uuid.UUID] = Field(default_factory=list)
    coverage: CoverageBand = "gap"
    best_score: float | None = None
    quantity: float = 0.0
    unit: str = "pcs"
    # True when any quantity was derived from a proxy (estimated, editable).
    estimated: bool = False


class IntakeState(BaseModel):
    """The full intake dialogue state (the poll + step responses)."""

    run_id: uuid.UUID
    mode: IntakeMode
    phase: IntakePhase
    round_idx: int = 0
    rounds_remaining: int = 3
    detected_type: str | None = None
    # Real type-detection confidence or null (null on the deterministic path).
    type_confidence: float | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    # The current round's question batch (empty when off-round).
    questions: list[IntakeQuestion] = Field(default_factory=list)
    # Populated from compose_groups onward.
    packages: list[ComposedPackage] = Field(default_factory=list)
    # Advisory foreman-sequence warnings for the selected package set (never
    # blocking): each names a successor package selected without a prerequisite
    # (e.g. tiling with no plaster substrate). Empty off-board. See
    # project_types.dependency_warnings.
    dependency_warnings: list[dict[str, str]] = Field(default_factory=list)
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    ai_connected: bool = False
    vector_ready: bool = False
    # "no_ai_key" | "no_vectors" | "no_catalogue" | None.
    degraded_reason: str | None = None
    summary: str | None = None


# ── Intake request bodies ──────────────────────────────────────────────────


class IntakeCreate(BaseModel):
    """Start a conversational intake from a free-text request.

    Creates a run in status ``intake`` plus an intake row, runs ``extract`` and
    returns the first :class:`IntakeState`. Grouping does NOT run yet.
    """

    project_id: uuid.UUID
    text: str = Field(default="", max_length=4000)
    name: str | None = None
    # "ai" | "offline" | None - force a mode (tests / cost control). None lets
    # the service pick AI when a key is present, else offline.
    mode_hint: IntakeMode | None = None
    # Optional manual project-type pick when the user chose a tile instead of /
    # in addition to free text.
    project_type: str | None = None
    # Optional config the user pre-selected (catalogue / region / currency).
    catalogue_id: str | None = None
    region: str | None = None
    currency: str | None = None


class IntakeAnswerRequest(BaseModel):
    """Record answers for the current round and (optionally) advance."""

    answers: dict[str, Any] = Field(default_factory=dict)
    # When true, compute the next phase (next round, or parameter_sheet when
    # ready / the round cap is hit). When false, just persist the answers.
    advance: bool = True
    # Optional change of the detected project type (re-seeds the questionnaire).
    project_type: str | None = None


class ConfirmParametersRequest(BaseModel):
    """Confirm the parameter sheet (checkpoint A) and compose the group board."""

    params: dict[str, Any] = Field(default_factory=dict)


class WorkPackageSelection(BaseModel):
    """A package to add to the board (curated key or a free-text custom work)."""

    package_key: str | None = None
    # Free-text custom work the composer probes immediately; ignored when
    # ``package_key`` is a curated key.
    custom_description: str | None = None
    unit: str | None = None


class IntakePackagesRequest(BaseModel):
    """Edit the package board: add / remove / toggle packages (checkpoint B)."""

    add: list[WorkPackageSelection] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)
    # {package_key: selected_bool}.
    toggle: dict[str, bool] = Field(default_factory=dict)


# ── Project-type registry (static, for the UI tiles + questionnaire) ────────


class ProjectParamOut(BaseModel):
    """One parameter in a project type's questionnaire schema."""

    key: str
    kind: Literal["number", "choice", "bool", "length"]
    unit: str | None = None
    required: bool = False
    choices: list[str] = Field(default_factory=list)
    unlocks: list[str] = Field(default_factory=list)
    round_group: int = 1
    label_key: str
    why_key: str


class WorkPackageOut(BaseModel):
    """One work package in a project type's curated checklist."""

    key: str
    trade: str
    default_on: bool = False
    stages: list[str] = Field(default_factory=list)
    unit: str = "pcs"
    label_key: str


class ProjectTypeOut(BaseModel):
    """A project type tile + its questionnaire/checklist schema for the UI."""

    key: str
    label_key: str
    synonyms: list[str] = Field(default_factory=list)
    params: list[ProjectParamOut] = Field(default_factory=list)
    packages: list[WorkPackageOut] = Field(default_factory=list)
    default_unit_system: str = "metric"
