# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""qms_money_numeric — NCR cost_impact_amount Numeric(15,2) → Numeric(18,2).

Round 5 QMS audit upgraded ``oe_qms_ncr.cost_impact_amount`` to the
platform money convention ``NUMERIC(18, 2)`` (matches ``finance``,
``change_orders``, ``contracts``, ``rfq_bidding``, ``clash_cost_impact``).
The previous ``NUMERIC(15, 2)`` capped integer side at 13 digits — fine
for a single positional cost but truncates aggregate infrastructure NCRs
(e.g. a multi-million-EUR tunnel-section rework) at the database edge.

Widening-only on Postgres so existing rows round-trip identically.
SQLite stores numerics as text regardless of declared precision; the
ORM ``Numeric`` decorator handles Python-side ``Decimal`` normalisation.
Dev DBs keep working unchanged.

Revision ID: v3101_qms
Revises: v3100_sched
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3101_qms"
down_revision: Union[str, Sequence[str], None] = "v3100_sched"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_qms_ncr"
_COLUMN = "cost_impact_amount"


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    if not _is_postgres():
        # SQLite ignores declared numeric precision.
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    op.alter_column(
        _TABLE,
        _COLUMN,
        existing_type=sa.Numeric(15, 2),
        type_=sa.Numeric(18, 2),
        existing_nullable=True,
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    op.alter_column(
        _TABLE,
        _COLUMN,
        existing_type=sa.Numeric(18, 2),
        type_=sa.Numeric(15, 2),
        existing_nullable=True,
    )
