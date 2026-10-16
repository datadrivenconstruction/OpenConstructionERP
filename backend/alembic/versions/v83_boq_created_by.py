# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""boq_created_by - who started a bill of quantities.

One nullable column on ``oe_boq_boq``: ``created_by``, the user id that created the bill. The
author of a bill may delete it without the ``boq.delete`` role, because a viewer may start an
estimate (issue #101) and must be able to remove the one they started. NULL on every bill written
before this revision; no backfill, since nothing records who started those bills and guessing an
author would hand someone a delete right they never had.

Inspector-guarded, so a database whose table ``create_all`` already built with the column reaches
this revision and does nothing. The column is additive and nullable, so the boot-time
``postgres_auto_migrate`` adds it on an installation that stamps rather than upgrades.

Revision ID: v83_boq_created_by
Revises: v82_requisition_item_sources
Create Date: 2026-10-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v83_boq_created_by"
down_revision: str | Sequence[str] | None = "v82_requisition_item_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_boq_boq"
_COLUMN = "created_by"


def _has_column(bind: sa.engine.Connection) -> bool:
    return _COLUMN in {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}


def upgrade() -> None:
    """Add the nullable author column when the table exists and lacks it."""
    bind = op.get_bind()
    if _TABLE in sa.inspect(bind).get_table_names() and not _has_column(bind):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=36), nullable=True))


def downgrade() -> None:
    """Drop the author column when it is there."""
    bind = op.get_bind()
    if _TABLE in sa.inspect(bind).get_table_names() and _has_column(bind):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)
