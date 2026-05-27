# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""documents — password-protected share-link table.

Adds ``oe_documents_share_link`` so file owners can mint a 32-char
URL-safe token with an optional bcrypt-hashed password + expiry that
lets a recipient download a single document without an account.

Idempotent — re-applying on a DB where ``Base.metadata.create_all``
has already created the table is a no-op.

Revision ID: v2939_document_share_links
Revises: v2938_documents_activity
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v2939_document_share_links"
down_revision: Union[str, Sequence[str], None] = "v2938_documents_activity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_documents_share_link"

_INDEXES: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    # (name, cols, unique)
    ("ix_documents_share_link_token", ("token",), True),
    ("ix_documents_share_link_document_id", ("document_id",), False),
    ("ix_documents_share_link_revoked", ("revoked",), False),
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
    # Mirror the GUID() TypeDecorator behaviour: VARCHAR(36) on SQLite,
    # native UUID on PostgreSQL. Matches the activity table pattern.
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    if not _has_table(inspector, _TABLE):
        op.create_table(
            _TABLE,
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
                "document_id",
                guid_type,
                sa.ForeignKey("oe_documents_document.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("token", sa.String(64), nullable=False),
            sa.Column("password_hash", sa.String(255), nullable=True),
            sa.Column(
                "expires_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "created_by",
                guid_type,
                sa.ForeignKey("oe_users_user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "download_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "revoked",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0") if is_sqlite else sa.text("false"),
            ),
        )

    # Inspector cache is stale after CREATE TABLE.
    inspector = sa.inspect(bind)
    for name, cols, unique in _INDEXES:
        if not _has_index(inspector, _TABLE, name):
            op.create_index(name, _TABLE, list(cols), unique=unique)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        return

    for name, _cols, _unique in _INDEXES:
        if _has_index(inspector, _TABLE, name):
            op.drop_index(name, table_name=_TABLE)

    op.drop_table(_TABLE)
