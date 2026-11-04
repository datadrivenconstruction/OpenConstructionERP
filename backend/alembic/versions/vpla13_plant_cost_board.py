# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""plant cost board inputs on the equipment register

Two nullable columns on ``oe_equipment_equipment``: the monthly cost of holding
a machine beyond depreciation (finance, insurance, storage; the monthly rent
for rented or leased units) and the market hire rate per day that the
rent-or-return suggestion compares against.

Revision ID: vpla13_plant_cost_board
Revises: vdee9_schedule_constraint_names
Create Date: 2026-11-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vpla13_plant_cost_board"
down_revision: str | Sequence[str] | None = "vdee9_schedule_constraint_names"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_equipment_equipment"


def upgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column("holding_cost_per_month", sa.Numeric(18, 4), nullable=True))
        batch.add_column(sa.Column("market_hire_rate_per_day", sa.Numeric(18, 4), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column("market_hire_rate_per_day")
        batch.drop_column("holding_cost_per_month")
