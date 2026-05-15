# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Match Elements ORM models.

Tables:
    oe_match_elements_session   — per-project session: source, group-by config,
                                  filters, scope exclusions, threshold, name
    oe_match_elements_group     — one row per group inside a session: element ids,
                                  rolled-up quantities, matcher results, status,
                                  applied BOQ position
    oe_match_elements_template  — cross-project library: tenant-scoped reusable
                                  signature → CWICR position mapping that the
                                  next project's match flow auto-suggests
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class MatchSession(Base):
    """A user's matching session for a single project + source.

    Sessions are durable so estimators can pause and come back. The
    ``group_by`` and ``filters`` columns are the live config; changes
    rebuild groups on the fly via the source adapter.
    """

    __tablename__ = "oe_match_elements_session"
    __table_args__ = (
        Index("ix_match_session_project", "project_id"),
        Index("ix_match_session_project_active", "project_id", "is_archived"),
        Index("ix_match_session_bim_model", "bim_model_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional binding to a specific BIM model. NULL = "all models in the
    # project" (legacy behaviour); set = scope groups to that model only.
    # Multi-model projects (arch + struct + MEP) need this so a session
    # can stay focused on one discipline.
    bim_model_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), nullable=True,
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="bim")
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Active group-by attribute keys, ordered. e.g. ["ifc_class","type_name","material"]
    group_by: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]",
    )
    # Element-level filters before group-by. e.g. {"ifc_class":["IfcWall"],"level":["L01"]}
    filters: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}",
    )
    # IfcCategories chip-excluded from estimation scope.
    excluded_categories: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]",
    )
    # 0.95 = safety-net DB default. The runtime default is
    # ``DEFAULT_AUTO_CONFIRM_THRESHOLD`` from the match-service config,
    # which the Pydantic ``SessionCreate`` schema applies before insert,
    # so an env-overridden tenant deploy still gets its calibrated
    # threshold on every fresh session. The literal "0.95" only fires
    # when a row is inserted without going through the schema path
    # (raw SQL backfill, alembic data migration).
    auto_confirm_threshold: Mapped[str] = mapped_column(
        String(10), nullable=False, default="0.95", server_default="0.95",
    )
    # When true, wall/slab/column volumes deduct IfcOpeningElement voids.
    use_net_quantities: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1",
    )
    # Single CWICR catalogue when project has multiple language variants.
    # Null = match against all attached active CWICR catalogues.
    catalogue_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), nullable=True, index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Bumped by the touch endpoint and confirm/match writes so the resume
    # picker can sort by recent activity. Nullable for legacy rows.
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # User-archived sessions hide from the resume picker but stay in DB
    # so applied BOQ positions keep their backlinks.
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0",
    )
    # v3-P10b: User-picked construction stage that pins the SearchPlan's
    # ``construction_stage`` hard filter. Null = no stage pin (default —
    # search the full catalogue without temporal narrowing). Allowed
    # values are the 12 OmniClass-aligned stages ("02_Demolition" ...
    # "13_Sitework"); enforced by the schema validator, not the column
    # type, so tomorrow's 14th stage doesn't need a migration.
    construction_stage: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}",
    )

    groups: Mapped[list[MatchGroup]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<MatchSession project={self.project_id} source={self.source}>"


class MatchGroup(Base):
    """A single group within a session — N elements that share group-by values.

    ``group_key`` is the human-readable composite key
    (``"ifc_class:IfcWall|material:STB|thickness:240"``). ``signature`` is the
    canonical hash used for cross-project lookup in ``oe_match_elements_template``.
    """

    __tablename__ = "oe_match_elements_group"
    __table_args__ = (
        UniqueConstraint("session_id", "group_key", name="uq_match_group_session_key"),
        Index("ix_match_group_session_status", "session_id", "status"),
        Index("ix_match_group_signature", "signature"),
        Index("ix_match_group_boq_position", "boq_position_id"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_match_elements_session.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_key: Mapped[str] = mapped_column(String(500), nullable=False)
    # SHA-1 hex of normalized signature fields; survives slight key reordering.
    signature: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # IDs from the source-adapter universe (BIMElement.id stringified, etc.).
    element_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]",
    )
    element_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    # Rolled-up quantities for the whole group, per unit type. Always carries
    # ``volume_m3``, ``area_m2``, ``length_m``, ``count`` plus
    # ``gross_volume_m3`` / ``net_volume_m3`` when the source has openings.
    quantities: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}",
    )
    # Override of the auto-picked unit (m3 / m2 / m / pcs).
    chosen_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Per-method candidates: {"vector":[{candidate_id,confidence,...},...],
    # "lexical":[...], "llm":[...]}. Cached to avoid re-running matchers.
    methods: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}",
    )
    chosen_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), nullable=True, index=True,
    )
    chosen_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # unmatched | suggested | confirmed | overridden | skipped | tbd | applied
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unmatched", server_default="unmatched",
    )
    # Set to the Position.id once apply-to-BOQ writes the row.
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), nullable=True,
    )
    # Optional override of which attribute fields to consider when computing
    # the cross-project signature (default = session.group_by). Lets the user
    # decide "this match was about wall material only — ignore thickness".
    signature_fields: Mapped[list | None] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=True,
    )
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}",
    )

    session: Mapped[MatchSession] = relationship(back_populates="groups")

    def __repr__(self) -> str:
        return f"<MatchGroup {self.group_key} status={self.status}>"


