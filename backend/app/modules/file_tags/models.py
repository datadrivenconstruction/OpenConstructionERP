# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File tag ORM models.

Tables:
    oe_file_tag             — the project-scoped tag definition.
    oe_file_tag_assignment  — many-to-many anchor that attaches a tag to
                              a single ``(file_kind, file_id)`` pair.

Cascade rules:
    * Deleting the tag cascades to every assignment.
    * Deleting the underlying file is the responsibility of the
      file-manager dispatcher (it calls the bulk-unassign endpoint per
      kind on delete) — there is no FK from ``file_id`` to a specific
      table because the field is polymorphic.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class FileTag(Base):
    """A reusable, project-scoped tag."""

    __tablename__ = "oe_file_tag"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "name",
            name="uq_file_tag_project_name",
        ),
        Index("ix_file_tag_project_category", "project_id", "category"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    color: Mapped[str] = mapped_column(
        String(7),
        nullable=False,
        default="#94a3b8",
        server_default="#94a3b8",
    )
    category: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    assignments: Mapped[list[FileTagAssignment]] = relationship(
        back_populates="tag",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<FileTag {self.name} project={self.project_id}>"


class FileTagAssignment(Base):
    """A single ``tag → (file_kind, file_id)`` link."""

    __tablename__ = "oe_file_tag_assignment"
    __table_args__ = (
        UniqueConstraint(
            "tag_id",
            "file_kind",
            "file_id",
            name="uq_file_tag_assignment_tag_kind_file",
        ),
        Index("ix_file_tag_assignment_kind_file", "file_kind", "file_id"),
    )

    tag_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_file_tag.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    file_id: Mapped[str] = mapped_column(String(64), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    tag: Mapped[FileTag] = relationship(back_populates="assignments")

    def __repr__(self) -> str:
        return f"<FileTagAssignment tag={self.tag_id} kind={self.file_kind} file_id={self.file_id}>"
