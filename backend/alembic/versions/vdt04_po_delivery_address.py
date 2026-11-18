# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""procurement - delivery address on the purchase order.

One nullable column, ``oe_procurement_po.delivery_address`` (model
``PurchaseOrder.delivery_address``): where the goods go, printed on the order
the supplier receives.

This one does NOT need running by hand. It adds a nullable column and nothing
else, and the boot schema heal adds it from the model on a running install.
Inspector-guarded, so a re-run or a downgrade on a database without the column
changes nothing.

Revision ID: vdt04_po_delivery_address
Revises: vdt03_doc_layouts
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "vdt04_po_delivery_address"
down_revision: Union[str, Sequence[str], None] = "vdt03_doc_layouts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_procurement_po"
_COLUMN = "delivery_address"


def _columns() -> set[str] | None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return None
    return {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    """Add the delivery address column."""
    columns = _columns()
    if columns is not None and _COLUMN not in columns:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(500), nullable=True))


def downgrade() -> None:
    """Drop the delivery address column."""
    columns = _columns()
    if columns is not None and _COLUMN in columns:
        op.drop_column(_TABLE, _COLUMN)