class MatchTemplate(Base):
    """Cross-project mapping library — tenant-scoped reusable signatures.

    When a user confirms a match in Project A, a row goes here. When they
    open a session in Project B and a group's normalized ``signature``
    matches an existing template, the system pre-suggests the same CWICR
    position with a "previously matched" hint.
    """

    __tablename__ = "oe_match_elements_template"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "signature", name="uq_match_template_tenant_signature",
        ),
        Index("ix_match_template_tenant", "tenant_id"),
        Index("ix_match_template_signature", "signature"),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), nullable=True, index=True,
    )
    signature: Mapped[str] = mapped_column(String(64), nullable=False)
    # Human-readable label for the library UI ("IfcWall · Stahlbeton · 240mm").
    label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cwicr_position_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_costs_item.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The signature_fields and last group_by used to derive this signature.
    # Stored so the UI can explain "this template was created from
    # ifc_class+material+thickness on Project A".
    source_fields: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]",
    )
    use_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<MatchTemplate {self.signature[:12]} → {self.cwicr_position_id}>"


class MatchSearchLog(Base):
    """Per-request analytics row for v3-P10 SearchPlan auditing.

    One row per call into the ranker. Records the SearchPlan inputs
    (hard filters, soft boosts, catalog), the search outcome (relax
    tier used, hit count, top score, confidence band of the top
    candidate, latency), and which optional reranker tiers ran.

    Used for:

    * Calibration sweeps: "of N searches, how many fell back past
      tier 0?" → if >30% the default filter set is too tight.
    * Confidence-band tuning: scatter top_score vs hard filter count
      to validate the §6.4 promotion thresholds.
    * Catalogue gap detection: low ``top_score`` + high
      ``relax_tier_used`` across the same ``catalog_id`` flags
      vectorisation gaps.
    * Latency monitoring: p95 of ``took_ms`` segmented by
      ``bge_rerank_used`` shows the cross-encoder cost in production.

    Retention: rows accumulate forever by design — search logs are
    cheap (one INSERT per match call, no cascading writes) and the
    analytics value compounds with history. Operators can prune via
    SQL when the table grows past 50M rows.
    """

    __tablename__ = "oe_match_elements_search_log"
    __table_args__ = (
        Index("ix_match_search_log_project_time", "project_id", "created_at"),
        Index("ix_match_search_log_catalog_time", "catalog_id", "created_at"),
        Index("ix_match_search_log_session", "session_id"),
        Index("ix_match_search_log_tier", "relax_tier_used"),
        # v2936 — feedback + envelope-context analytics
        Index("ix_match_search_log_picked_rank", "picked_rank"),
        Index("ix_match_search_log_source_type", "source_type"),
        Index("ix_match_search_log_country_time", "country", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Both nullable — ad-hoc /costs/qdrant-search calls have no session.
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_match_elements_session.id", ondelete="SET NULL"),
        nullable=True,
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_match_elements_group.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Catalogue + collection routing — keep both so analytics can join
    # against config changes (e.g., when the v3 → v4 schema flip
    # rebrands ``cwicr_de_v3`` → ``cwicr_de_v4``).
    catalog_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    collection_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The ``core_query`` from the SearchPlan, truncated for storage.
    core_query: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    hard_filters: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}",
    )
    soft_boosts: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]",
    )
    # Counters
    hits_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    relax_tier_used: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    top_score: Mapped[float | None] = mapped_column(nullable=True)
    top_confidence_band: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
    )
    bge_rerank_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0",
    )
    llm_rerank_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0",
    )
    took_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Free-form metadata bag for future analytics dimensions without a
    # migration (e.g., translation_used, abstract_substituted_count).
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}",
    )

    # ── v2936 — user-feedback columns (MAPPING_PROCESS.md §10) ───────
    # Populated by the /confirm hook in service.MatchService.confirm().
    # Without these the §10 alerts (`user_picked_rank > 4` for >20% of
    # requests = re-train classifier) cannot fire.
    picked_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    picked_rate_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    picked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # ── v2936 — envelope-context columns ────────────────────────────
    # Populated by ranker_qdrant._write_search_log() at INSERT time.
    # Lets analytics filter "recall by ifc_class" without a 3-table
    # JOIN through session → group → element.
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ifc_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Region head (``DE``, ``RU``, ``USA``) — derived from catalog_id
    # at write time.
    country: Mapped[str | None] = mapped_column(String(16), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<MatchSearchLog catalog={self.catalog_id} "
            f"hits={self.hits_count} tier={self.relax_tier_used} "
            f"top={self.top_score}>"
        )


