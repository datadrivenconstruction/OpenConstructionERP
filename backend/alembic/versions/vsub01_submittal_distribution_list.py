# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Submittal distribution list

Adds ``distribution_list`` (JSON array of user ids) to ``oe_submittals_submittal``.
Additive only: the column carries a server default, so the boot heal and
``alembic upgrade`` agree.

Revision ID: vsub01_submittal_distribution
Revises: vct01_cost_type_budget_lines
Create Date: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vsub01_submittal_distribution"
down_revision: str | Sequence[str] | None = "vct01_cost_type_budget_lines"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_submittals_submittal"
_COLUMN = "distribution_list"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}:
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column(_COLUMN, sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if _COLUMN not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column(_COLUMN)
