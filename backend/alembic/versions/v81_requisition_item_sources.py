# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""procurement - BOQ provenance for material requisition lines.

One new table, ``oe_procurement_req_item_source``: each row names a BOQ position and the resource
within its split that contributed quantity to a requisition line, with the quantity and unit as they
stood at the source and the cost line the position pointed at. The row cascades with its line.

One column is added to an existing table: ``oe_procurement_req_item.catalog_item_id``, nullable with an
index and no foreign key. It is the only identity two lines are merged on without a person confirming.

Every constraint and index name is written out and matches the models. Every step is inspector-guarded,
so a database whose tables ``create_all`` already built reaches this revision and does nothing.

Revision ID: v81_requisition_item_sources
Revises: v80_project_handbook
Create Date: 2026-10-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v81_requisition_item_sources"
down_revision: str | Sequence[str] | None = "v80_project_handbook"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ITEM_TABLE = "oe_procurement_req_item"
_ITEM_INDEX = "ix_oe_procurement_req_item_catalog_item_id"
_SOURCE_TABLE = "oe_procurement_req_item_source"
_SOURCE_INDEXES: list[tuple[str, list[str]]] = [
    ("ix_oe_procurement_req_item_source_item_id", ["item_id"]),
    ("ix_oe_procurement_req_item_source_boq_position_id", ["boq_position_id"]),
]


def upgrade() -> None:
    """Add the catalogue column to requisition lines, then the provenance table; each only when missing."""
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if _ITEM_TABLE in tables:
        if "catalog_item_id" not in {c["name"] for c in sa.inspect(bind).get_columns(_ITEM_TABLE)}:
            op.add_column(_ITEM_TABLE, sa.Column("catalog_item_id", GUID(), nullable=True))
        if _ITEM_INDEX not in {ix["name"] for ix in sa.inspect(bind).get_indexes(_ITEM_TABLE)}:
            op.create_index(_ITEM_INDEX, _ITEM_TABLE, ["catalog_item_id"])
    if _SOURCE_TABLE not in tables:
        op.create_table(
            _SOURCE_TABLE,
            sa.Column("id", GUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column(
                "item_id",
                GUID(),
                sa.ForeignKey(
                    f"{_ITEM_TABLE}.id",
                    ondelete="CASCADE",
                    name="fk_oe_procurement_req_item_source_item_id_oe_procurement_req_item",
                ),
                nullable=False,
            ),
            sa.Column("boq_position_id", GUID(), nullable=True),
            sa.Column("resource_key", sa.String(length=200), nullable=True),
            sa.Column("quantity", sa.String(length=50), nullable=False, server_default="0"),
            sa.Column("unit", sa.String(length=20), nullable=True),
            sa.Column("cost_line_id", GUID(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.PrimaryKeyConstraint("id", name="pk_oe_procurement_req_item_source"),
        )
    existing = {ix["name"] for ix in sa.inspect(bind).get_indexes(_SOURCE_TABLE)}
    for name, cols in _SOURCE_INDEXES:
        if name not in existing:
            op.create_index(name, _SOURCE_TABLE, cols)


def downgrade() -> None:
    """Drop the provenance table, then the catalogue column."""
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if _SOURCE_TABLE in tables:
        op.drop_table(_SOURCE_TABLE)
    if _ITEM_TABLE in tables:
        if _ITEM_INDEX in {ix["name"] for ix in sa.inspect(bind).get_indexes(_ITEM_TABLE)}:
            op.drop_index(_ITEM_INDEX, table_name=_ITEM_TABLE)
        if "catalog_item_id" in {c["name"] for c in sa.inspect(bind).get_columns(_ITEM_TABLE)}:
            with op.batch_alter_table(_ITEM_TABLE) as batch:
                batch.drop_column("catalog_item_id")
