"""v1.9.1 -- add document_ids JSON column to oe_meetings_meeting.

Adds ``document_ids`` (JSON array) to ``oe_meetings_meeting`` so a meeting
can cross-link to one or more Document rows (same pattern as FieldReports
and Correspondence). Idempotent: inspects the live schema first and only
runs ``ADD COLUMN`` when the column is absent.

Revision ID: v191_meetings_document_ids
Revises: a1b2c3d4e5f6
Create Date: 2026-04-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v191_meetings_document_ids"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "oe_meetings_meeting"
COLUMN_NAME = "document_ids"


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(col["name"] == column for col in insp.get_columns(table))


def upgrade() -> None:
    if not _table_exists(TABLE_NAME):
        return
    if _has_column(TABLE_NAME, COLUMN_NAME):
        return
    op.add_column(
        TABLE_NAME,
        sa.Column(
            COLUMN_NAME,
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    if not _has_column(TABLE_NAME, COLUMN_NAME):
        return
    with op.batch_alter_table(TABLE_NAME) as batch_op:
        batch_op.drop_column(COLUMN_NAME)
