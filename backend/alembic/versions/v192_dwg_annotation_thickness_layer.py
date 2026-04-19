"""v1.9.2 -- add thickness and layer_name columns to oe_dwg_takeoff_annotation.

Adds two columns to ``oe_dwg_takeoff_annotation`` so user-drawn primitive
shapes can be rendered with a configurable stroke width and grouped under
a virtual ``USER_MARKUP`` layer for bulk show/hide in the LayerPanel:

* ``thickness`` (Float, default 2.0) — stroke width in logical pixels.
  Sits alongside ``line_width`` (Integer) because the renderer now
  supports fractional widths (e.g. 1.5 px for fine leader lines).
* ``layer_name`` (String, default "USER_MARKUP") — virtual layer name
  that groups hand-drawn annotations so estimators can toggle all
  markups off in one click without losing the underlying DXF entities.

Idempotent — inspects the live schema and only ``ADD COLUMN`` when the
column is absent. Safe to re-run against dev SQLite databases where
``Base.metadata.create_all`` may already have created the columns.

Revision ID: v192_dwg_annotation_thickness_layer
Revises: v191_cde_audit
Create Date: 2026-04-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "v192_dwg_annotation_thickness_layer"
down_revision: Union[str, None] = "v191_cde_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "oe_dwg_takeoff_annotation"


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(col["name"] == column for col in insp.get_columns(table))


def upgrade() -> None:
    if not _table_exists(TABLE_NAME):
        return

    if not _has_column(TABLE_NAME, "thickness"):
        op.add_column(
            TABLE_NAME,
            sa.Column(
                "thickness",
                sa.Float(),
                nullable=False,
                server_default="2.0",
            ),
        )

    if not _has_column(TABLE_NAME, "layer_name"):
        op.add_column(
            TABLE_NAME,
            sa.Column(
                "layer_name",
                sa.String(length=100),
                nullable=False,
                server_default="USER_MARKUP",
            ),
        )


def downgrade() -> None:
    if _has_column(TABLE_NAME, "layer_name"):
        with op.batch_alter_table(TABLE_NAME) as batch_op:
            batch_op.drop_column("layer_name")
    if _has_column(TABLE_NAME, "thickness"):
        with op.batch_alter_table(TABLE_NAME) as batch_op:
            batch_op.drop_column("thickness")
