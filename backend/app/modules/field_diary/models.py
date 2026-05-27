# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Field Diary ORM models.

Tables (all prefixed ``oe_field_diary_``):
    oe_field_diary_entry              — header per (project, author, date)
    oe_field_diary_activity           — append-only work/delay/inspection rows
    oe_field_diary_attachment         — file metadata (storage key only)
    oe_field_module_grant             — dedicated per-project module permission
                                        table (BYPASSES standard RBAC).
    oe_field_diary_magic_link         — PIN-gated magic-link token (sha256 hash)
    oe_field_diary_session            — long-lived field session (sha256 hash)

The ``oe_field_module_grant`` table is intentionally generic — the
``module_key`` column is free-form so future field modules (timesheet,
photos, deliveries) reuse the same grant table without a schema change.
The MVP only writes ``module_key = 'field_diary'``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class DiaryEntry(Base):
    """One diary entry per project, per author, per calendar date."""

    __tablename__ = "oe_field_diary_entry"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "author_id",
            "entry_date",
            name="uq_oe_field_diary_entry_proj_author_date",
        ),
        Index(
            "ix_oe_field_diary_entry_project_status",
            "project_id",
            "status",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Plain ISO ``YYYY-MM-DD`` string — matches the legacy ``daily_diary``
    # convention and avoids a timezone trap when site clocks roll over at
    # local midnight while the server is on UTC.
    entry_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    weather: Mapped[str | None] = mapped_column(String(64), nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    headcount: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    notes_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    # draft / submitted / approved. Free-form on the DB side so future
    # statuses can land without a migration; the FSM in the service layer
    # is authoritative.
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover — debug only
        return f"<DiaryEntry {self.entry_date} author={self.author_id} ({self.status})>"


class DiaryActivity(Base):
    """Append-only activity attached to a diary entry."""

    __tablename__ = "oe_field_diary_activity"
    __table_args__ = (
        Index(
            "ix_oe_field_diary_activity_entry_type",
            "entry_id",
            "activity_type",
        ),
    )

    entry_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_field_diary_entry.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # work / delay / inspection / visit / incident — service-layer enum.
    activity_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    hours: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DiaryActivity {self.activity_type} entry={self.entry_id}>"


class DiaryAttachment(Base):
    """File metadata for an attachment to a diary entry.

    The actual bytes are stored on disk (or S3/MinIO in production) under
    the path encoded in ``storage_key``; this table holds only the
    metadata + audit fields.
    """

    __tablename__ = "oe_field_diary_attachment"
    __table_args__ = (
        Index(
            "ix_oe_field_diary_attachment_entry",
            "entry_id",
        ),
    )

    entry_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_field_diary_entry.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Filename as supplied by the client — purely informational. The
    # router never trusts this to build a path (path-traversal guard).
    filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    mime_type: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="application/octet-stream",
        server_default="application/octet-stream",
    )
    size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    # Server-derived relative path (``field_diary/attachments/<entry>_<hex><ext>``).
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DiaryAttachment {self.filename} entry={self.entry_id}>"


class FieldModuleGrant(Base):
    """Dedicated per-project field-module permission.

    Distinct from ``oe_permission`` / ``oe_role`` — a row here grants
    access to ``module_key`` on ``project_id`` for ``user_id`` regardless
    of the user's standard RBAC role. Soft-revoke is via ``revoked_at``
    so historical audit data stays available.

    Unique constraint on the active row is enforced PARTIALLY (only when
    ``revoked_at IS NULL``). On SQLite this is implemented as a partial
    index — see the migration for the exact predicate. On PostgreSQL the
    same partial index applies.
    """

    __tablename__ = "oe_field_module_grant"
    __table_args__ = (
        # Lookup hot path: "does this user have a non-revoked grant for
        # (project, module)?" — covered by the partial unique index in
        # the migration. The plain composite below is the SQLAlchemy
        # metadata hint; the *unique* part is added in the migration as
        # a partial index for portability.
        Index(
            "ix_oe_field_module_grant_lookup",
            "user_id",
            "project_id",
            "module_key",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Free-form so new field modules (timesheet / photos / deliveries)
    # can grant against the same table without a schema migration.
    module_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="field_diary",
        server_default="field_diary",
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    # Optional sunset — null = no expiry. Service layer compares against
    # UTC ``now()``.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<FieldModuleGrant user={self.user_id} project={self.project_id} "
            f"module={self.module_key} revoked={self.revoked_at is not None}>"
        )


class FieldMagicLink(Base):
    """PIN-gated one-time login token for a field session.

    Each row carries a SHA-256 hash of the URL token AND a SHA-256 hash
    of the six-digit PIN that was attached at SMS send time. Opening the
    link consumes the token (sets ``consumed_at``) and atomically opens a
    :class:`FieldSession` after the PIN is verified by the client.
    """

    __tablename__ = "oe_field_diary_magic_link"
    __table_args__ = (
        Index(
            "ix_oe_field_diary_magic_link_user_project",
            "user_id",
            "project_id",
        ),
    )

    # Owning field worker (a regular ``oe_users_user`` row — provisioned
    # by the request-magic-link endpoint if missing).
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    module_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="field_diary",
        server_default="field_diary",
    )
    phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    # SHA-256 of the URL token. The plaintext is shown to the field
    # worker exactly once via SMS and never persisted.
    token_hash: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
        index=True,
    )
    # SHA-256 of the 6-digit PIN. The plaintext is shown to the field
    # worker via the same SMS as a separate line ("PIN: 482910").
    pin_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    pin_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FieldMagicLink user={self.user_id} project={self.project_id} consumed={self.consumed_at is not None}>"


class FieldSession(Base):
    """Long-lived field-worker session.

    Scoped to a single ``(project_id, module_key)`` — once the field
    worker scans a different project's QR code they need a fresh magic
    link. Token stored as SHA-256 hash; plaintext returned to the
    client exactly once on consume.
    """

    __tablename__ = "oe_field_diary_session"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    module_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="field_diary",
        server_default="field_diary",
    )
    session_token_hash: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
        index=True,
    )
    # Pin-hash carried over from the consumed magic-link so subsequent
    # requests can present the same PIN header against the same session.
    pin_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<FieldSession user={self.user_id} project={self.project_id} "
            f"module={self.module_key} revoked={self.revoked_at is not None}>"
        )


__all__ = [
    "DiaryEntry",
    "DiaryActivity",
    "DiaryAttachment",
    "FieldMagicLink",
    "FieldModuleGrant",
    "FieldSession",
]
