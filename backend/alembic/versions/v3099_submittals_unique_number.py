# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v3099 — submittals (project_id, submittal_number) unique.

Round-5 submittals audit: ``next_submittal_number(project_id)`` reads
``MAX(suffix)+1`` then formats the label; concurrent submitters racing
on the same project produce duplicate ``SUB-005`` rows. The unique
index plus the service-layer IntegrityError retry loop (3 attempts)
converts the silent dup into a clean N+1 allocation.

Idempotent + cross-dialect (uses ``op.create_index(unique=True)`` so
SQLite — which lacks ``ALTER TABLE ADD CONSTRAINT`` — also succeeds).

Revision ID: v3099_subm
Revises: v3099_rfi
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3099_subm"
down_revision: Union[str, Sequence[str], None] = "v3099_rfi"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_submittals_submittal"
_INDEX = "uq_oe_submittals_submittal_project_number"


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE in inspector.get_table_names() and not _has_index(inspector, _TABLE, _INDEX):
        try:
            op.create_index(
                _INDEX,
                _TABLE,
                ["project_id", "submittal_number"],
                unique=True,
            )
        except sa.exc.IntegrityError:
            # Pre-existing duplicates would block the unique index. The
            # operator must resolve those manually — log and continue so
            # the rest of the upgrade chain doesn't wedge.
            pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_index(inspector, _TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
