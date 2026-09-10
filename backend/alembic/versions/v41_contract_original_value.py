# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contract — stored original_contract_value baseline.

Adds a nullable ``original_contract_value`` column (Numeric 18,4) to
``oe_contracts_contract``.  The column is frozen at the moment the
contract transitions from draft to active and is never written again.
Reports that need the pre-amendment figure read it directly instead of
reconstructing it by subtracting change-order deltas from the current
``total_value``.

Strictly additive — no existing column is touched.  Idempotent via
inspector guard so re-runs on a partially-migrated database skip the
column if it already exists.

Revision ID: v41_contract_original_value
Revises: v41_coordination_thresholds
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v41_contract_original_value"
down_revision: Union[str, Sequence[str], None] = (
    "v41_coordination_thresholds",
    "v3324_buyer_selection_currency",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_contracts_contract"
_COLUMN = "original_contract_value"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    if _COLUMN not in existing:
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.Numeric(precision=18, scale=4),
                nullable=True,
                comment=(
                    "Frozen copy of total_value at the moment the contract left draft. Immutable after being set."
                ),
            ),
        )

    # Backfill: for contracts already active, compute the original by
    # subtraction (same logic the G702 report used before this column).
    # This is a best-effort reconstruction; contracts with no rollup
    # metadata fall back to the manually-entered terms value.
    # data-rewrite-ack: table=oe_contracts_contract growth=tenure rows=draft contracts whose original_contract_value was never set
    # boot-repair: none - the column is added by the boot heal but left NULL; only alembic backfills it
    op.execute(
        sa.text(f"""
            UPDATE {_TABLE}
            SET {_COLUMN} = total_value
            WHERE status = 'draft'
              AND {_COLUMN} IS NULL
        """)
    )


def downgrade() -> None:
    op.drop_column(_TABLE, _COLUMN)
