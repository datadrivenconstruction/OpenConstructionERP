# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Interface-register ORM models (multi-package coordination register).

Tables:
    oe_interface_mgmt_interface - one interface (handshake) between two parties,
                                  disciplines or work packages on a project,
                                  carrying its status, priority, type, the owning
                                  and accepting side, and the key dates.
    oe_interface_mgmt_action    - one action needed to close an interface (who
                                  does what by when), the to-do list that drives
                                  the interface to agreement.
    oe_interface_mgmt_history   - one entry in an interface's status history: who
                                  moved it, when, from which status to which, with
                                  what comment, and whether the change came from a
                                  person or from an approval-route verdict.

The register numbers are never stored: the per-status / per-priority / per-type
counts, the overdue and disputed lists, the agreed percentage, the open action
load and the per-work-package health are all derived from the rows by the pure
functions in :mod:`app.modules.interface_management.register`. Both tables
foreign-key into ``oe_projects_project`` by id only (cascade on project delete)
and never alter it; an action additionally foreign-keys into its interface
(cascade on interface delete) and carries its own ``project_id`` so every query
is project-scoped without a join.

The soft-link columns (``owner_subcontractor_id``, ``accepter_subcontractor_id``,
``rfi_id``, ``schedule_activity_id``) reference rows owned by other modules and
deliberately carry no foreign key, so this coordination register never blocks or
cascades another module's deletes. GUID primary keys, timezone-aware
``created_at`` / ``updated_at`` and calendar dates follow the platform
column-type conventions. Vocabulary columns (type, status, priority, action
status) are stored as plain strings, not DB enums, so a new value never needs a
schema migration; the allowed values are enforced at the API edge and in the pure
register core.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_types import SafeDate
from app.database import GUID, Base

# -- Interface ---------------------------------------------------------------


class InterfaceRecord(Base):
    """One interface (handshake) between two sides on a project.

    ``interface_type`` places the interface in a family (physical, functional,
    contractual, spatial, information, schedule). ``status`` tracks it through the
    lifecycle from ``identified`` to ``closed`` (with ``disputed`` and ``on_hold``
    as side states). ``owner_party`` is the side responsible for getting the
    interface agreed and ``accepter_party`` is the side that depends on it; each
    may additionally carry a soft link to a subcontractor row. The derived
    register numbers come from :mod:`app.modules.interface_management.register`,
    never from this row directly.

    The soft-link columns (``owner_subcontractor_id``,
    ``accepter_subcontractor_id``, ``rfi_id``, ``schedule_activity_id``)
    reference rows owned by other modules and deliberately carry no foreign key.
    """

    __tablename__ = "oe_interface_mgmt_interface"
    __table_args__ = (
        Index("ix_interface_mgmt_interface_project", "project_id"),
        Index("ix_interface_mgmt_interface_project_status", "project_id", "status"),
        Index("ix_interface_mgmt_interface_project_owner", "project_id", "owner_subcontractor_id"),
        UniqueConstraint(
            "project_id",
            "reference",
            name="uq_interface_mgmt_project_reference",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    reference: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The owning side (responsible for agreeing the interface) and its optional
    # soft link to a subcontractor row (no FK - see class docstring).
    owner_party: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_subcontractor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # The accepting side (depends on the interface) and its optional soft link.
    accepter_party: Mapped[str | None] = mapped_column(String(255), nullable=True)
    accepter_subcontractor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    discipline_from: Mapped[str | None] = mapped_column(String(60), nullable=True)
    discipline_to: Mapped[str | None] = mapped_column(String(60), nullable=True)
    work_package_from: Mapped[str | None] = mapped_column(String(120), nullable=True)
    work_package_to: Mapped[str | None] = mapped_column(String(120), nullable=True)
    interface_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="identified",
        server_default="identified",
    )
    priority: Mapped[str | None] = mapped_column(String(20), nullable=True)
    need_by_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    agreed_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    closed_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    # Soft link to a Request-for-Information row (stored as its string id, no FK).
    rfi_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    schedule_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    actions: Mapped[list["InterfaceAction"]] = relationship(
        "app.modules.interface_management.models.InterfaceAction",
        back_populates="interface",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<InterfaceRecord {self.reference!r} ({self.status}) project={self.project_id}>"


# -- Action ------------------------------------------------------------------


class InterfaceAction(Base):
    """One action needed to close an interface (who does what by when).

    ``status`` tracks the action from ``open`` to ``done`` (or ``cancelled``).
    The action carries its own ``project_id`` (copied from its interface's
    project) so every listing and rollup query is project-scoped without a join,
    and it foreign-keys into its interface so it is deleted with the interface.
    Only the open actions count towards an interface's open action load in the
    pure register core.
    """

    __tablename__ = "oe_interface_mgmt_action"
    __table_args__ = (
        Index("ix_interface_mgmt_action_project", "project_id"),
        Index("ix_interface_mgmt_action_interface", "interface_id"),
        Index("ix_interface_mgmt_action_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    interface_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_interface_mgmt_interface.id", ondelete="CASCADE"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    action_party: Mapped[str | None] = mapped_column(String(255), nullable=True)
    due_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="open",
        server_default="open",
    )
    completed_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    interface: Mapped["InterfaceRecord"] = relationship(
        "app.modules.interface_management.models.InterfaceRecord",
        back_populates="actions",
    )

    def __repr__(self) -> str:
        return f"<InterfaceAction {self.status} interface={self.interface_id}>"


# -- Status history ----------------------------------------------------------


class InterfaceHistoryEntry(Base):
    """One entry in an interface's status history.

    Written by the service in the same transaction as the change it records, so
    an interface can never move without leaving a trace. ``event`` names what
    happened (``created``, ``status_changed``, ``approval_requested``,
    ``approval_approved``, ``approval_rejected``, ``approval_cancelled``);
    ``from_status`` / ``to_status`` carry the move (equal when the event did not
    move the status, e.g. an approval that was requested or rejected).
    ``approval_instance_id`` is a soft link to the approval-routes instance the
    entry came from, with no foreign key, like every cross-module link here.

    Foreign keys are named explicitly: the platform naming convention would spell
    them out past PostgreSQL's 63-character identifier limit.
    """

    __tablename__ = "oe_interface_mgmt_history"
    __table_args__ = (
        Index("ix_interface_mgmt_history_project", "project_id"),
        Index("ix_interface_mgmt_history_interface", "interface_id", "changed_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE", name="fk_interface_mgmt_history_project"),
        nullable=False,
    )
    interface_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey(
            "oe_interface_mgmt_interface.id",
            ondelete="CASCADE",
            name="fk_interface_mgmt_history_interface",
        ),
        nullable=False,
    )
    event: Mapped[str] = mapped_column(String(30), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_instance_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<InterfaceHistoryEntry {self.event} {self.from_status}->{self.to_status} interface={self.interface_id}>"
        )
