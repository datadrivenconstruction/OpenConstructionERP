# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍BOQ ORM models.

Tables:
    oe_boq_boq — bill of quantities (one per project scope)
    oe_boq_position — individual line items within a BOQ
    oe_boq_markup — markup/overhead lines applied to a BOQ
    oe_boq_activity_log — audit trail for BOQ mutations
    oe_boq_snapshot — point-in-time BOQ state for version history
    oe_boq_quantity_link — live model→position quantity binding
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class BOQ(Base):
    """‌⁠‍Bill of Quantities — groups positions for a project."""

    __tablename__ = "oe_boq_boq"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)

    # ── Phase 12.2 lock & revision fields ────────────────────────────────
    estimate_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    parent_estimate_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_boq.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    base_date: Mapped[str | None] = mapped_column(String(20), nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    positions: Mapped[list["Position"]] = relationship(
        back_populates="boq",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Position.sort_order",
    )
    markups: Mapped[list["BOQMarkup"]] = relationship(
        back_populates="boq",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="BOQMarkup.sort_order",
    )

    def __repr__(self) -> str:
        return f"<BOQ {self.name} ({self.status})>"


class Position(Base):
    """‌⁠‍Single line item in a BOQ — the core estimation entity."""

    __tablename__ = "oe_boq_position"
    __table_args__ = (
        # Covers the hot read path ``WHERE boq_id=? ORDER BY sort_order``
        # used by every position listing call (repository.list_positions,
        # repository.list_children, BOQ editor refresh, GAEB export).
        # Without the composite the planner has to fall back to
        # ``ix_oe_boq_position_boq_id`` + a temp B-tree sort on every
        # request — 1.2 s on a 6 k-position BOQ. With it: ~12 ms.
        # See alembic v3123_boq_fk_indexes for the prod migration.
        Index("ix_boq_position_boq_sort", "boq_id", "sort_order"),
        # Covers the tree-walk hot path
        # ``WHERE boq_id=? AND parent_id IS ?`` used by the hierarchical
        # BOQ renderer (#136 multi-level nesting up to depth 8).
        Index("ix_boq_position_boq_parent", "boq_id", "parent_id"),
    )

    boq_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_boq.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_position.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ordinal: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    # Money/quantity stored as String by design — SQLite's native Numeric
    # degrades to REAL with precision loss, and JS JSON consumers lose
    # digits on large currency values via Number. Service layer coerces to
    # Decimal via ``_to_decimal`` for all arithmetic.
    quantity: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    unit_rate: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    total: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    classification: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    cad_element_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    validation_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")

    # ── Phase 12.2 expansion fields ──────────────────────────────────────
    wbs_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cost_code_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # ── Issue #127: reusable code & linked-position groups ───────────────
    # ``reference_code`` is the USER-FACING reusable code
    # (Sección/Partida/Recurso, e.g. "0040"). It is DELIBERATELY distinct
    # from ``ordinal`` (the line number): ``ordinal`` stays unique within a
    # BOQ (GAEB X83 RNoPart/ID identity + boq_quality.no_duplicate_ordinals),
    # while the SAME ``reference_code`` may be reused across many positions.
    # Every position carries one (auto-generated "R-XXXXXXXX" when the
    # client supplies none) so it is always referenceable.
    reference_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Positions that SHARE one master definition all carry the same
    # ``link_group_id``. NULL = standalone (not yet part of a group).
    link_group_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    # 'master' = owns the canonical definition; 'instance' = a linked reuse
    # that mirrors the master's definition; NULL = standalone.
    link_role: Mapped[str | None] = mapped_column(String(16), nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── BUG-CONCURRENCY01: optimistic concurrency token ─────────────────
    # Bumped on every successful service-layer update.  Clients echo the
    # last-read value on PATCH; mismatch returns 409 instead of allowing
    # a lost write.  Default 0 for legacy rows so existing data is valid.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Relationships
    boq: Mapped[BOQ] = relationship(back_populates="positions")
    children: Mapped[list["Position"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    parent: Mapped["Position | None"] = relationship(
        back_populates="children",
        remote_side="Position.id",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Position {self.ordinal} — {self.description[:40]}>"


class BOQMarkup(Base):
    """Markup line applied to a BOQ (overhead, profit, tax, contingency).

    Represents a single markup/overhead line that is applied on top of the
    direct cost (sum of position totals).  Markups are ordered by ``sort_order``
    and can be applied as a percentage of the direct cost, a fixed amount, or
    cumulatively (percentage of direct cost + preceding markups).

    Columns:
        boq_id — owning BOQ
        name — human-readable label, e.g. "Site Overhead (BGK)"
        markup_type — "percentage" | "fixed" | "per_unit"
        category — semantic grouping: overhead, profit, tax, contingency, …
        percentage — stored as string for SQLite compatibility (e.g. "8.0")
        fixed_amount — used when markup_type is "fixed"
        apply_to — "direct_cost" (default) or "cumulative"
        sort_order — evaluation order (ascending)
        is_active — soft toggle
    """

    __tablename__ = "oe_boq_markup"
    __table_args__ = (
        # Covers ``WHERE boq_id=? ORDER BY sort_order, created_at`` —
        # the single read pattern for the markups grid (repository
        # ``list_for_boq``, BOQ total rollup, GAEB export markup write).
        Index("ix_boq_markup_boq_sort", "boq_id", "sort_order"),
    )

    boq_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_boq.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    markup_type: Mapped[str] = mapped_column(String(50), nullable=False, default="percentage")
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="overhead")
    percentage: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    fixed_amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    apply_to: Mapped[str] = mapped_column(String(50), nullable=False, default="direct_cost")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    boq: Mapped[BOQ] = relationship(back_populates="markups")

    def __repr__(self) -> str:
        return f"<BOQMarkup {self.name} ({self.markup_type}: {self.percentage}%)>"


class BOQActivityLog(Base):
    """Audit trail entry for BOQ-related mutations.

    Records every significant action (position created/updated/deleted,
    markup added, BOQ exported, etc.) for traceability and undo support.

    Columns:
        project_id — optional project scope for project-wide queries
        boq_id — optional BOQ scope
        user_id — who performed the action
        action — dot-notation action key, e.g. "position.created"
        target_type — entity kind: "position", "boq", "markup", "section"
        target_id — UUID of the affected entity (nullable for bulk ops)
        description — human-readable summary, e.g. "Added position 01.01.0010"
        changes — field-level diff, e.g. {"field": "quantity", "old": "100", "new": "150"}
        metadata_ — additional context (module version, client IP, etc.)
    """

    __tablename__ = "oe_boq_activity_log"
    __table_args__ = (
        Index("ix_boq_activity_user_created", "user_id", "created_at"),
        Index("ix_boq_activity_target", "target_type", "target_id"),
        # Audit-feed read paths — both per-project and per-BOQ activity
        # streams are ordered by created_at DESC. The composites turn an
        # O(n) sequential scan of the (potentially huge) audit table into
        # an index-only range scan.
        Index("ix_boq_activity_project_created", "project_id", "created_at"),
        Index("ix_boq_activity_boq_created", "boq_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    boq_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_boq.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    changes: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<BOQActivityLog {self.action} target={self.target_type}:{self.target_id}>"


class BOQSnapshot(Base):
    """Point-in-time snapshot of a BOQ for version history.

    Stores a full JSON snapshot of the BOQ state (positions, markups)
    so users can view and restore previous versions.
    """

    __tablename__ = "oe_boq_snapshot"
    __table_args__ = (
        # Version-history list is ordered by created_at DESC scoped to
        # one BOQ — composite turns the index seek into a range scan
        # without a separate sort step.
        Index("ix_boq_snapshot_boq_created", "boq_id", "created_at"),
    )

    boq_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_boq.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    snapshot_data: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<BOQSnapshot boq={self.boq_id} name={self.name}>"


class QuantityLink(Base):
    """Live binding between a BOQ position and a set of BIM model elements.

    Records *how* a position's numeric field is derived from the canonical
    quantities of one or more model elements so the figure can be
    re-pulled when the source model revises. The link is a *rule*, never a
    cached value — the current quantity always lives on
    :class:`Position`; this row only states the extraction recipe and the
    provenance of the last applied pull.

    Columns:
        position_id — owning BOQ position (CASCADE on delete)
        boq_id — denormalised owning BOQ for cheap per-BOQ listing/refresh
        model_id — the BIM model the binding tracks (NOT version-pinned;
            ``compute_diff`` resolves the latest version on refresh)
        element_stable_ids — list[str] of canonical element ``stable_id``s
            whose quantities feed this position
        quantity_field — the canonical quantity key to read off each
            element's ``quantities`` map, e.g. ``area_m2`` / ``volume_m3``
        target_field — the Position numeric field the aggregate writes to;
            currently always ``quantity`` (only field a model can drive)
        aggregation — how multiple elements combine: ``sum`` (default),
            ``max``, ``min``, ``count``, ``first``
        status — ``active`` (in sync) | ``stale`` (a refresh detected the
            source elements changed and a human has not yet applied) |
            ``broken`` (model/elements no longer resolvable)
        source_model_version — the model ``version`` string captured at
            the last successful apply (provenance)
        last_applied_quantity — the position quantity this link last
            wrote (provenance / staleness baseline), stored as a string
            for the same SQLite-precision reason as Position.quantity
        last_pulled_at — ISO-8601 UTC timestamp of the last refresh probe
        last_applied_at — ISO-8601 UTC timestamp of the last human apply
        created_by / applied_by — user provenance (who bound / who applied)
        metadata_ — module-extensible blob (last diff envelope etc.)
    """

    __tablename__ = "oe_boq_quantity_link"
    __table_args__ = (
        Index("ix_boq_quantity_link_boq", "boq_id"),
        Index("ix_boq_quantity_link_status", "status"),
        # "Find broken / stale links for this BOQ" — the dashboard
        # health card hits this on every BOQ open.
        Index("ix_boq_quantity_link_boq_status", "boq_id", "status"),
    )

    position_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_position.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    boq_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_boq.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    element_stable_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    quantity_field: Mapped[str] = mapped_column(String(64), nullable=False)
    target_field: Mapped[str] = mapped_column(String(32), nullable=False, default="quantity", server_default="quantity")
    aggregation: Mapped[str] = mapped_column(String(16), nullable=False, default="sum", server_default="sum")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    source_model_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_applied_quantity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_pulled_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_applied_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    applied_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return (
            f"<QuantityLink pos={self.position_id} model={self.model_id} "
            f"{self.quantity_field}->{self.target_field} ({self.status})>"
        )
