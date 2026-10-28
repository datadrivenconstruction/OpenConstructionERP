# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠AI Estimate Builder ORM models.

Tables:
    oe_ai_estimator_run    - one long-lived estimate job. Carries the run FSM
                             status, the per-stage checkpoint state, the
                             detected source / suggested config, the resolved
                             provider+model, spend rollup, the last validation
                             report, the grand total (per-currency subtotals),
                             and the BOQ written on apply.
    oe_ai_estimator_group  - one row per quantity group inside a run: rolled-up
                             quantities, the source-agnostic ElementEnvelope, the
                             chosen rate candidate (code/unit_rate/currency with a
                             real retrieval-derived score + confidence), the full
                             resource breakdown, the top-K candidates considered
                             (for the override UI), and the applied BOQ position.
    oe_ai_estimator_step   - the run's ReAct / pipeline timeline. One row per
                             stage event (thought / tool_call / observation /
                             answer / error / stage_complete) for clean per-run
                             provenance, mirroring the AgentStep shape.
    oe_ai_estimator_intake - the conversational intake (v2) state for a run:
                             one row per run (1:1), carrying the dialogue FSM
                             phase, the detected project type, the partial /
                             confirmed parameter sheet, the per-param status,
                             the clarification round counter, the current
                             question batch, the transcript, and the composed
                             package-board state. The intake sits in front of
                             the run FSM and is resumable / pollable like the
                             rest of the run.

