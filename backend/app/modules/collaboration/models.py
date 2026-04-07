"""Collaboration ORM models.

Tables:
    oe_collaboration_comment   — threaded comments on any entity
    oe_collaboration_mention   — @mentions within comments
    oe_collaboration_viewpoint — spatial viewpoints (PDF section, BIM camera, etc.)
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class Comment(Base):
    """Threaded comment attached to any entity."""

    __tablename__ = "oe_collaboration_comment"
    __table_args__ = (
        Index("ix_collab_comment_entity", "entity_type", "entity_id"),
    )

    entity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    comment_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="comment", server_default="comment"
    )
    parent_comment_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_collaboration_comment.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    mentions: Mapped[list["CommentMention"]] = relationship(
        back_populates="comment",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    replies: Mapped[list["Comment"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    parent: Mapped["Comment | None"] = relationship(
        back_populates="replies",
        remote_side="Comment.id",
        lazy="selectin",
    )
    viewpoints: Mapped[list["Viewpoint"]] = relationship(
        back_populates="comment",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Comment {self.id} on {self.entity_type}/{self.entity_id}>"


class CommentMention(Base):
    """An @mention of a user within a comment."""

    __tablename__ = "oe_collaboration_mention"

    comment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_collaboration_comment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mentioned_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    mention_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="at_notify"
    )

    # Relationships
    comment: Mapped[Comment] = relationship(back_populates="mentions")

    def __repr__(self) -> str:
        return f"<CommentMention user={self.mentioned_user_id} in comment={self.comment_id}>"


class Viewpoint(Base):
    """A spatial viewpoint linked to an entity and optionally to a comment.

    Stores camera position, bounding box, PDF region, or any spatial reference
    that helps locate context for a discussion or annotation.
    """

    __tablename__ = "oe_collaboration_viewpoint"
    __table_args__ = (
        Index("ix_collab_viewpoint_entity", "entity_type", "entity_id"),
    )

    entity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    viewpoint_type: Mapped[str] = mapped_column(String(50), nullable=False)
    data: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        GUID(), nullable=False, index=True
    )
    comment_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_collaboration_comment.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    comment: Mapped[Comment | None] = relationship(back_populates="viewpoints")

    def __repr__(self) -> str:
        return f"<Viewpoint {self.id} ({self.viewpoint_type}) on {self.entity_type}/{self.entity_id}>"
