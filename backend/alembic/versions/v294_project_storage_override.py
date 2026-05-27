"""v2.9.4 — Project.storage_path_override + storage_uses_default.

Adds two columns to ``oe_projects_project`` so a project can opt into a
custom on-disk storage root for its attachments. When ``storage_uses_default``
is true (default), uploads land under the system-wide data dir as before.
When it is false and ``storage_path_override`` is set, the documents /
photos / sheets / BIM / DWG services route writes under
``{override}/{project_id}/...`` instead.

The flags are nullable-with-default so existing rows pick the new behaviour
without requiring a backfill migration.

Revision ID: v294_project_storage_override
Revises: v283_costs_region_active_index
Create Date: 2026-05-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v294_project_storage_override"
down_revision: Union[str, Sequence[str], None] = "v283_costs_region_active_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_projects_project"
_COLS = (
    ("storage_path_override", sa.String(length=500), True, None),
    ("storage_uses_default", sa.Boolean(), False, "1"),
)


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    name: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(col["name"] == name for col in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    for col_name, col_type, nullable, server_default in _COLS:
        if _has_column(inspector, _TABLE, col_name):
            continue
        kwargs: dict = {"nullable": nullable}
        if server_default is not None:
            kwargs["server_default"] = server_default
        op.add_column(_TABLE, sa.Column(col_name, col_type, **kwargs))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    for col_name, _t, _n, _d in _COLS:
        if _has_column(inspector, _TABLE, col_name):
            op.drop_column(_TABLE, col_name)
