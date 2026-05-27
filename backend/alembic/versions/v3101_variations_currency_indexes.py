# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v3101 — variations (project_id, currency_code) covering index.

Round-5 variations correctness fix changed
``get_project_variations_total`` from a flat sum across mixed currencies
to a currency-grouped rollup. The new query is
``GROUP BY project_id, currency_code``; this covering index keeps it at
index-scan cost.

Strictly-additive + inspector-guarded.

Revision ID: v3101_var
Revises: v3100_sched
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3101_var"
down_revision: Union[str, Sequence[str], None] = "v3100_sched"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_variations_variation"
_INDEX = "ix_variations_project_currency"
_COLS = ["project_id", "currency_code"]


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def _has_columns(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    cols: list[str],
) -> bool:
    if table not in inspector.get_table_names():
        return False
    present = {c["name"] for c in inspector.get_columns(table)}
    return all(c in present for c in cols)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if (
        _TABLE in inspector.get_table_names()
        and _has_columns(inspector, _TABLE, _COLS)
        and not _has_index(inspector, _TABLE, _INDEX)
    ):
        op.create_index(_INDEX, _TABLE, _COLS)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_index(inspector, _TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
