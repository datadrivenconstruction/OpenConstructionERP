# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BOQ Snapshot - add description, total_value, position_count columns.

Strictly additive: three new nullable columns on ``oe_boq_snapshot`` so
the version-history list can display position count and grand total
without deserialising the heavy ``snapshot_data`` JSON blob.

Idempotent via inspector guard so re-runs on a partially-migrated
database skip already-present columns.

Revision ID: v41_boq_snapshot_summary_cols
Revises: v41_contract_original_value
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v41_boq_snapshot_summary_cols"
down_revision: Union[str, Sequence[str], None] = "v41_contract_original_value"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_boq_snapshot"

_COLUMNS = [
    ("description", sa.Text(), ""),
    ("total_value", sa.String(50), None),
    ("position_count", sa.Integer(), None),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    for col_name, col_type, default in _COLUMNS:
        if col_name not in existing:
            op.add_column(
                _TABLE,
                sa.Column(col_name, col_type, nullable=True, server_default=str(default) if default == "" else None),
            )


def downgrade() -> None:
    for col_name, _, _ in reversed(_COLUMNS):
        op.drop_column(_TABLE, col_name)
