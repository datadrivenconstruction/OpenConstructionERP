"""v2.9.24 — composite index on (is_active, code) for region-less cost search.

Companion to v2.8.3's ``ix_costs_region_active_code``. That index covers the
hot path when a ``region`` filter is supplied — but the public ``/costs``
list view (no region selected, "all regions") cannot use it because
``region`` is the leading column. SQLite then falls back to
``ix_costs_is_active`` and sorts the entire active set in a temp B-tree:
on a 111 k-row catalogue the ``WHERE is_active=1 ORDER BY code LIMIT 10``
plan scans every active row and runs ``USE TEMP B-TREE FOR ORDER BY``,
clocking 15 s on the dev box even with the lite payload trim.

Adding ``ix_costs_active_code`` ((is_active, code)) lets the planner serve
both predicate and ORDER BY directly from the B-tree, cutting the same
query to ~1 ms (~10 000× speedup measured locally on the 111 k-row dev
DB). The two indexes coexist — the v2.8.3 region-leading one stays the
preferred path when a region filter is present.

Inspector-guarded — re-running is a no-op.

Revision ID: v2924_costs_active_code_index
Revises: v2924_normalize_estimator_role
Create Date: 2026-05-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v2924_costs_active_code_index"
down_revision: Union[str, Sequence[str], None] = "v2924_normalize_estimator_role"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_costs_item"
_INDEX = "ix_costs_active_code"
_COLUMNS = ["is_active", "code"]


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
