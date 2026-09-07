"""add_co_rejected_fields

Inspector-guarded, so re-running against an already-migrated database is a
no-op. It was not, and that was measured rather than suspected: the boot path
materialises the whole schema with ``Base.metadata.create_all`` before anything
reads ``alembic_version``, so on an install that has ever started, both columns
below already exist. Replaying the chain over such a database died here with

    (psycopg2.errors.DuplicateColumn) column "rejected_by" of relation
    "oe_changeorders_order" already exists

and because PostgreSQL runs DDL inside a transaction, that rolled back the whole
upgrade rather than this one revision. ``alembic_version`` did not move and every
later revision was skipped along with its backfills, so an operator on an old
install could never catch up and each attempt failed in the same place.

The guard changes nothing for a database where the columns are absent.

Revision ID: 24f9595e16d0
Revises: fee2e323c50c
Create Date: 2026-04-19 10:10:54.732981

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "24f9595e16d0"
down_revision: Union[str, None] = "fee2e323c50c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "oe_changeorders_order"


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
    """Add rejected_by / rejected_at columns to change orders.

    BUG-351: previously the reject path wrote the rejector's user-id into
    ``approved_by``, which caused audit UIs to attribute the rejection to
    the approver role. Splitting rejection into its own columns lets the
    audit trail reflect reality and keeps ``approved_by`` semantically
    pure (it now only names someone who actually approved).
    """
    if not _table_exists(TABLE_NAME):
        return

    # Resolved before the batch context opens, so the answers describe the
    # live table rather than a schema the batch has already started editing.
    add_rejected_by = not _has_column(TABLE_NAME, "rejected_by")
    add_rejected_at = not _has_column(TABLE_NAME, "rejected_at")
    if not (add_rejected_by or add_rejected_at):
        return

    with op.batch_alter_table(TABLE_NAME) as batch:
        if add_rejected_by:
            batch.add_column(sa.Column("rejected_by", sa.String(length=36), nullable=True))
        if add_rejected_at:
            batch.add_column(sa.Column("rejected_at", sa.String(length=20), nullable=True))


def downgrade() -> None:
    if not _table_exists(TABLE_NAME):
        return

    drop_rejected_at = _has_column(TABLE_NAME, "rejected_at")
    drop_rejected_by = _has_column(TABLE_NAME, "rejected_by")
    if not (drop_rejected_at or drop_rejected_by):
        return

    with op.batch_alter_table(TABLE_NAME) as batch:
        if drop_rejected_at:
            batch.drop_column("rejected_at")
        if drop_rejected_by:
            batch.drop_column("rejected_by")
