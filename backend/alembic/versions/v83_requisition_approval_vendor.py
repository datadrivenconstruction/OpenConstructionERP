# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""procurement - requisition approval, vendor choice and order line provenance.

Five nullable columns, no new table and no data written:

* ``oe_procurement_requisition.vendor_id`` (indexed): the supplier chosen from the Vendor directory.
* ``oe_procurement_requisition.submitted_by``: who submitted last, read by the four-eyes check.
* ``oe_procurement_requisition.decided_at`` and ``decision_comment``: the approval or rejection.
* ``oe_procurement_po_item.requisition_item_id`` (indexed): the requisition line an order line was
  converted from, which leads on to the BOQ positions in ``oe_procurement_req_item_source``.

Everything is additive and nullable, so the boot heal adds the same columns and indexes on an install
that never runs ``alembic upgrade``. Every step is inspector-guarded, so a database whose tables
``create_all`` already built reaches this revision and does nothing. Index names match the models.

Revision ID: v83_requisition_approval_vendor
Revises: v82_requisition_item_sources
Create Date: 2026-10-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v83_requisition_approval_vendor"
down_revision: str | Sequence[str] | None = "v82_requisition_item_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQ_TABLE = "oe_procurement_requisition"
_PO_ITEM_TABLE = "oe_procurement_po_item"

#: (table, column, type factory, index name or None)
_COLUMNS: list[tuple[str, str, object, str | None]] = [
    (_REQ_TABLE, "vendor_id", GUID, "ix_oe_procurement_requisition_vendor_id"),
    (_REQ_TABLE, "submitted_by", lambda: sa.String(length=36), None),
    (_REQ_TABLE, "decided_at", lambda: sa.String(length=40), None),
    (_REQ_TABLE, "decision_comment", sa.Text, None),
    (_PO_ITEM_TABLE, "requisition_item_id", GUID, "ix_oe_procurement_po_item_requisition_item_id"),
]


def upgrade() -> None:
    """Add each column and its index when missing."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table, column, type_factory, index_name in _COLUMNS:
        if table not in tables:
            continue
        columns = {c["name"] for c in sa.inspect(bind).get_columns(table)}
        if column not in columns:
            op.add_column(table, sa.Column(column, type_factory(), nullable=True))  # type: ignore[operator]
        if index_name is not None:
            indexes = {ix["name"] for ix in sa.inspect(bind).get_indexes(table)}
            if index_name not in indexes:
                op.create_index(index_name, table, [column])


def downgrade() -> None:
    """Drop the indexes, then the columns, each only when present."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table, column, _type_factory, index_name in reversed(_COLUMNS):
        if table not in tables:
            continue
        if index_name is not None and index_name in {ix["name"] for ix in sa.inspect(bind).get_indexes(table)}:
            op.drop_index(index_name, table_name=table)
        if column in {c["name"] for c in sa.inspect(bind).get_columns(table)}:
            with op.batch_alter_table(table) as batch:
                batch.drop_column(column)
