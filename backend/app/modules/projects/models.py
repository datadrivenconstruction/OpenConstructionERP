# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project ORM models.

Tables:
    oe_projects_project          — construction estimation projects
    oe_projects_wbs              — work breakdown structure nodes
    oe_projects_milestone        — project milestones (payment, approval, handover)
    oe_projects_match_settings   — per-project element-to-CWICR auto-match settings
"""

import uuid

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base

# ── Match-settings defaults (v2.8.0) ─────────────────────────────────────
# Module-level constants so the model, schemas, service, and Alembic
# migration all share a single source of truth — no magic numbers.
MATCH_DEFAULT_TARGET_LANGUAGE: str = "en"
MATCH_DEFAULT_CLASSIFIER: str = "none"
MATCH_DEFAULT_AUTO_LINK_THRESHOLD: float = 0.85
MATCH_DEFAULT_AUTO_LINK_ENABLED: bool = False
MATCH_DEFAULT_MODE: str = "manual"
MATCH_DEFAULT_SOURCES: tuple[str, ...] = ("bim", "pdf", "dwg", "photo")

MATCH_ALLOWED_CLASSIFIERS: frozenset[str] = frozenset(
    {"none", "din276", "nrm", "masterformat"},
)
MATCH_ALLOWED_MODES: frozenset[str] = frozenset({"manual", "auto"})
MATCH_ALLOWED_SOURCES: frozenset[str] = frozenset(MATCH_DEFAULT_SOURCES)


class Project(Base):
    """Construction estimation project."""

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
    """Work Breakdown Structure node for a project.

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