class MatchStageState(Base):
    """Per-session × per-stage runtime state for the visible pipeline.

    The pipeline has seven named stages — ``convert``, ``load``, ``schema``,
    ``filter``, ``group``, ``match``, ``rollup``. Each gets exactly one row
    per session; ``status`` advances pending → running → done | error so
    the UI can render a status pill, an output preview, and a "Re-run from
    here" button per stage.

    ``inputs`` and ``output`` are JSON envelopes the stage runner writes —
    inputs capture the knobs (group_by, filter expression, prompt body,
    LLM provider, threshold) so the user can tweak and re-run; output
    captures a small preview (row count, sample rows, score histogram)
    plus pointers into the underlying tables (matched group_ids, etc.).
    The full element/candidate payload stays in the existing tables —
    this row is the audit + control surface.
    """

    __tablename__ = "oe_match_elements_stage"
    __table_args__ = (
        UniqueConstraint("session_id", "stage_name", name="uq_match_stage_session_name"),
        Index("ix_match_stage_session", "session_id"),
        Index("ix_match_stage_status", "status"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_match_elements_session.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage_name: Mapped[str] = mapped_column(String(32), nullable=False)
    # pending | running | done | error | skipped
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending",
    )
    # Stage-specific knobs (group_by override, filter expression, prompt
    # template id, LLM provider/model, threshold...). Default = inherited
    # from session config.
    inputs: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}",
    )
    # Stage output envelope — never the raw payload, just a small preview:
    # element_count, sample rows, top-N scores, summary metrics. Used by
    # the StageCard to render the "what happened" panel without a second
    # roundtrip.
    output: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}",
    )
    # Last error message when status == "error", or NULL otherwise.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    took_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ``oe_match_elements_prompt_template.id`` when the stage uses an LLM
    # prompt. NULL for non-LLM stages (load, schema, group, rollup).
    prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), nullable=True,
    )
    # LLM provider/model — only set when prompt_template_id is set. e.g.
    # ``"anthropic/claude-sonnet-4-6"``, ``"openai/gpt-4o"``,
    # ``"local/ollama-mistral"``.
    llm_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<MatchStageState session={self.session_id} "
            f"stage={self.stage_name} status={self.status}>"
        )


class MatchPromptTemplate(Base):
    """User-editable prompt templates that drive the LLM-augmented stages.

    Two kinds of rows live here:

    * **System prompts** (``is_system=True``, ``created_by=NULL``) — seeded
      by the migration from the n8n workflow we ported from. The user
      cannot edit a system row directly; the UI offers a "Fork" action
      that copies it into a user-owned row.
    * **User prompts** (``is_system=False``, ``created_by`` set) — created
      by forking a system prompt or by typing a new one from scratch.
      Fully editable; carry their own ``version`` so an estimator can
      revert.

    ``key`` is the stage hook the prompt plugs into:
    ``schema.header_aggregation``, ``filter.building_classifier``,
    ``match.cost_agent``, ``group.key_picker``. The stage runner resolves
    the active prompt by (a) reading ``stage_state.prompt_template_id``
    if set, else (b) loading the most recent template for the stage's
    canonical key from this table.
    """

    __tablename__ = "oe_match_elements_prompt_template"
    __table_args__ = (
        Index("ix_match_prompt_key_version", "key", "version"),
        Index("ix_match_prompt_creator", "created_by"),
        UniqueConstraint("key", "name", "created_by", name="uq_match_prompt_owner_name"),
    )

    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Jinja-ish ``{var}`` placeholders for the user-supplied row data.
    # No sandboxed execution — pure string ``str.format()`` so the call
    # surface is the same regardless of provider.
    user_template: Mapped[str] = mapped_column(Text, nullable=False)
    # Comma-separated list of allowed providers, or empty for "any". e.g.
    # ``"anthropic/claude-sonnet-4-6,openai/gpt-4o"``.
    allowed_providers: Mapped[str | None] = mapped_column(String(512), nullable=True)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Forked-from pointer so the UI can show "edited from system prompt
    # header_aggregation_v1". NULL on system rows and freshly-typed ones.
    forked_from_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}",
    )

    def __repr__(self) -> str:
        return (
            f"<MatchPromptTemplate key={self.key} name={self.name} "
            f"v{self.version} system={self.is_system}>"
        )