The run/step tables are append-only from a user's perspective (the service
writes incrementally as the pipeline advances). Group rows are mutated as the
user overrides / skips / confirms matches. Money + quantity fields are stored
as Decimal-as-strings to match the BOQ/CostItem convention; the service coerces
to Decimal and never rounds through float.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class AiEstimatorRun(Base):
    """A single AI estimate job - the four-stage pipeline bookkeeping row.

    The run is a long-lived, pollable job. ``status`` is the run FSM
    (``draft`` -> ``analyzing`` -> ``grouping`` -> ``matching`` -> ``review``
    -> ``applied``, plus ``failed`` / ``cancelled``); ``current_stage`` names
    the stage the run is sitting in. Each human-confirm checkpoint records its
    acceptance under ``checkpoints`` so a stage cannot advance until the prior
    checkpoint is accepted.
    """

    __tablename__ = "oe_ai_estimator_run"
    __table_args__ = (
        Index("ix_ai_estimator_run_project", "project_id"),
        Index("ix_ai_estimator_run_user", "user_id"),
        Index("ix_ai_estimator_run_project_status", "project_id", "status"),
        Index("ix_ai_estimator_run_boq", "boq_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    # Human-facing label for the run list. Auto-derived from the source when
    # the user does not name it.
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The user-selected agent slug driving stage-3 reasoning. NULL = the
    # deterministic (no-agent) fallback path; honours the founder's "the agent
    # the user selected".
    agent_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # ── FSM ──────────────────────────────────────────────────────────────
    # draft | analyzing | grouping | matching | review | applied | failed |
    # cancelled
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    # The stage the run is currently sitting in: source | grouping | matching |
    # assembly. Distinct from ``status`` so the UI stepper can render the active
    # stage even while a background pass runs.
    current_stage: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="source",
        server_default="source",
    )
    # Per-checkpoint acceptance + edits, keyed by stage:
    # {"source": {"accepted_at": "<iso>", "by": "<uuid>"}, "grouping": {...}}
    checkpoints: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # ── Stage 1 outputs ──────────────────────────────────────────────────
    # Raw source references: uploaded file refs, pasted text, picked BIM model
    # ids, selected project document ids, plus the source kind.
    source_inputs: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # {"type": "excel"|"text"|"bim"|"dwg"|"pdf"|"photo"|"documents",
    #  "confidence": 0.0-1.0, "disciplines": [...], "summary": "..."}
    detected_source: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # AI-suggested config the user reviews at checkpoint #1:
    # {"catalogue_id", "region", "currency", "group_by": [...],
    #  "construction_stage"}.
    suggested_config: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # ── Confirmed config (the values the run actually matches against) ────
    # CWICR v3 region id ("DE_BERLIN", "US_BOSTON") or a legacy CostDatabase
    # UUID string. String so both shapes round-trip without a 422.
    catalogue_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    region: Mapped[str | None] = mapped_column(String(32), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Active group-by attribute keys, ordered.
    group_by: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # One of the 12 OmniClass-aligned stages, or NULL for no temporal pin.
    construction_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # ── AI provenance + spend ────────────────────────────────────────────
    # The provider/model that actually ran (resolved via
    # resolve_provider_key_model). NULL on the deterministic path.
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(120), nullable=True)
    total_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    # Estimated USD spend, computed from tokens at persist time. Float for
    # symmetry with AIEstimateJob.cost_usd_estimate.
    cost_usd_estimate: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        server_default="0.0",
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    # ── Stage 4 outputs ──────────────────────────────────────────────────
    # Last validation report envelope (status / score / results) surfaced as
    # the traffic-light before apply. A SKIPPED report scores None, not 1.0.
    validation_report: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
        default=None,
    )
    # Grand total in the run's base currency, Decimal-as-string. NULL until the
    # assembly preview runs.
    grand_total: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Per-currency subtotals so currencies are never blended:
    # {"EUR": "12345.67", "USD": "890.00"}.
    currency_subtotals: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # CHECK_SCOPE advisory completeness (0.0-1.0), NULL when not computed.
    completeness_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Set to the written BOQ on apply.
    boq_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Free-form reason when status=failed (e.g. "no_catalogue", "llm_error").
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    groups: Mapped[list[AiEstimatorGroup]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<AiEstimatorRun {self.id} status={self.status} stage={self.current_stage}>"


class AiEstimatorGroup(Base):
    """A single quantity group inside a run - N elements sharing group-by values.

    ``group_key`` is the human-readable composite key; ``signature`` is the
    canonical hash used for cross-project template reuse. ``quantities`` carries
    the canonical rolled-up amounts (``area_m2`` / ``volume_m3`` / ``length_m``
    / ``count`` / ``mass_kg``); ``envelope`` is the source-agnostic
    ElementEnvelope the matcher consumes. The chosen-candidate columns store the
    grounded rate (code/unit_rate/currency) plus a REAL retrieval-derived score
    and confidence in [0, 1] or NULL - never a fabricated placeholder.
    """

    __tablename__ = "oe_ai_estimator_group"
    __table_args__ = (
        Index("ix_ai_estimator_group_run_status", "run_id", "status"),
        Index("ix_ai_estimator_group_signature", "signature"),
        Index("ix_ai_estimator_group_boq_position", "boq_position_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_ai_estimator_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_key: Mapped[str] = mapped_column(String(500), nullable=False)
    # SHA-1 hex of the normalized signature fields; survives key reordering.
    signature: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # IDs from the source-adapter universe (stringified element ids).
    element_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    element_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    # Rolled-up canonical quantities for the whole group, per unit type.
    quantities: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # The serialised ElementEnvelope the matcher consumes for this group.
    envelope: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    chosen_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Clean human-readable label the AI/grouping pass assigns to the group.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Trade bucket from the stage-2 taxonomy (earthworks / foundations / ...).
    trade: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # ── Chosen candidate (the grounded rate) ─────────────────────────────
    # The picked candidate's id (CostItem.id / CatalogResource.id), kept as a
    # string so non-UUID candidate refs round-trip.
    candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chosen_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Unit rate, Decimal-as-string. NULL = no grounded rate (honest "no rate").
    unit_rate: Mapped[str | None] = mapped_column(String(40), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Raw retrieval/rerank score [0, 1] or NULL - never fabricated.
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Real derived confidence [0, 1] or NULL.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # high | medium | low | none
    confidence_band: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Chosen candidate's full resource breakdown (scaled at apply time):
    # [{name, code, unit, quantity, unit_rate, cost, type}]
    resources: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # Top-K candidates considered, for the override UI:
    # [{candidate_id, code, description, unit, unit_rate, currency, score,
    #   confidence_band}]
    candidates: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # How the chosen candidate was matched: vector | lexical | resources | llm
    # | manual | auto.
    match_method: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # ── Status + provenance ──────────────────────────────────────────────
    # unmatched | suggested | confirmed | overridden | skipped | tbd |
    # needs_human | applied
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="unmatched",
        server_default="unmatched",
    )
    # Set to the Position.id once apply-to-BOQ writes the row.
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    run: Mapped[AiEstimatorRun] = relationship(back_populates="groups")

    def __repr__(self) -> str:
        return f"<AiEstimatorGroup {self.group_key} status={self.status}>"


class AiEstimatorStep(Base):
    """One entry in a run's pipeline / ReAct timeline.

    Mirrors :class:`app.modules.ai_agents.models.AgentStep` but is keyed by an
    AI-estimator run for clean per-run provenance. ``role`` values:
    ``thought`` (LLM reasoning), ``tool_call`` (``content`` is ``{name, args}``),
    ``observation`` (tool result/error), ``answer`` (final stage text),
    ``error`` (out-of-band failure), ``stage_complete`` (a stage finished -
    ``content`` carries the stage summary).
    """

    __tablename__ = "oe_ai_estimator_step"
    __table_args__ = (
        Index("ix_ai_estimator_step_run", "run_id"),
        Index("ix_ai_estimator_step_run_idx", "run_id", "step_idx"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_ai_estimator_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # source | grouping | matching | assembly
    stage: Mapped[str] = mapped_column(String(24), nullable=False)
    step_idx: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    # thought | tool_call | observation | answer | error | stage_complete
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[dict | list | str | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
    )
    token_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    # Optional per-step latency for the timeline UI.
    took_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return f"<AiEstimatorStep run={self.run_id} idx={self.step_idx} role={self.role}>"


class AiEstimatorIntake(Base):
    """Conversational intake (v2) state for a run - one row per run (1:1).

    The intake is a small FSM that sits in front of the run FSM: it turns a
    vague free-text request ("ремонт кухни") into a confirmed parameter sheet
    plus a composed, editable element-group board, then hands off to the
    existing grouping -> matching -> apply pipeline unchanged. It is persisted
    so it is resumable and pollable like the run.

    ``mode`` is ``ai`` (LLM-driven conversation) or ``offline`` (curated
    questionnaire form through the same machine). ``phase`` walks the dialogue
    (``collect_request`` -> ``extract`` -> ``clarify_round_1..3`` ->
    ``parameter_sheet`` -> ``compose_groups`` -> ``group_board`` -> ``done``).
    ``round_idx`` is the hard 0..3 clarification-round counter (max 3 rounds,
    founder decision 1). ``param_status`` records, per parameter,
    ``known | asked | confirmed | skipped`` so the machine never re-asks a
    question it already has an answer for.
    """

    __tablename__ = "oe_ai_estimator_intake"
    __table_args__ = (Index("ix_ai_estimator_intake_run", "run_id", unique=True),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_ai_estimator_run.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    # "ai" | "offline" - whether the dialogue is LLM-phrased or a curated form.
    mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="offline",
        server_default="offline",
    )
    # The original free-text request the user submitted (or "" on a manual
    # type pick). source_inputs.text_input still mirrors this for v1 back-compat.
    raw_request: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # The detected project_type key, or NULL when none / ambiguous (the UI then
    # shows the type tiles for a manual pick).
    detected_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Real type-detection confidence [0,1] or NULL (NULL on the deterministic
    # offline path - honest "selected", not a fabricated percentage).
    type_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The partial / confirmed parameter sheet: {param_key: value}.
    params: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # Per-param lifecycle: {param_key: "known"|"asked"|"confirmed"|"skipped"}.
    param_status: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # How many clarification rounds have been used (0..3, hard ceiling 3).
    round_idx: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    # The current round's question batch (serialised IntakeQuestion dicts).
    questions: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # The dialogue transcript: [{"role": "user"|"assistant", "text": "...",
    # "ts": "<iso>"}].
    transcript: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # The intake dialogue phase (see service._INTAKE_PHASES).
    phase: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="collect_request",
        server_default="collect_request",
    )
    # The composed package-board state: [{"package_key", "selected",
    # "coverage", "best_score", "group_ids", "quantity", "unit", "estimated",
    # "stages", "trade"}].
    packages: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    def __repr__(self) -> str:
        return f"<AiEstimatorIntake run={self.run_id} phase={self.phase} mode={self.mode}>"
