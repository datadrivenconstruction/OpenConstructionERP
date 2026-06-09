# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Approval Routes ORM models.

Tables
------

``oe_approval_routes_route``
    Template definition. Project-scoped or tenant-wide (project_id NULL).

``oe_approval_routes_step``
    Ordered step inside a route. Either ``approver_role`` OR
    ``approver_user_id`` is set - not both - and the service validates
    this. ``mode`` describes aggregation when the role expands to
    several users.

``oe_approval_routes_instance``
    A running workflow for a concrete target row. Polymorphic via
    ``(target_kind, target_id)`` - the engine never FKs into a specific
    module's table.

``oe_approval_routes_step_state``
    Per-step decision. ``UniqueConstraint(instance_id, step_id,
    approver_user_id)`` is the race-guard against simultaneous decisions
    from the same user on the same step.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

# Canonical target kinds - open-ended ``String(64)`` in the DB so new
# kinds don't need a migration; this tuple is the validated whitelist
# surfaced to API consumers.
TARGET_KINDS: tuple[str, ...] = (
    "markup",
    "submittal",
    "change_order",
    "rfi",
    "contract",
    "variation",
    "invoice",
    "purchase_order",
    # QMS hold / witness point disposition. A failed or conditional
    # inspection on a hold point fans out ``qms.inspection.approval_requested``;
    # when the project has a route configured for this kind, the QMS module's
    # subscriber starts an instance against the inspection so the gate cannot
    # release without a formal disposition approval (item 12).
    "qms_hold_point",
)

# Aggregation mode at a single step when the approver_role expands to
# multiple users.
STEP_MODES: tuple[str, ...] = ("all", "any", "majority")

# Instance lifecycle.
INSTANCE_STATUSES: tuple[str, ...] = ("pending", "approved", "rejected", "cancelled")

# Per-step decision.
STEP_DECISIONS: tuple[str, ...] = ("pending", "approved", "rejected")


class Route(Base):
    """Approval route template (definition, not an active workflow)."""

    __tablename__ = "oe_approval_routes_route"
    __table_args__ = (Index("ix_approval_route_project_kind", "project_id", "target_kind"),)

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<Route {self.name!r} kind={self.target_kind} active={self.is_active}>"


class Step(Base):
    """Ordered approver slot inside a :class:`Route`."""

    __tablename__ = "oe_approval_routes_step"
    __table_args__ = (Index("ix_approval_step_route_ordinal", "route_id", "ordinal"),)

    route_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_approval_routes_route.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approver_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="all",
        server_default="all",
    )
    # Eligible-approver population for a role-based ``all`` / ``majority``
    # step. The engine cannot expand a role to its members, so when the
    # route author needs a true quorum they persist the expected count
    # here and the advance logic evaluates against it. NULL means the
    # author did not declare a quorum.
    required_approver_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        target = self.approver_role or str(self.approver_user_id)
        return f"<Step #{self.ordinal} {self.mode} -> {target}>"


class Instance(Base):
    """A running approval workflow against one target row."""

    __tablename__ = "oe_approval_routes_instance"
    __table_args__ = (Index("ix_approval_instance_target", "target_kind", "target_id"),)

    route_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_approval_routes_route.id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    current_step_ordinal: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    started_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Instance {self.target_kind}:{self.target_id} step={self.current_step_ordinal} status={self.status}>"


class StepState(Base):
    """Per-step decision row inside one :class:`Instance`."""

    __tablename__ = "oe_approval_routes_step_state"
    __table_args__ = (
        UniqueConstraint(
            "instance_id",
            "step_id",
            "approver_user_id",
            name="uq_approval_step_state_instance_step_user",
        ),
        Index(
            "ix_approval_step_state_instance_step",
            "instance_id",
            "step_id",
        ),
    )

    instance_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_approval_routes_instance.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_approval_routes_step.id", ondelete="CASCADE"),
        nullable=False,
    )
    approver_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    decision: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StepState inst={self.instance_id} step={self.step_id} {self.decision}>"
