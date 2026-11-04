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
down_revision: str | Sequence[str] | None = "vrat13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_equipment_equipment"


def _columns() -> set[str] | None:
    insp = sa.inspect(op.get_bind())
    if _TABLE not in insp.get_table_names():
        return None
    return {c["name"] for c in insp.get_columns(_TABLE)}


def upgrade() -> None:
    have = _columns()
    if have is None:
        return
    new = [c for c in ("holding_cost_per_month", "market_hire_rate_per_day") if c not in have]
    if not new:
        return
    with op.batch_alter_table(_TABLE) as batch:
        for name in new:
            batch.add_column(sa.Column(name, sa.Numeric(18, 4), nullable=True))


def downgrade() -> None:
    have = _columns()
    if have is None:
        return
    drop = [c for c in ("market_hire_rate_per_day", "holding_cost_per_month") if c in have]
    if not drop:
        return
    with op.batch_alter_table(_TABLE) as batch:
        for name in drop:
            batch.drop_column(name)
