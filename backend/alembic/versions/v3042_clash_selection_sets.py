# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Clash - BIM-coordination tool style selection sets + element_type snapshot.

Additive columns, all backward-compatible:

* ``oe_clash_run.set_a`` / ``set_b`` — nullable JSON. The two selection
  sets for ``mode='selection_sets'`` (each
  ``{"disciplines": [...], "element_types": [...]}``). NULL for every
  other mode and for all pre-existing runs.
* ``oe_clash_result.a_element_type`` / ``b_element_type`` — NOT NULL
  String(100) defaulting to '' so existing rows stay valid; snapshots
  the participating elements' category/family-type for the result table.

Idempotent: inspector-guarded so re-running after SQLite's
``Base.metadata.create_all`` (dev) is a no-op; Postgres prod gets the DDL.

Revision ID: v3042_clash_selection_sets
Revises: v3041_clash_storey
Created: 2026-05-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3042_clash_selection_sets"
down_revision: Union[str, Sequence[str], None] = "v3041_clash_storey"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RUN = "oe_clash_run"
_RESULT = "oe_clash_result"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _RUN):
        cols = {c["name"] for c in inspector.get_columns(_RUN)}
        if "set_a" not in cols:
            op.add_column(_RUN, sa.Column("set_a", sa.JSON(), nullable=True))
        if "set_b" not in cols:
            op.add_column(_RUN, sa.Column("set_b", sa.JSON(), nullable=True))

    if _has_table(inspector, _RESULT):
        cols = {c["name"] for c in inspector.get_columns(_RESULT)}
        if "a_element_type" not in cols:
            op.add_column(
                _RESULT,
                sa.Column(
                    "a_element_type",
                    sa.String(100),
                    nullable=False,
                    server_default="",
                ),
            )
        if "b_element_type" not in cols:
            op.add_column(
                _RESULT,
                sa.Column(
                    "b_element_type",
                    sa.String(100),
                    nullable=False,
                    server_default="",
                ),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _RESULT):
        cols = {c["name"] for c in inspector.get_columns(_RESULT)}
        if "b_element_type" in cols:
            op.drop_column(_RESULT, "b_element_type")
        if "a_element_type" in cols:
            op.drop_column(_RESULT, "a_element_type")

    if _has_table(inspector, _RUN):
        cols = {c["name"] for c in inspector.get_columns(_RUN)}
        if "set_b" in cols:
            op.drop_column(_RUN, "set_b")
        if "set_a" in cols:
            op.drop_column(_RUN, "set_a")
