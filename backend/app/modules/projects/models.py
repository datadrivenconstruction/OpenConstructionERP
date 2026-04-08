# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project ORM models.

Tables:
    oe_projects_project    — construction estimation projects
    oe_projects_wbs        — work breakdown structure nodes
    oe_projects_milestone  — project milestones (payment, approval, handover)
"""

import uuid

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


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
