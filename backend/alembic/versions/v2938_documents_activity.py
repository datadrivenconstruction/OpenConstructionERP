# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""documents — per-file activity log table.

Adds ``oe_documents_activity`` so the /files preview pane can render a
per-document audit timeline (uploaded / renamed / downloaded / deleted /
cde_state_changed). The table is write-only at the API layer; deletes
flow through the ``ON DELETE CASCADE`` on the parent document.

Idempotent — re-applying on a DB where ``Base.metadata.create_all`` has
already created the table is a no-op.

Revision ID: v2938_documents_activity
Revises: v2937_rfi_priority_discipline
Create Date: 2026-05-11
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v2938_documents_activity"
down_revision: Union[str, Sequence[str], None] = "v2937_rfi_priority_discipline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_documents_activity"

_INDEXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ix_oe_documents_activity_document_id", ("document_id",)),
    ("ix_documents_activity_created_at", ("created_at",)),
    ("ix_documents_activity_doc_created", ("document_id", "created_at")),
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
    # native UUID on PostgreSQL. Keeps existing GUID columns happy and
    # avoids a downstream UUID-cast issue in JSON serialization.
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
            sa.Column("user_id", sa.String(36), nullable=True),
            sa.Column("action", sa.String(40), nullable=False),
            sa.Column(
                "meta",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )

    # Inspector cache is stale after CREATE TABLE.
    inspector = sa.inspect(bind)
    for name, cols in _INDEXES:
        if not _has_index(inspector, _TABLE, name):
            op.create_index(name, _TABLE, list(cols))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        return

    for name, _cols in _INDEXES:
        if _has_index(inspector, _TABLE, name):
            op.drop_index(name, table_name=_TABLE)

    op.drop_table(_TABLE)
