# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Approvals (W8) ORM models.

Tables
------
* ``oe_file_approval_workflow`` — one submission. ``status`` is the
  workflow-level decision; it flips to ``approved`` only when every
  step in ``sort_order`` order has ``decision='approved'``. A single
  ``rejected`` decision short-circuits the workflow to ``rejected``.
* ``oe_file_approval_step``    — per-approver row, ``sort_order``-keyed.
* ``oe_file_stamp_template``   — reusable stamp definitions (SVG +
  default colour + text). ``project_id=NULL`` means "global / system"
  and is seeded by the migration.
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base

# Lifecycle states for the whole workflow.
WORKFLOW_STATUSES: tuple[str, ...] = (
    "in_review",
    "approved",
    "rejected",
    "withdrawn",
)

# Per-step decision vocabulary.
STEP_DECISIONS: tuple[str, ...] = (
    "pending",
    "approved",
    "rejected",
    "delegated",
)


class FileStampTemplate(Base):
    """A reusable stamp definition (svg + colour + text).

    ``project_id`` is nullable: ``NULL`` rows are global / system seeds
    (``For Construction``, ``Approved``, ``Revise & Resubmit``,
    ``Rejected``). Project-scoped rows override globals by name.

    Name is ``File``-prefixed to avoid colliding with the existing
    ``StampTemplate`` class in :mod:`app.modules.markups.models` —
    SQLAlchemy's declarative registry deduplicates by short class name
    when string-based ``relationship`` lookups are used elsewhere.
    """

    __tablename__ = "oe_file_stamp_template"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "name",
            name="uq_oe_file_stamp_template_project_id_name",
        ),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    text: Mapped[str] = mapped_column(String(255), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#16a34a", server_default="#16a34a")
    svg_template: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    def __repr__(self) -> str:
        scope = "global" if self.project_id is None else str(self.project_id)
        return f"<StampTemplate '{self.name}' ({scope})>"


class FileApprovalWorkflow(Base):
    """One approval submission for a single file.

    Renamed from ``ApprovalWorkflow`` to avoid colliding with the
    workflow-engine class of the same name in the
    :mod:`app.modules.enterprise_workflows` module — SQLAlchemy's
    declarative registry dedupes by short class name when string-based
    relationship lookups are used across modules.
    """

    __tablename__ = "oe_file_approval_workflow"
    __table_args__ = (
        Index(
            "ix_oe_file_approval_workflow_project_status",
            "project_id",
            "status",
        ),
        Index(
            "ix_oe_file_approval_workflow_file",
            "file_kind",
            "file_id",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    file_id: Mapped[str] = mapped_column(String(64), nullable=False)
    file_version_snapshot: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    submitted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="in_review",
        server_default="in_review",
    )
    final_decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    final_decision_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    stamp_template_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_file_stamp_template.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    stamped_artifact_path: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    steps: Mapped[list[FileApprovalStep]] = relationship(
        "FileApprovalStep",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="FileApprovalStep.sort_order",
    )

    def __repr__(self) -> str:
        return f"<FileApprovalWorkflow {self.file_kind}/{self.file_id} ({self.status})>"


class FileApprovalStep(Base):
    """One ordered step inside a :class:`FileApprovalWorkflow`."""

    __tablename__ = "oe_file_approval_step"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "sort_order",
            name="uq_oe_file_approval_step_workflow_id_sort_order",
        ),
        Index(
            "ix_oe_file_approval_step_approver",
            "approver_id",
            "decision",
        ),
    )

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_file_approval_workflow.id", ondelete="CASCADE"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_label: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    decision: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    workflow: Mapped[FileApprovalWorkflow] = relationship("FileApprovalWorkflow", back_populates="steps")
