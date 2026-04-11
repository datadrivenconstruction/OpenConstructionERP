"""gate_result.score: String(10) -> Float

Migrates ``oe_requirements_gate_result.score`` from a ``String(10)``
column storing a stringified percentage ("85.5") to a real ``Float``
column.

Why this matters
----------------

Storing a numeric score as a string had three concrete problems:

1. **Lexicographic sort**: ``ORDER BY score DESC`` returned ``"9.5"``
   above ``"85.0"`` because string comparison happens character by
   character. Any "top N gate runs" report was silently wrong.
2. **Precision loss**: every write went through ``str(score)`` and
   every read through ``float(score_raw)`` — round-trip noise.
3. **Type safety**: clients could store any 10-character string in
   the column. The Pydantic schema already exposes ``score: float``,
   so the column type was a lie about the contract.

The migration is idempotent — it inspects the live schema first and
only runs the type change when the column is still ``VARCHAR/CHAR``.
Existing string values are coerced to floats via SQLAlchemy's batch
alter; rows that fail to parse default to ``0.0`` (defensive — none
should exist in production but the score column had no validation).

Revision ID: b2f4e1a3c907
Revises: 1f58eec86764
Create Date: 2026-04-11 16:00:00.000000

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2f4e1a3c907"
down_revision: Union[str, None] = "1f58eec86764"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "oe_requirements_gate_result"
COLUMN_NAME = "score"


def _column_type(table: str, column: str) -> str | None:
    """Return the live column type as a lowercase string, or None."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return None
    for col in insp.get_columns(table):
        if col["name"] == column:
            return str(col["type"]).lower()
    return None


def upgrade() -> None:
    col_type = _column_type(TABLE_NAME, COLUMN_NAME)
    if col_type is None:
        # Table or column missing — fresh dev DB will pick up the new
        # type from ``Base.metadata.create_all``.
        return
    if "float" in col_type or "real" in col_type or "double" in col_type:
        # Already migrated.
        return

    # Coerce any non-numeric strings to "0" before the type change so
    # the cast does not fail.  This is defensive — production rows
    # should already be parseable.
    op.execute(
        f"UPDATE {TABLE_NAME} SET {COLUMN_NAME} = '0' "
        f"WHERE {COLUMN_NAME} IS NULL OR {COLUMN_NAME} = '' "
        f"OR {COLUMN_NAME} GLOB '*[^0-9.]*'"
    )

    with op.batch_alter_table(TABLE_NAME) as batch_op:
        batch_op.alter_column(
            COLUMN_NAME,
            existing_type=sa.String(length=10),
            type_=sa.Float(),
            existing_nullable=False,
            existing_server_default="0",
            postgresql_using=f"{COLUMN_NAME}::double precision",
        )


def downgrade() -> None:
    col_type = _column_type(TABLE_NAME, COLUMN_NAME)
    if col_type is None:
        return
    if "varchar" in col_type or "char" in col_type:
        return

    with op.batch_alter_table(TABLE_NAME) as batch_op:
        batch_op.alter_column(
            COLUMN_NAME,
            existing_type=sa.Float(),
            type_=sa.String(length=10),
            existing_nullable=False,
            existing_server_default="0",
        )
