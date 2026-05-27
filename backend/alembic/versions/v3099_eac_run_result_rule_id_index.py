# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v3099 — standalone FK index on oe_eac_run_result_item.rule_id.

Round-5 EAC audit Wave A FK-index sweep: the compound index
``ix_eac_run_result_run_rule (run_id, rule_id)`` is leftmost-prefixed on
``run_id`` so any query that filters by ``rule_id`` alone cannot use it.
``oe_eac_run_result_item`` is a hot table (up to ``HOT_RESULT_ITEM_CAP =
100_000`` rows per run); the "results for one rule across runs" query
becomes a seq-scan once a few large runs accumulate.

Idempotent + cross-dialect (inspector-guarded).

Revision ID: v3099_eac
Revises: v3098
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3099_eac"
down_revision: Union[str, Sequence[str], None] = "v3098"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_eac_run_result_item"
_INDEX = "ix_eac_run_result_rule_id"


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE in inspector.get_table_names() and not _has_index(inspector, _TABLE, _INDEX):
        op.create_index(_INDEX, _TABLE, ["rule_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_index(inspector, _TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
