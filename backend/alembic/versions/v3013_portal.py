# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""portal — external customer/partner portal foundation.

Creates six tables (all prefixed ``oe_portal_``) for portal users,
per-resource access rules (RLS), session tokens (sha256-hashed),
magic-links (one-time, sha256-hashed), notification feed entries,
and an append-only document-access audit log.

Portal accounts are stored separately from ``oe_users_user`` — they
never have internal-system access. All token columns store sha256 hex
digests only; plaintext is shown to inviter / portal user exactly once
and then discarded.

Idempotent — re-applying on a DB where ``Base.metadata.create_all`` has
already created the tables is a no-op.

Revision ID: v3013_portal
Revises: v2943_compliance_docs
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3013_portal"
down_revision: Union[str, Sequence[str], None] = "v3012_equipment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES: tuple[str, ...] = (
    "oe_portal_user",
    "oe_portal_access_rule",
    "oe_portal_session",
    "oe_portal_magic_link",
    "oe_portal_notification",
    "oe_portal_document_access_log",
)

_INDEXES: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
    # (table, name, cols, unique)
    ("oe_portal_user", "ix_oe_portal_user_email", ("email",), True),
    ("oe_portal_user", "ix_oe_portal_user_portal_role", ("portal_role",), False),
    ("oe_portal_user", "ix_oe_portal_user_status", ("status",), False),
    (
        "oe_portal_access_rule",
        "ix_oe_portal_access_rule_portal_user_id",
        ("portal_user_id",),
        False,
    ),
    (
        "oe_portal_access_rule",
        "ix_oe_portal_access_rule_resource",
        ("portal_user_id", "resource_type", "resource_id"),
        False,
    ),
    (
        "oe_portal_session",
        "ix_oe_portal_session_portal_user_id",
        ("portal_user_id",),
        False,
    ),
    (
        "oe_portal_session",
        "ix_oe_portal_session_session_token_hash",
        ("session_token_hash",),
        True,
    ),
    (
        "oe_portal_magic_link",
        "ix_oe_portal_magic_link_portal_user_id",
        ("portal_user_id",),
        False,
    ),
    (
        "oe_portal_magic_link",
        "ix_oe_portal_magic_link_token_hash",
        ("token_hash",),
        True,
    ),
    (
        "oe_portal_notification",
        "ix_oe_portal_notification_user_read",
        ("portal_user_id", "read_at"),
        False,
    ),
    (
        "oe_portal_document_access_log",
        "ix_oe_portal_document_access_log_portal_user_id",
        ("portal_user_id",),
        False,
    ),
)


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    index: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    if not _has_table(inspector, "oe_portal_user"):
        op.create_table(
            "oe_portal_user",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column(
                "full_name",
                sa.String(255),
                nullable=False,
                server_default="",
            ),
            sa.Column("portal_role", sa.String(32), nullable=False),
            sa.Column(
                "language",
                sa.String(10),
                nullable=False,
                server_default="en",
            ),
            sa.Column(
                "timezone",
                sa.String(64),
                nullable=False,
                server_default="UTC",
            ),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="invited",
            ),
            sa.Column(
                "invited_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "last_login_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column("password_hash", sa.String(255), nullable=True),
            sa.Column(
                "failed_login_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "locked_until",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )

    if not _has_table(inspector, "oe_portal_access_rule"):
        op.create_table(
            "oe_portal_access_rule",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "portal_user_id",
                guid_type,
                sa.ForeignKey("oe_portal_user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("resource_type", sa.String(64), nullable=False),
            sa.Column("resource_id", guid_type, nullable=False),
            sa.Column(
                "permission",
                sa.String(32),
                nullable=False,
                server_default="view",
            ),
            sa.Column(
                "granted_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column("granted_by", sa.String(36), nullable=True),
            sa.Column(
                "expires_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )

    if not _has_table(inspector, "oe_portal_session"):
        op.create_table(
            "oe_portal_session",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "portal_user_id",
                guid_type,
                sa.ForeignKey("oe_portal_user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("session_token_hash", sa.String(128), nullable=False),
            sa.Column("ip_address", sa.String(64), nullable=True),
            sa.Column("user_agent", sa.String(512), nullable=True),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "last_seen_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
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
        )

    if not _has_table(inspector, "oe_portal_magic_link"):
        op.create_table(
            "oe_portal_magic_link",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "portal_user_id",
                guid_type,
                sa.ForeignKey("oe_portal_user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("token_hash", sa.String(128), nullable=False),
            sa.Column(
                "purpose",
                sa.String(32),
                nullable=False,
                server_default="login",
            ),
            sa.Column("redirect_path", sa.String(512), nullable=True),
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
            sa.Column("created_ip", sa.String(64), nullable=True),
        )

    if not _has_table(inspector, "oe_portal_notification"):
        op.create_table(
            "oe_portal_notification",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "portal_user_id",
                guid_type,
                sa.ForeignKey("oe_portal_user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "kind",
                sa.String(64),
                nullable=False,
                server_default="general",
            ),
            sa.Column(
                "title",
                sa.String(255),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "body",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
            sa.Column("link_path", sa.String(512), nullable=True),
            sa.Column(
                "payload",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "read_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )

    if not _has_table(inspector, "oe_portal_document_access_log"):
        op.create_table(
            "oe_portal_document_access_log",
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "portal_user_id",
                guid_type,
                sa.ForeignKey("oe_portal_user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("document_type", sa.String(64), nullable=False),
            sa.Column("document_id", guid_type, nullable=False),
            sa.Column(
                "action",
                sa.String(32),
                nullable=False,
                server_default="view",
            ),
            sa.Column(
                "occurred_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column("ip_address", sa.String(64), nullable=True),
        )

    # Inspector cache is stale after CREATE TABLE.
    inspector = sa.inspect(bind)
    for table, name, cols, unique in _INDEXES:
        if not _has_index(inspector, table, name):
            try:
                op.create_index(name, table, list(cols), unique=unique)
            except sa.exc.OperationalError:
                pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table, name, _cols, _unique in _INDEXES:
        if _has_index(inspector, table, name):
            op.drop_index(name, table_name=table)

    # Drop in reverse-dependency order — log, notif, magic, session, rule, user.
    for table in reversed(_TABLES):
        if _has_table(inspector, table):
            op.drop_table(table)
