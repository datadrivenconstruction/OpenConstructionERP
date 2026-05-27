# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v3.8.1 — Punch List reopen audit trail.

Adds a ``reopen_history`` JSON column to ``oe_punchlist_item`` that captures
every transition from a terminal status (``closed`` / ``verified``) back to
an active status (``open`` / ``in_progress``).

Each history entry is a JSON object:

.. code-block:: json

    {
        "reopened_at": "2026-05-19T12:34:56+00:00",
        "reopened_by": "<user-id>",
        "previous_status": "closed",
        "reason": "Defect re-observed during walk-through"
    }

The column defaults to ``'[]'`` so existing rows remain valid after the
migration. The migration is fully inspector-guarded and SQLite-safe via
``batch_alter_table``.

Revision ID: v3081_punchlist_reopen_audit
Revises: v3071_merge_clash_and_files
Created: 2026-05-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3081_punchlist_reopen_audit"
down_revision: Union[str, Sequence[str], None] = "v3071_merge_clash_and_files"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_punchlist_item"
_COLUMN = "reopen_history"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(inspector: sa.engine.reflection.Inspector, table: str, column: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    """Add ``reopen_history`` JSON column to oe_punchlist_item."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        # Fresh installs lay the table down via Base.metadata.create_all
        # which already includes the new column — nothing to do.
        return

    if _has_column(inspector, _TABLE, _COLUMN):
        return

    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.add_column(
            sa.Column(
                _COLUMN,
                sa.JSON(),
                nullable=False,
                server_default="[]",
            )
        )


def downgrade() -> None:
    """Drop the ``reopen_history`` column."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, _TABLE, _COLUMN):
        return

    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.drop_column(_COLUMN)
