# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Clash — per-element storey (level) index on oe_clash_result.

Two additive, nullable integer columns on ``oe_clash_result``:

* ``a_storey`` — storey/level index of element A (clustered from real
  geometry Z by the clash geometry loader).
* ``b_storey`` — storey/level index of element B.

Both nullable with no server_default so every existing row stays valid
(NULL = unknown storey, e.g. a bbox-only model with no GLB, behaves
exactly as before this migration). These power the run summary's
``level_matrix`` — the meaningful coordination grid for the common
single-discipline intra-model run, where the discipline×discipline
matrix collapses to a useless 1×1.

Idempotent: guarded by an inspector so re-running after SQLite's
``Base.metadata.create_all`` (dev) is a no-op; Postgres prod gets the DDL.

Revision ID: v3041_clash_storey
Revises: v3040_clash
Created: 2026-05-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3041_clash_storey"
down_revision: Union[str, Sequence[str], None] = "v3040_clash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RESULT = "oe_clash_result"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    """Add a_storey / b_storey to oe_clash_result (nullable int)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _RESULT):
        # Fresh DB: v3040 (or create_all) will build the table with these
        # columns already present from the ORM model — nothing to add.
        return
    existing_cols = {c["name"] for c in inspector.get_columns(_RESULT)}

    if "a_storey" not in existing_cols:
        op.add_column(_RESULT, sa.Column("a_storey", sa.Integer(), nullable=True))
    if "b_storey" not in existing_cols:
        op.add_column(_RESULT, sa.Column("b_storey", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Drop the two storey columns."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _RESULT):
        return
    existing_cols = {c["name"] for c in inspector.get_columns(_RESULT)}

    if "b_storey" in existing_cols:
        op.drop_column(_RESULT, "b_storey")
    if "a_storey" in existing_cols:
        op.drop_column(_RESULT, "a_storey")
