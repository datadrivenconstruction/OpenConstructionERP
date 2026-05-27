# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Versioning ORM models.

Tables:
    oe_file_version — polymorphic version chain (no FK to the file
                      table because there are 8 kinds; ``file_id`` is
                      stored as ``String`` and grouped by
                      ``canonical_name`` within ``project_id`` +
                      ``file_kind``).
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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

# Canonical set of file-kind labels the file manager exposes. The
# field is open ``String(32)`` in the DB so a future kind doesn't
# require a migration; this tuple is the validated whitelist surfaced
# to API consumers.
FILE_KINDS: tuple[str, ...] = (
    "document",
    "photo",
    "sheet",
    "bim_model",
    "dwg_drawing",
    "takeoff",
    "report",
    "markup",
)


class FileVersion(Base):
    """One snapshot in a file's version chain.

    Polymorphic: ``file_id`` is the id of the row in the kind's own
    table (``oe_documents_document``, ``oe_documents_photo``, …).
    The chain key is ``(project_id, file_kind, canonical_name)``.
    Only one row per chain has ``is_current=True``.
    """

    __tablename__ = "oe_file_version"
    __table_args__ = (
        Index(
            "ix_file_version_chain",
            "project_id",
            "file_kind",
            "canonical_name",
            "is_current",
        ),
        Index("ix_file_version_file_id", "file_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    file_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        default=None,
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, default=None)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)

    def __repr__(self) -> str:
        return (
            f"<FileVersion {self.canonical_name} V{self.version_number:02d} "
            f"({self.file_kind}, current={self.is_current})>"
        )
