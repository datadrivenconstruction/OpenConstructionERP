# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Add the EVM earned-value column to costmodel budget lines.

Adds a single additive, nullable column:

    oe_costmodel_budget_line.earned_amount - BCWP for the line, computed as
        the linked BOQ position total x the latest recorded percent_complete
        / 100. Maintained synchronously by the progress module whenever a
        progress entry is recorded (latest reading wins, never accumulated).
        NULL means no progress has been recorded for the position yet.

This closes the BOQ -> budget -> progress chain gap where percent-complete
entries never flowed into budget earned value, leaving EVM rollups empty.

The embedded PostgreSQL runtime materialises new columns via create_all and
auto-heals at startup, so this migration is for external PostgreSQL deployments
that manage schema with Alembic. The step is guarded with a presence check so a
re-run, or a DB the runtime already auto-created, is a no-op. Additive and
backfill-safe (existing rows read NULL = no progress recorded). PostgreSQL-only.

Revision ID: v3180_budget_line_earned_amount
Revises: v3179_gaap_chart_of_accounts
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v3180_budget_line_earned_amount"
down_revision = "v3179_gaap_chart_of_accounts"
branch_labels = None
depends_on = None

_TABLE = "oe_costmodel_budget_line"
_COLUMN = "earned_amount"


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if not _has_column(_TABLE, _COLUMN):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Numeric(20, 4), nullable=True))


def downgrade() -> None:
    if _has_column(_TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
