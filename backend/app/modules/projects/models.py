# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Project ORM models.

Tables:
    oe_projects_project          — construction estimation projects
    oe_projects_wbs              — work breakdown structure nodes
    oe_projects_milestone        — project milestones (payment, approval, handover)
    oe_projects_match_settings   — per-project element-to-CWICR auto-match settings
"""

# ── Match-settings defaults (v2.8.0) ─────────────────────────────────────
# Module-level constants so the model, schemas, service, and Alembic
# migration all share a single source of truth — no magic numbers.
#
# Values are env-overridable so a deploy that ships in a non-English
# market (e.g. a Russian rollout) can change the default for fresh
# projects without a code change. Existing projects keep whatever they
# were saved with — these constants only pin the *new-row* default.
import os as _os
import uuid

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base

MATCH_DEFAULT_TARGET_LANGUAGE: str = _os.environ.get(
    "MATCH_DEFAULT_TARGET_LANGUAGE", "en"
).strip().lower() or "en"
MATCH_DEFAULT_CLASSIFIER: str = "none"


def _env_float_default(name: str, fallback: float) -> float:
    raw = _os.environ.get(name)
    if raw is None or not raw.strip():
        return fallback
    try:
        return float(raw)
    except ValueError:
        return fallback


MATCH_DEFAULT_AUTO_LINK_THRESHOLD: float = _env_float_default(
    "MATCH_DEFAULT_AUTO_LINK_THRESHOLD", 0.85
)
MATCH_DEFAULT_AUTO_LINK_ENABLED: bool = False
MATCH_DEFAULT_MODE: str = "manual"
MATCH_DEFAULT_SOURCES: tuple[str, ...] = ("bim", "pdf", "dwg", "photo")

MATCH_ALLOWED_CLASSIFIERS: frozenset[str] = frozenset(
    {"none", "din276", "nrm", "masterformat"},
)
MATCH_ALLOWED_MODES: frozenset[str] = frozenset({"manual", "auto"})
MATCH_ALLOWED_SOURCES: frozenset[str] = frozenset(MATCH_DEFAULT_SOURCES)


class Project(Base):
    """‌⁠‍Construction estimation project."""

    __tablename__ = "oe_projects_project"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    region: Mapped[str] = mapped_column(String(50), nullable=False, default="DACH")
    classification_standard: Mapped[str] = mapped_column(String(50), nullable=False, default="din276")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="de")
    validation_rule_sets: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=lambda: ["boq_quality"],
        server_default='["boq_quality"]',
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Phase 12 expansion fields (all nullable for backward compat) ─────
    project_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    project_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phase: Mapped[str | None] = mapped_column(String(50), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    parent_project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    address: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=True
    )
    contract_value: Mapped[str | None] = mapped_column(String(50), nullable=True)
    planned_start_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    planned_end_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    actual_start_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    actual_end_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    budget_estimate: Mapped[str | None] = mapped_column(String(50), nullable=True)
    contingency_pct: Mapped[str | None] = mapped_column(String(10), nullable=True)
    custom_fields: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=True
    )
    work_calendar_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # ── v2.6.0 — multi-currency + per-project VAT (RFC 37, Issues #88/#89/#93) ──
    # ``fx_rates`` holds extra currencies the project uses alongside ``currency``
    # (the base). Shape:
    #     [{"code": "USD", "rate": "1200.50", "label": "US Dollar"}]
    # ``rate`` is a decimal-string giving how many BASE units per 1 unit of the
    # foreign currency. Empty list = single-currency project (existing
    # behaviour).
    fx_rates: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # ``default_vat_rate`` overrides the regional template's VAT row when a new
    # BOQ is seeded. Stored as a decimal-string percentage (e.g. ``"21"`` for
    # 21%). NULL means "use regional default" — preserves pre-2.6 behaviour
    # for projects that never set it.
    default_vat_rate: Mapped[str | None] = mapped_column(
        String(10), nullable=True,
    )
    # ``custom_units`` lets a project carry unit codes not in the canonical
    # frontend list (Issue #93 item 3). Plain list of strings — order matters
    # because the UI shows custom units after the canonical set in the order
    # the user added them.
    custom_units: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # ── v2.9.4 — Per-project storage override (Issue #109) ──────────────
    # When ``storage_uses_default`` is True (the default), all attachments
    # for this project land under the system-wide data dir resolved by the
    # documents / photos / sheets / BIM / DWG services. When False and
    # ``storage_path_override`` is non-empty, services route writes for
    # this project under ``{override}/{project_id}/<kind>/...`` instead.
    # Reads always check both paths so legacy rows keep working.
    storage_path_override: Mapped[str | None] = mapped_column(
        String(500), nullable=True, default=None,
    )
    storage_uses_default: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default="1",
    )

    # ── Relationships ────────────────────────────────────────────────────
    children: Mapped[list["Project"]] = relationship(
        back_populates="parent_project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    parent_project: Mapped["Project | None"] = relationship(
        back_populates="children",
        remote_side="Project.id",
        lazy="selectin",
    )
    wbs_nodes: Mapped[list["ProjectWBS"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ProjectWBS.sort_order",
    )
    milestones: Mapped[list["ProjectMilestone"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ProjectMilestone.planned_date",
    )

    def __repr__(self) -> str:
        return f"<Project {self.name} ({self.status})>"


class ProjectWBS(Base):
    """‌⁠‍Work Breakdown Structure node for a project.

    Supports hierarchical decomposition of project scope into cost, schedule,
    or scope-oriented WBS trees.  Each node can carry planned cost/hours for
    earned-value analysis.
    """

    __tablename__ = "oe_projects_wbs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_wbs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_translations: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=True
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wbs_type: Mapped[str] = mapped_column(String(50), nullable=False, default="cost")
    planned_cost: Mapped[str | None] = mapped_column(String(50), nullable=True)
    planned_hours: Mapped[str | None] = mapped_column(String(50), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    project: Mapped[Project] = relationship(back_populates="wbs_nodes")
    children: Mapped[list["ProjectWBS"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    parent: Mapped["ProjectWBS | None"] = relationship(
        back_populates="children",
        remote_side="ProjectWBS.id",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<ProjectWBS {self.code} — {self.name}>"


class ProjectMilestone(Base):
    """Project milestone — payment, approval, handover, or general checkpoint.

    Tracks planned vs actual dates and can link to payment percentages for
    progress-based invoicing workflows.
    """

    __tablename__ = "oe_projects_milestone"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    milestone_type: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    planned_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    actual_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    linked_payment_pct: Mapped[str | None] = mapped_column(String(10), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    project: Mapped[Project] = relationship(back_populates="milestones")

    def __repr__(self) -> str:
        return f"<ProjectMilestone {self.name} ({self.status})>"


class MatchProjectSettings(Base):
    """Per-project settings for the element-to-CWICR auto-match pipeline.

    Captures the user's choices for the BIM/PDF/DWG/photo → catalog matcher:

    * ``target_language`` — ISO-639 two-letter code of the CWICR catalog
      slice to search against (e.g. ``de``, ``bg``, ``en``). Free-form so
      newly seeded languages don't require a schema bump.
    * ``classifier`` — optional classification standard the matcher should
      bias towards (``din276`` / ``nrm`` / ``masterformat``) or ``none``
      to skip classification altogether (per A4 decision).
    * ``auto_link_threshold`` — float in ``[0.0, 1.0]``; matches with a
      score above this are auto-linked (only when ``auto_link_enabled``).
    * ``auto_link_enabled`` — master toggle. False forces every match to
      go through human confirmation regardless of the threshold.
    * ``mode`` — ``manual`` (default) or ``auto``. The user must opt in
      to fully-automated linking.
    * ``sources_enabled`` — JSON list, subset of
      ``["bim", "pdf", "dwg", "photo"]``. Sources omitted from this list
      are skipped by the matcher service.

    One-to-one with :class:`Project` via the ``project_id`` unique FK.
    Cascade-delete on the project mirrors the WBS/milestone behaviour:
    when a project is hard-deleted its match settings go with it.
    """

    __tablename__ = "oe_projects_match_settings"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            name="uq_oe_projects_match_settings_project_id",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_language: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default=MATCH_DEFAULT_TARGET_LANGUAGE,
        server_default=MATCH_DEFAULT_TARGET_LANGUAGE,
    )
    classifier: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MATCH_DEFAULT_CLASSIFIER,
        server_default=MATCH_DEFAULT_CLASSIFIER,
    )
    auto_link_threshold: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=MATCH_DEFAULT_AUTO_LINK_THRESHOLD,
        server_default=str(MATCH_DEFAULT_AUTO_LINK_THRESHOLD),
    )
    auto_link_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=MATCH_DEFAULT_AUTO_LINK_ENABLED,
        server_default="0",
    )
    mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=MATCH_DEFAULT_MODE,
        server_default=MATCH_DEFAULT_MODE,
    )
    sources_enabled: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=lambda: list(MATCH_DEFAULT_SOURCES),
        server_default='["bim", "pdf", "dwg", "photo"]',
    )
    # CWICR catalogue ID the project matches against
    # (e.g. "RU_STPETERSBURG", "DE_BERLIN", "USA_USD"). Nullable: a freshly
    # created project has no binding — match endpoint returns a structured
    # ``no_catalog_selected`` error and the UI surfaces an explicit picker.
    # No auto-pick from ``project.region`` because regions are coarse tags
    # (DACH / EU / US) while catalogue IDs are city-level (DE_BERLIN).
    cost_database_id: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        default=None,
    )

    def __repr__(self) -> str:
        return (
            f"<MatchProjectSettings project={self.project_id} "
            f"mode={self.mode} classifier={self.classifier} "
            f"catalog={self.cost_database_id}>"
        )


class ProjectProfile(Base):
    """The applied profile for a project (concept doc §6.1).

    One row per project. Captures the wizard answers (preset, axes,
    region, …) so the module set can be recomputed when the profile is
    edited. ``focus_mode_enabled`` is the user-facing master switch the
    sidebar reads: when false the nav shows every module ungreyed
    (legacy behaviour) — the "this mode can be turned off" requirement.

    The wizard *draft* is intentionally NOT here (doc §6.4) — drafts
    live in :class:`ProjectWizardDraft` with a TTL so a half-finished
    setup never pollutes a real project.
    """

    __tablename__ = "oe_project_profile"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_project_profile_project"),
        Index("ix_project_profile_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    preset: Mapped[str] = mapped_column(
        String(64), nullable=False, default="custom", server_default="custom",
    )
    # Multi-select axes stored as JSON lists.
    activity: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]",
    )
    phases: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]",
    )
    role: Mapped[str | None] = mapped_column(String(48), nullable=True)
    size: Mapped[str | None] = mapped_column(String(24), nullable=True)
    region: Mapped[str | None] = mapped_column(String(32), nullable=True)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    extensions_enabled: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]",
    )
    # Master switch the sidebar honours. True = numbered route + greyed
    # non-selected modules. False = show everything normally.
    focus_mode_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1",
    )
    # {"wizard_steps_completed":[1,2,3,5],"skipped_steps":[4],
    #  "completion_score":0.83}
    setup_completion: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}",
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectProfile project={self.project_id} "
            f"preset={self.preset} focus={self.focus_mode_enabled}>"
        )


class ProjectModule(Base):
    """Per-project module selection (concept doc §6.1 ``modules``).

    Presentation-only gating: this drives the sidebar's visual emphasis
    (active + numbered vs greyed) — it never unloads a module or blocks
    its API. ``ordinal`` is the global sequential number (doc §3.2);
    null for cross-cutting / disabled modules. ``source`` records why
    the module is in the set (core / region / preset / score / manual)
    so the wizard can explain it and edit-setup can diff cleanly.
    """

    __tablename__ = "oe_project_module"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "module_name", name="uq_project_module_unique",
        ),
        Index("ix_project_module_project", "project_id"),
        Index("ix_project_module_project_enabled", "project_id", "enabled"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    module_name: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0",
    )
    # must | recommended | optional | hidden
    tier: Mapped[str] = mapped_column(
        String(16), nullable=False, default="hidden", server_default="hidden",
    )
    score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    phase: Mapped[str] = mapped_column(
        String(24), nullable=False, default="construction",
        server_default="construction",
    )
    # core | region | preset | score | manual
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="score", server_default="score",
    )
    # Global sequential number for the numbered route; null = no number
    # (cross-cutting / disabled).
    ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    why: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectModule project={self.project_id} "
            f"{self.module_name} {self.tier} ord={self.ordinal}>"
        )


class ProjectWizardDraft(Base):
    """Transient wizard state (concept doc §6.4).

    Separate from :class:`ProjectProfile` so an abandoned half-finished
    setup never creates a real project. Promoted to a Project +
    ProjectProfile atomically on the wizard's final "Create" step.
    Rows older than ``WIZARD_DRAFT_TTL_DAYS`` are swept by a periodic
    job (not part of Slice 1 — the column is here so the sweep has a
    timestamp to filter on).
    """

    __tablename__ = "oe_project_wizard_draft"
    __table_args__ = (
        Index("ix_project_wizard_draft_owner", "created_by"),
        Index("ix_project_wizard_draft_created", "created_at"),
    )

    # Free-form wizard answers so far; shape mirrors ProjectProfile plus
    # the in-progress project name / code / dates.
    payload: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:
        return f"<ProjectWizardDraft by={self.created_by}>"
