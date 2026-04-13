"""Collaboration-lock ORM models.

Tables:
    oe_collab_lock — pessimistic per-entity soft lock.

A lock is a row uniquely keyed by ``(entity_type, entity_id)``.  The
holder renews it with ``heartbeat_at`` and a new ``expires_at`` every
~15 seconds.  When ``expires_at`` passes, the row is swept by the
background task in :mod:`sweeper` so a disconnected tab can never hold
an entity hostage.

The table is intentionally *append-in-place*: there is no history.  If
you need an audit trail of who edited a row, use the existing
collaboration comments / event bus — the lock table is state, not log.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class CollabLock(Base):
    """One active soft lock per ``(entity_type, entity_id)`` pair."""

    __tablename__ = "oe_collab_lock"
    __table_args__ = (
        UniqueConstraint(
            "entity_type", "entity_id", name="uq_collab_lock_entity"
        ),
        Index("ix_collab_lock_expires", "expires_at"),
        Index("ix_collab_lock_user", "user_id"),
        Index("ix_collab_lock_entity_lookup", "entity_type", "entity_id"),
    )

    # Multi-tenant scope.  Nullable because the current user model has no
    # organisation column — when one is added, the service fills it in.
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), nullable=True, index=True
    )

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
    )

    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return (
            f"<CollabLock {self.entity_type}/{self.entity_id} "
            f"by user={self.user_id} expires={self.expires_at.isoformat()}>"
        )
