# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BOQ ORM models.

Tables:
    oe_boq_boq — bill of quantities (one per project scope)
    oe_boq_position — individual line items within a BOQ
    oe_boq_markup — markup/overhead lines applied to a BOQ
    oe_boq_activity_log — audit trail for BOQ mutations
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class BOQ(Base):
    """Bill of Quantities — groups positions for a project."""

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
    is_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
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
    """Single line item in a BOQ — the core estimation entity."""

    __tablename__ = "oe_boq_position"

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

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

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
