# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""subcontract change pass-through economics

Adds the owner-granted amount, the GC markup kept on a pass-through, the signed
time impact and the days the owner granted to ``oe_subcontractors_change``.

Revision ID: vsub9_subco_change_passthrough
Revises: vai01_doc_assistant_agent_catalogue
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vsub9_subco_change_passthrough"
down_revision: str | Sequence[str] | None = "vdup9_orders_receipts_role_split"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_subcontractors_change"


def _columns() -> list[sa.Column]:
    return [
        sa.Column("owner_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("markup_pct", sa.Numeric(7, 3), nullable=False, server_default="0"),
        sa.Column("time_impact_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("owner_time_days", sa.Integer(), nullable=True),
    ]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    with op.batch_alter_table(_TABLE) as batch:
        for column in _columns():
            if column.name not in existing:
                batch.add_column(column)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    with op.batch_alter_table(_TABLE) as batch:
        for column in _columns():
            if column.name in existing:
                batch.drop_column(column.name)
