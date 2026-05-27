"""v2.8.3 — composite index on (region, is_active, code) for cost search.

Drops the search hot path from ~6 s to ~1 ms on 55K-row catalogues.

The keyset-paginated search runs

    SELECT ... FROM oe_costs_item
    WHERE region = ? AND is_active = ?
    ORDER BY code, id LIMIT N

Without a covering index, SQLite picked ``ix_costs_is_active`` and sorted
the 55K matching rows in a temp B-tree, costing ~6 s per page. The
COUNT(*) for total pagination took another ~3 s. With the composite
``(region, is_active, code)`` index the planner serves both queries
directly from the B-tree — COUNT in 6 ms, SELECT in 1 ms.

Inspector-guarded — re-running on an already-migrated DB is a no-op.

Revision ID: v283_costs_region_active_index
Revises: v282_match_cost_database_id
Create Date: 2026-05-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v283_costs_region_active_index"
down_revision: Union[str, Sequence[str], None] = "v282_match_cost_database_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_costs_item"
_INDEX = "ix_costs_region_active_code"
_COLUMNS = ["region", "is_active", "code"]


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(idx["name"] == name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    if _has_index(inspector, _TABLE, _INDEX):
        return
    op.create_index(_INDEX, _TABLE, _COLUMNS)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_index(inspector, _TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
