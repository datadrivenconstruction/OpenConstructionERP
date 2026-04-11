"""add tasks bim_element_ids column

Adds ``bim_element_ids`` (JSON array) to ``oe_tasks_task`` so that tasks
(defects / inspections / topics) can be spatially linked to BIM elements
without needing a separate join table. Mirrors the denormalised pattern
used by ``oe_boq_position.cad_element_ids``.

The migration is idempotent — it first inspects the live schema and only
runs ``ADD COLUMN`` when the column is absent. Safe to re-run against
dev SQLite databases where ``Base.metadata.create_all`` may already have
created the column.

Revision ID: 1f58eec86764
Revises: ffe3f561e2c1
Create Date: 2026-04-11 11:03:25.253364

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "1f58eec86764"
down_revision: Union[str, None] = "ffe3f561e2c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "oe_tasks_task"
COLUMN_NAME = "bim_element_ids"


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
    # If the table itself isn't present (fresh SQLite dev DB that has not
    # run the v090 init migration against a populated schema), skip —
    # ``Base.metadata.create_all`` at app boot will pick up the new column
    # from the model. Similarly, if the column already exists (dev DBs
    # where create_all ran before the migration), nothing to do.
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
