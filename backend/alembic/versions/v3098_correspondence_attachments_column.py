"""correspondence_attachments_column

Adds `attachments JSON NOT NULL DEFAULT []` to `oe_correspondence_correspondence`
so R4-W11's POST /{id}/attachments/ endpoint can write to existing prod DBs
without crashing on a missing column.

Revision ID: v3098
Revises: v3097_dwg_takeoff_decimal_quantities
Create Date: 2026-05-21 23:51:36.155297
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3098"
down_revision: Union[str, None] = "v3097_dwg_takeoff_decimal_quantities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_correspondence_correspondence"
_COLUMN = "attachments"


def _column_exists(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    if _column_exists(bind, _TABLE, _COLUMN):
        return
    op.add_column(
        _TABLE,
        sa.Column(
            _COLUMN,
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _column_exists(bind, _TABLE, _COLUMN):
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column(_COLUMN)
