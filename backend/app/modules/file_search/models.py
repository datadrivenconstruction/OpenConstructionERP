# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File search ORM models.

Table:
    oe_file_search_index — one row per (project, file_kind, file_id);
                            extracted full text + OCR engine metadata.
                            On Postgres an additional ``tsv_vector``
                            generated column (added by the migration)
                            powers ranked search via ``to_tsvector``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
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


class FileSearchIndex(Base):
    """Full-text search index row for a single file.

    The row is **idempotent on (project_id, file_kind, file_id)**:
    re-indexing the same file just overwrites ``content_text`` and bumps
    ``indexed_at``. ``content_text`` is hard-capped at 1 MB upstream so
    a single pathological PDF cannot inflate the table.
    """

    __tablename__ = "oe_file_search_index"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "file_kind",
            "file_id",
            name="uq_file_search_index_project_kind_file",
        ),
        Index("ix_file_search_index_project_kind", "project_id", "file_kind"),
        Index("ix_file_search_index_file", "file_kind", "file_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    file_id: Mapped[str] = mapped_column(String(64), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    ocr_engine: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True, default=None)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<FileSearchIndex project={self.project_id} kind={self.file_kind} file_id={self.file_id}>"
