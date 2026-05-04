"""v2.8.2 — per-project catalog binding.

Adds the ``cost_database_id`` column to ``oe_projects_match_settings``.
This is the explicit user-selected CWICR catalogue (``RU_STPETERSBURG``,
``DE_BERLIN``, …) that the match service searches against. Nullable —
no auto-pick from ``project.region`` because regions are coarse tags
(DACH / EU / US) while catalogue IDs are city-level. The match
endpoint surfaces a structured ``no_catalog_selected`` error envelope
when this is null so the UI can render an explicit picker instead of
returning empty results that look like a bug.

Inspector-guarded — re-running on a migrated DB is a no-op.

Revision ID: v282_match_cost_database_id
Revises: v281_match_project_settings
Create Date: 2026-05-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v282_match_cost_database_id"
down_revision: Union[str, Sequence[str], None] = "v281_match_project_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_projects_match_settings"
_COL = "cost_database_id"


def _has_column(inspector: sa.engine.reflection.Inspector, table: str, col: str) -> bool:
    return col in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _TABLE not in inspector.get_table_names():
        return  # match-settings table not yet created — earlier migration handles it
    if _has_column(inspector, _TABLE, _COL):
        return

    op.add_column(
        _TABLE,
        sa.Column(_COL, sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _TABLE not in inspector.get_table_names():
        return
    if not _has_column(inspector, _TABLE, _COL):
        return

    op.drop_column(_TABLE, _COL)
