# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Comments ORM models.

Tables:
    oe_file_comment         — polymorphic threaded comment on any file
                              kind. A comment can be anchored to a PDF
                              page + normalized (x, y) coordinate so it
                              renders as a pin.
    oe_file_comment_mention — @username extractions resolved to a real
                              user, with a ``notified_at`` watermark
                              for the "unread mentions" inbox query.

Polymorphism choice
-------------------
``file_kind`` (a short string, validated against the FileKind enum at the
service layer) + ``file_id`` (a free-form string id) is used instead of
seven concrete FK columns because the eight file kinds live in seven
different tables (documents, photos, sheets, bim_models, dwg_drawings,
takeoff, reports, markups) and Postgres polymorphic FKs require either
inheritance or a join-table per kind — both significantly heavier than
the project-scoped ``(project_id, file_kind, file_id)`` index this table
ships with.

Soft delete
-----------
``DELETE /file-comments/{id}/`` replaces ``body`` with ``"[deleted]"``
and clears mention rows; the row stays so child replies retain their
thread structure. Hard-delete is intentionally not exposed — deleted-
ness is reflected in ``body`` so the UI can render a tombstone marker.
"""

import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class FileComment(Base):
    """A polymorphic threaded comment on any file kind."""

    __tablename__ = "oe_file_comment"
    __table_args__ = ()

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # FileKind enum: document | photo | sheet | bim_model | dwg_drawing |
    # takeoff | report | markup. Validated by the Pydantic schema. Stored
    # free-form to allow future kinds without a migration.
    file_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # File id is a string because some kinds (markup, takeoff annotation)
    # may use composite string ids; for plain UUID-backed kinds the
    # canonical UUID string is stored verbatim.
    file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Pre-Epic-C snapshot column (string label of the version at comment
    # time, e.g. "V01"). Retained for one release as a fallback while
    # the unified ``file_version_id`` FK below propagates through stored
    # rows. New writes populate both; reads prefer the FK and fall back
    # to the snapshot only if the FK is NULL. DO NOT drop this column
    # in this epic.
    file_version_snapshot: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Epic C: unified version-chain link. Points at the
    # ``oe_file_version`` row that was current when this comment was
    # created. NULL = legacy row written before Epic C; the UI treats
    # those as "comment on the current version" (best-effort).
    file_version_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_file_version.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        default=None,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_file_comment.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # PDF pin anchor — all three nullable: a non-PDF comment leaves them
    # NULL. anchor_x / anchor_y are normalized to [0.0, 1.0] of the page
    # bounding box so the pin survives PDF re-scales / rotations.
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anchor_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    anchor_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    resolved_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<FileComment {self.file_kind}/{self.file_id} parent={self.parent_id} resolved={self.resolved}>"


class FileCommentMention(Base):
    """A resolved @mention inside a :class:`FileComment` body.

    One row per (comment, mentioned_user). ``notified_at`` is set when
    the notification system has dispatched a digest / push for this
    mention; the "unread mentions" inbox query filters rows where the
    requesting user is the mentioned user AND ``notified_at`` is NULL
    OR ``notified_at < $threshold`` (caller-controlled).
    """

    __tablename__ = "oe_file_comment_mention"
    __table_args__ = (
        UniqueConstraint(
            "comment_id",
            "mentioned_user_id",
            name="uq_oe_file_comment_mention_comment_user",
        ),
    )

    comment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_file_comment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mentioned_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notified_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<FileCommentMention comment={self.comment_id} user={self.mentioned_user_id} notified={self.notified_at}>"
        )
