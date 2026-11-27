# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Invoice lines name their order line, change orders split across commitments, invoices record their release

* ``oe_finance_invoice_item.po_line_id``: the purchase order line a supplier
  invoice line bills. Indexed.
* ``oe_finance_invoice.released_at`` / ``released_by`` / ``released_export_id``:
  when, by whom and in which booking export an approved invoice went to
  accounting.
* ``oe_changeorders_order.commitment_allocations``: the share of a change
  order that raises each order or subcontract it touches.

All nullable and additive, so the boot heal and ``alembic upgrade`` agree.

Revision ID: vpo02_po_lines_allocations_release
Revises: vreq01_requisition_value_bands
Create Date: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vpo02_po_lines_allocations_release"
down_revision: str | Sequence[str] | None = "vreq01_requisition_value_bands"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GUID = sa.String(36)
#: table -> columns it gains.
_COLUMNS: dict[str, tuple[tuple[str, sa.types.TypeEngine], ...]] = {
    "oe_finance_invoice_item": (("po_line_id", _GUID),),
    "oe_finance_invoice": (
        ("released_at", sa.String(40)),
        ("released_by", _GUID),
        ("released_export_id", _GUID),
    ),
    "oe_changeorders_order": (("commitment_allocations", sa.JSON()),),
}
_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_finance_invoice_item_po_line", "oe_finance_invoice_item", "po_line_id"),
)


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table, columns in _COLUMNS.items():
        if table not in tables:
            continue
        present = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
        missing = [(name, kind) for name, kind in columns if name not in present]
        if missing:
            with op.batch_alter_table(table) as batch:
                for name, kind in missing:
                    batch.add_column(sa.Column(name, kind, nullable=True))
    for name, table, column in _INDEXES:
        if table in tables and name not in {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(table)}:
            op.create_index(name, table, [column])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for name, table, _column in _INDEXES:
        if table in tables and name in {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(table)}:
            op.drop_index(name, table_name=table)
    for table, columns in _COLUMNS.items():
        if table not in tables:
            continue
        present = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
        dropping = [name for name, _ in columns if name in present]
        if dropping:
            with op.batch_alter_table(table) as batch:
                for name in dropping:
                    batch.drop_column(name)
