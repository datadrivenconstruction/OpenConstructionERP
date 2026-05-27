# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Saved Views ORM models.

Tables:
    oe_file_saved_view — a named filter snapshot for the /files screen.

The view stores the FilterSnapshot inline as JSON so the schema does
not need to grow whenever the file manager learns a new filter knob.
``id`` / ``created_at`` / ``updated_at`` are inherited from
:class:`app.database.Base`.

Scope rules
-----------
* ``user_id`` is always the owner.
* ``project_id`` is **nullable**. NULL means "global view across every
  project the user can access" — applied automatically on the
  file-manager landing page before a project is chosen.
* ``is_shared`` is opt-in: when true, project members may *read* the
  view in their saved-views rail (but can never edit it; they can
  always duplicate to their own list).
* ``(user_id, project_id, name)`` is unique so the same person cannot
  accidentally create two views called "Drawings" in the same project.

Pinned views float to the top; ties broken by ``sort_order`` then by
``last_used_at`` desc so the "most useful right now" view is at hand.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class FileSavedView(Base):
    """A named, serialised filter snapshot for the /files screen."""

    __tablename__ = "oe_file_saved_view"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "project_id",
            "name",
            name="uq_file_saved_view_user_proj_name",
        ),
        Index("ix_file_saved_view_user", "user_id"),
        Index("ix_file_saved_view_project", "project_id"),
        Index("ix_file_saved_view_pinned", "is_pinned"),
    )

    # FK to user (always present — view always belongs to someone).
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    # FK to project (nullable — NULL means "global across all
    # accessible projects" / cross-project saved view).
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Optional lucide-react icon name (e.g. ``clipboard-list``, ``image``).
    icon: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    # Serialised FilterSnapshot. Free-form on purpose — when the file
    # manager learns a new filter we don't need a schema migration to
    # persist it.
    filter_json: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    is_shared: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    # Usage telemetry — bumped via POST /{id}/use/. The frontend rail
    # surfaces ``use_count`` as a soft badge so the user can spot which
    # views they actually rely on.
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    use_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    def __repr__(self) -> str:  # pragma: no cover — debug helper
        return f"<FileSavedView {self.name!r} user={self.user_id} project={self.project_id} pinned={self.is_pinned}>"
