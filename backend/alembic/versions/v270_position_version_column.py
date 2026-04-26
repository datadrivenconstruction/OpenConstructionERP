"""v2.7.0 — add ``version`` column to oe_boq_position (BUG-CONCURRENCY01).

Adds an integer ``version`` column with default 0 to support
optimistic-concurrency control on Position updates.  The service-layer
``update_position`` method bumps it on every successful write; clients
echo the last-read value on PATCH and receive 409 on mismatch.

Revision ID: v270_position_version_column
Revises: eb1cef6f5fce, v232_merge_heads
Create Date: 2026-04-25
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v270_position_version_column"
# Merge with the two existing heads so ``alembic upgrade head`` resolves
# to a single tip again (BUG-CONCURRENCY01 schema sits below the
# v232/v262 merge points).
down_revision: Union[str, Sequence[str], None] = ("eb1cef6f5fce", "v232_merge_heads")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add ``version INT NOT NULL DEFAULT 0`` to ``oe_boq_position``."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "oe_boq_position" not in inspector.get_table_names():
        return
    existing_cols = {col["name"] for col in inspector.get_columns("oe_boq_position")}
    if "version" in existing_cols:
        return
    with op.batch_alter_table("oe_boq_position") as batch_op:
        batch_op.add_column(
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    """Drop the ``version`` column."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "oe_boq_position" not in inspector.get_table_names():
        return
    existing_cols = {col["name"] for col in inspector.get_columns("oe_boq_position")}
    if "version" not in existing_cols:
        return
    with op.batch_alter_table("oe_boq_position") as batch_op:
        batch_op.drop_column("version")
