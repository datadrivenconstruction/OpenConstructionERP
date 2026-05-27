# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""field_diary: MVP daily diary + dedicated module-grant table.

Six tables for the Field Diary module (task #113 / Epic F):

* ``oe_field_diary_entry``         — header (project, author, date, status)
* ``oe_field_diary_activity``      — append-only activity rows
* ``oe_field_diary_attachment``    — file metadata
* ``oe_field_module_grant``        — dedicated per-project permission
                                     table that BYPASSES the standard RBAC
                                     stack. Reused by future field modules
                                     (timesheet / photos / deliveries).
* ``oe_field_diary_magic_link``    — PIN-gated one-time magic-link token
* ``oe_field_diary_session``       — long-lived field-worker session

A partial unique index on ``oe_field_module_grant`` enforces "one live
grant per (user, project, module)" while still allowing historical
revoked rows to coexist. SQLite supports partial indexes (3.8+);
PostgreSQL has supported them for ever.

Idempotent (checks ``inspector.get_table_names``). Mirrors v3132 style
so the lock-cascade regression (Python ``default=`` ignored by
``create_all``) can't bite — every NOT NULL column carries a
``server_default``.

Revision ID: v3133_field_diary_init
Revises: v3132_formwork_init
Create Date: 2026-05-25
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3133_field_diary_init"
down_revision: Union[str, Sequence[str], None] = "v3132_formwork_init"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ENTRY = "oe_field_diary_entry"
_ACTIVITY = "oe_field_diary_activity"
_ATTACHMENT = "oe_field_diary_attachment"
_GRANT = "oe_field_module_grant"
_MAGIC = "oe_field_diary_magic_link"
_SESSION = "oe_field_diary_session"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _existing_indexes(
    inspector: sa.engine.reflection.Inspector,
    table: str,
) -> set[str]:
    if not _has_table(inspector, table):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── oe_field_diary_entry ──────────────────────────────────────────
    if not _has_table(inspector, _ENTRY):
        op.create_table(
            _ENTRY,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "author_id",
                sa.String(36),
                sa.ForeignKey("oe_users_user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("entry_date", sa.String(10), nullable=False),
            sa.Column("weather", sa.String(64), nullable=True),
            sa.Column("temperature_c", sa.Numeric(6, 2), nullable=True),
            sa.Column(
                "headcount",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("notes_md", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="draft",
            ),
            sa.Column(
                "submitted_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "approved_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "approved_by",
                sa.String(36),
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.UniqueConstraint(
                "project_id",
                "author_id",
                "entry_date",
                name="uq_oe_field_diary_entry_proj_author_date",
            ),
        )
        existing_ix = _existing_indexes(inspector, _ENTRY)
        for ix_name, cols in (
            (f"ix_{_ENTRY}_project_id", ["project_id"]),
            (f"ix_{_ENTRY}_author_id", ["author_id"]),
            (f"ix_{_ENTRY}_entry_date", ["entry_date"]),
            (
                "ix_oe_field_diary_entry_project_status",
                ["project_id", "status"],
            ),
        ):
            if ix_name not in existing_ix:
                op.create_index(ix_name, _ENTRY, cols)

    # ── oe_field_diary_activity ───────────────────────────────────────
    if not _has_table(inspector, _ACTIVITY):
        op.create_table(
            _ACTIVITY,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "entry_id",
                sa.String(36),
                sa.ForeignKey(
                    f"{_ENTRY}.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("activity_type", sa.String(32), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("hours", sa.Numeric(6, 2), nullable=True),
            sa.Column("location", sa.String(255), nullable=True),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "ended_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )
        existing_ix = _existing_indexes(inspector, _ACTIVITY)
        for ix_name, cols in (
            (f"ix_{_ACTIVITY}_entry_id", ["entry_id"]),
            (f"ix_{_ACTIVITY}_activity_type", ["activity_type"]),
            (
                "ix_oe_field_diary_activity_entry_type",
                ["entry_id", "activity_type"],
            ),
        ):
            if ix_name not in existing_ix:
                op.create_index(ix_name, _ACTIVITY, cols)

    # ── oe_field_diary_attachment ─────────────────────────────────────
    if not _has_table(inspector, _ATTACHMENT):
        op.create_table(
            _ATTACHMENT,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "entry_id",
                sa.String(36),
                sa.ForeignKey(f"{_ENTRY}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "filename",
                sa.String(255),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "mime_type",
                sa.String(120),
                nullable=False,
                server_default="application/octet-stream",
            ),
            sa.Column(
                "size_bytes",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("storage_key", sa.String(512), nullable=False),
            sa.Column(
                "uploaded_by",
                sa.String(36),
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        existing_ix = _existing_indexes(inspector, _ATTACHMENT)
        for ix_name, cols in (
            (f"ix_{_ATTACHMENT}_entry_id", ["entry_id"]),
            ("ix_oe_field_diary_attachment_entry", ["entry_id"]),
        ):
            if ix_name not in existing_ix:
                op.create_index(ix_name, _ATTACHMENT, cols)

    # ── oe_field_module_grant ─────────────────────────────────────────
    if not _has_table(inspector, _GRANT):
        op.create_table(
            _GRANT,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "user_id",
                sa.String(36),
                sa.ForeignKey("oe_users_user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "module_key",
                sa.String(64),
                nullable=False,
                server_default="field_diary",
            ),
            sa.Column(
                "granted_by",
                sa.String(36),
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "granted_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "expires_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "revoked_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
        existing_ix = _existing_indexes(inspector, _GRANT)
        for ix_name, cols in (
            (f"ix_{_GRANT}_user_id", ["user_id"]),
            (f"ix_{_GRANT}_project_id", ["project_id"]),
            (
                "ix_oe_field_module_grant_lookup",
                ["user_id", "project_id", "module_key"],
            ),
        ):
            if ix_name not in existing_ix:
                op.create_index(ix_name, _GRANT, cols)

        # Partial unique index — "one live grant per tuple". Both SQLite
        # (≥ 3.8) and PostgreSQL honour ``CREATE UNIQUE INDEX ... WHERE``.
        # Alembic's high-level ``create_index(unique=True, sqlite_where=...)``
        # quietly drops the WHERE clause on some SQLite combinations, so
        # issue the DDL directly to be portable.
        try:
            op.execute(
                sa.text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_oe_field_module_grant_live "
                    f"ON {_GRANT} (user_id, project_id, module_key) "
                    "WHERE revoked_at IS NULL"
                )
            )
        except sa.exc.OperationalError:
            # Very old SQLite without partial-index support — fall back to
            # a plain composite (uniqueness still enforced at the service
            # layer by ``get_active()``).
            pass

    # ── oe_field_diary_magic_link ─────────────────────────────────────
    if not _has_table(inspector, _MAGIC):
        op.create_table(
            _MAGIC,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "user_id",
                sa.String(36),
                sa.ForeignKey("oe_users_user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "module_key",
                sa.String(64),
                nullable=False,
                server_default="field_diary",
            ),
            sa.Column(
                "phone",
                sa.String(40),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "token_hash",
                sa.String(128),
                nullable=False,
                unique=True,
            ),
            sa.Column("pin_hash", sa.String(128), nullable=False),
            sa.Column(
                "pin_attempts",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "expires_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "consumed_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
        existing_ix = _existing_indexes(inspector, _MAGIC)
        for ix_name, cols in (
            (f"ix_{_MAGIC}_user_id", ["user_id"]),
            (f"ix_{_MAGIC}_project_id", ["project_id"]),
            (f"ix_{_MAGIC}_token_hash", ["token_hash"]),
            (
                "ix_oe_field_diary_magic_link_user_project",
                ["user_id", "project_id"],
            ),
        ):
            if ix_name not in existing_ix:
                op.create_index(ix_name, _MAGIC, cols)

    # ── oe_field_diary_session ────────────────────────────────────────
    if not _has_table(inspector, _SESSION):
        op.create_table(
            _SESSION,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "user_id",
                sa.String(36),
                sa.ForeignKey("oe_users_user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "module_key",
                sa.String(64),
                nullable=False,
                server_default="field_diary",
            ),
            sa.Column(
                "session_token_hash",
                sa.String(128),
                nullable=False,
                unique=True,
            ),
            sa.Column("pin_hash", sa.String(128), nullable=False),
            sa.Column(
                "expires_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "revoked_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "last_seen_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
        existing_ix = _existing_indexes(inspector, _SESSION)
        for ix_name, cols in (
            (f"ix_{_SESSION}_user_id", ["user_id"]),
            (f"ix_{_SESSION}_project_id", ["project_id"]),
            (f"ix_{_SESSION}_session_token_hash", ["session_token_hash"]),
        ):
            if ix_name not in existing_ix:
                op.create_index(ix_name, _SESSION, cols)


def downgrade() -> None:
    """Drop all six tables in the inverse FK order."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table in (
        _SESSION,
        _MAGIC,
        _ATTACHMENT,
        _ACTIVITY,
        _ENTRY,
        _GRANT,
    ):
        if _has_table(inspector, table):
            existing_ix = _existing_indexes(inspector, table)
            for ix in list(existing_ix):
                try:
                    op.drop_index(ix, table_name=table)
                except sa.exc.OperationalError:
                    pass
            op.drop_table(table)
