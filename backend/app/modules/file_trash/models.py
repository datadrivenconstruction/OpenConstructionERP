# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Trash ORM model.

Single table ``oe_file_trash`` holds soft-deleted rows from any of the
8 file-kind tables. The original row is removed and its full payload
JSON-snapshotted into ``payload_json`` so restore is loss-less.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


def _default_restore_token() -> str:
    """Generate a high-entropy restore token (24 url-safe chars)."""
    return secrets.token_urlsafe(18)


class FileTrash(Base):
    """One soft-deleted file from any of the 8 kind tables."""

    __tablename__ = "oe_file_trash"
    __table_args__ = (
        Index("ix_file_trash_project_trashed", "project_id", "trashed_at"),
        Index("ix_file_trash_origin", "original_kind", "original_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    original_id: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    payload_json: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    trashed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trashed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    restored_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    restore_token: Mapped[str] = mapped_column(String(64), nullable=False, default=_default_restore_token)

    def __repr__(self) -> str:
        return (
            f"<FileTrash {self.original_kind}:{self.original_id} "
            f"trashed_at={self.trashed_at.isoformat() if self.trashed_at else None}>"
        )

    @property
    def file_size(self) -> int:
        """Best-effort byte count pulled from the snapshot payload."""
        for key in ("file_size", "size_bytes"):
            val = self.payload_json.get(key) if isinstance(self.payload_json, dict) else None
            if isinstance(val, int):
                return val
        return 0
