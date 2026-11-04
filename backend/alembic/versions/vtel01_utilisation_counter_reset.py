# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""equipment utilisation day: counter reset flag

Adds ``counter_reset`` to ``oe_equipment_utilisation_day`` so a day whose engine
counter restarted (ECU swap, rollover) is shown as such instead of as zero use.

Revision ID: vtel01_util_counter_reset
Revises: vap01_inbox_po_match
Create Date: 2026-11-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vtel01_util_counter_reset"
down_revision: str | Sequence[str] | None = "vap01_inbox_po_match"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_equipment_utilisation_day"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if "counter_reset" not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column("counter_reset", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if "counter_reset" in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.drop_column(_TABLE, "counter_reset")
