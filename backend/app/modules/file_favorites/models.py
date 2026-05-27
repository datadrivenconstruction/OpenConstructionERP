# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Favourites ORM model.

Single table ``oe_file_favorite``. Polymorphic on ``(file_kind,
file_id)``; the file row's deletion is the file-manager dispatcher's
problem (no FK from ``file_id`` because the field spans 8 kinds).
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

# Mirrors the kind whitelist used by every other file_* module.
FAVORITE_KINDS: tuple[str, ...] = (
    "document",
    "photo",
    "sheet",
    "bim_model",
    "dwg_drawing",
    "takeoff",
    "report",
    "markup",
)


class FileFavorite(Base):
    """One ``user × file`` favourite row.

    ``pinned`` is a tri-state bit: an unpinned row is a *favourite*; a
    pinned row is an *elevated favourite* that sorts first in the
    Recently Viewed strip. A user can have many pinned files per
    project (no per-project pin cap — UX surfaces the top N only).
    """

    __tablename__ = "oe_file_favorite"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "file_kind",
            "file_id",
            name="uq_file_favorite_user_kind_file",
        ),
        Index(
            "ix_file_favorite_user_project",
            "user_id",
            "project_id",
        ),
        Index(
            "ix_file_favorite_kind_file",
            "file_kind",
            "file_id",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    file_id: Mapped[str] = mapped_column(String(64), nullable=False)
    pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )

    def __repr__(self) -> str:
        flag = "pinned" if self.pinned else "starred"
        return f"<FileFavorite user={self.user_id} {self.file_kind}:{self.file_id} {flag}>"
