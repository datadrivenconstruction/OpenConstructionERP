# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""procurement - suggested supplier and needed-by date per requisition line.

Six nullable columns and one data correction:

* ``oe_procurement_req_item.suggested_vendor_id`` (indexed): the supplier suggested for the line.
* ``oe_procurement_req_item.required_date``: when the line is needed; null falls back to the header.
* ``oe_procurement_req_item.schedule_activity_id`` (indexed), ``schedule_buffer_days`` and
  ``schedule_anchor_date``: the schedule activity a date was proposed from, the buffer before its
  start and the start date the proposal read.
* ``oe_procurement_req_item_source.suggested_vendor_id``: the supplier the BOQ suggested per source.

``oe_procurement_requisition.estimated_delivery_date`` used to hold ``required_date`` minus the lead
time, which is the latest ordering date and not a delivery forecast (issue #516). The column now holds
the delivery date of the order a requisition was converted into. The correction below clears the old
value on requisitions without an order and copies the order's delivery date onto those with one.

The columns are additive and nullable, so the boot heal adds them on an install that never runs
``alembic upgrade``; the data correction runs only here. Every step is inspector-guarded, so a database
whose tables ``create_all`` already built reaches this revision and does nothing but the correction.

Revision ID: v91_requisition_line_supplier_dates
Revises: v90_bi_benchmark_sets
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v91_requisition_line_supplier_dates"
down_revision: str | Sequence[str] | None = "v90_bi_benchmark_sets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQ_TABLE = "oe_procurement_requisition"
_ITEM_TABLE = "oe_procurement_req_item"
_SOURCE_TABLE = "oe_procurement_req_item_source"
_PO_TABLE = "oe_procurement_po"

#: (table, column, type factory, index name or None)
_COLUMNS: list[tuple[str, str, object, str | None]] = [
    (_ITEM_TABLE, "suggested_vendor_id", GUID, "ix_oe_procurement_req_item_suggested_vendor_id"),
    (_ITEM_TABLE, "required_date", lambda: sa.String(length=40), None),
    (_ITEM_TABLE, "schedule_activity_id", GUID, "ix_oe_procurement_req_item_schedule_activity_id"),
    (_ITEM_TABLE, "schedule_buffer_days", sa.Integer, None),
    (_ITEM_TABLE, "schedule_anchor_date", lambda: sa.String(length=40), None),
    (_SOURCE_TABLE, "suggested_vendor_id", GUID, None),
]


# data-rewrite-ack: table=oe_procurement_requisition growth=tenure rows=one row per material requisition raised, accumulates across projects and years
# boot-repair: registry=procurement_requisition_delivery_date_from_order
def upgrade() -> None:
    """Add each column and its index when missing, then correct the stored delivery forecast."""
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

    if _REQ_TABLE not in tables:
        return
    req_columns = {c["name"] for c in sa.inspect(bind).get_columns(_REQ_TABLE)}
    if "estimated_delivery_date" not in req_columns or "po_id" not in req_columns:
        return
    op.execute(sa.text(f"UPDATE {_REQ_TABLE} SET estimated_delivery_date = NULL WHERE po_id IS NULL"))
    if _PO_TABLE in tables:
        op.execute(
            sa.text(
                f"UPDATE {_REQ_TABLE} SET estimated_delivery_date = "
                f"(SELECT po.delivery_date FROM {_PO_TABLE} po WHERE po.id = {_REQ_TABLE}.po_id) "
                "WHERE po_id IS NOT NULL"
            )
        )


def downgrade() -> None:
    """Drop the indexes, then the columns, each only when present. The data correction stays."""
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
