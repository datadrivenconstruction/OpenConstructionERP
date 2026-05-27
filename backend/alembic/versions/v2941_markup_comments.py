# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""markups — threaded comments table.

Adds ``oe_markups_comment`` so users can attach threaded discussion
threads to any drawing markup. Comments are flat per markup (no
nested replies in v1); authorisation lives in the router layer and
falls back to the parent markup's project membership.

Idempotent — re-applying on a DB where ``Base.metadata.create_all``
has already created the table is a no-op.

Revision ID: v2941_markup_comments
Revises: v2940_assemblies_resource_type
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v2941_markup_comments"
down_revision: Union[str, Sequence[str], None] = "v2940_assemblies_resource_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_markups_comment"

_INDEXES: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    # (name, cols, unique)
    ("ix_markups_comment_markup_id", ("markup_id",), False),
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
                "markup_id",
                guid_type,
                sa.ForeignKey("oe_markups_markup.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("user_id", sa.String(255), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
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
