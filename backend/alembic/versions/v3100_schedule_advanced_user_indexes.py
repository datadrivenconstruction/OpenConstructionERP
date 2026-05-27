# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v3100 — schedule_advanced FK-column indexes.

Round-5 Wave A FK-index audit on the schedule_advanced module: the
workspace-share lookup path filters by ``shared_with_user_id`` (and
sometimes by ``shared_by_user_id``) without a supporting index, so a
multi-tenant install with thousands of workspace shares was hitting a
seq-scan on every "list workspaces shared with me" load.

Strictly-additive — only creates indexes if the target table + columns
exist and the index isn't already present. SQLite + PostgreSQL safe.

Revision ID: v3100_sched
Revises: v3099_subm, v3099_subs
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3100_sched"
down_revision: Union[str, Sequence[str], None] = ("v3099_subm", "v3099_subs")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, index_name)
_INDEXES: list[tuple[str, str, str]] = [
    (
        "oe_schedule_advanced_workspace_share",
        "shared_with_user_id",
        "ix_sched_adv_workspace_share_with_user",
    ),
    (
        "oe_schedule_advanced_workspace_share",
        "shared_by_user_id",
        "ix_sched_adv_workspace_share_by_user",
    ),
]


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def _has_column(inspector: sa.engine.reflection.Inspector, table: str, col: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return col in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, column, name in _INDEXES:
        if (
            table in inspector.get_table_names()
            and _has_column(inspector, table, column)
            and not _has_index(inspector, table, name)
        ):
            op.create_index(name, table, [column])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, _column, name in _INDEXES:
        if _has_index(inspector, table, name):
            op.drop_index(name, table_name=table)
