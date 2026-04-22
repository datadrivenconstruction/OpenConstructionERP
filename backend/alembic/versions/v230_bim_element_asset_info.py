"""v2.3.0 -- add asset_info + is_tracked_asset columns to oe_bim_element.

Part of the ISO 19650 Asset Information Model work: BIMElement becomes
the single source of truth for both design-phase BIM data and
operational-phase asset data. New columns:

* ``asset_info`` (JSON, default ``{}``) — free-form bag for manufacturer,
  model, serial_number, warranty_until, commissioned_at, operational_status,
  parent_system_id, asset_tag. Kept as a blob (not dedicated columns) so
  tenants can extend without a migration.
* ``is_tracked_asset`` (Boolean, default FALSE) — flags whether this
  element is a real-world asset that should appear on the Assets page.
  Flipped when asset_info is first populated; users can also toggle
  manually.

An index on ``is_tracked_asset`` supports the Assets-list query
(filters by this flag across the project).

Idempotent — checks live schema, adds only missing columns. Safe to
re-run against dev SQLite where ``Base.metadata.create_all`` may have
already produced the columns.

Revision ID: v230_bim_element_asset_info
Revises: v192_dwg_annotation_thickness_layer
Create Date: 2026-04-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "v230_bim_element_asset_info"
down_revision: Union[str, None] = "v192_dwg_annotation_thickness_layer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "oe_bim_element"
INDEX_NAME = "ix_bim_element_tracked"


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


def _has_index(table: str, index_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(ix["name"] == index_name for ix in insp.get_indexes(table))


def upgrade() -> None:
    if not _table_exists(TABLE_NAME):
        return

    if not _has_column(TABLE_NAME, "asset_info"):
        op.add_column(
            TABLE_NAME,
            sa.Column(
                "asset_info",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )

    if not _has_column(TABLE_NAME, "is_tracked_asset"):
        op.add_column(
            TABLE_NAME,
            sa.Column(
                "is_tracked_asset",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            ),
        )

    if not _has_index(TABLE_NAME, INDEX_NAME):
        op.create_index(INDEX_NAME, TABLE_NAME, ["is_tracked_asset"])


def downgrade() -> None:
    if _has_index(TABLE_NAME, INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
    if _has_column(TABLE_NAME, "is_tracked_asset"):
        with op.batch_alter_table(TABLE_NAME) as batch_op:
            batch_op.drop_column("is_tracked_asset")
    if _has_column(TABLE_NAME, "asset_info"):
        with op.batch_alter_table(TABLE_NAME) as batch_op:
            batch_op.drop_column("asset_info")
