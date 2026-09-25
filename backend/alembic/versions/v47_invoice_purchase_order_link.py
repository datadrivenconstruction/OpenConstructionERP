# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""finance - link a supplier invoice to the purchase order it bills against.

One nullable column, ``oe_finance_invoice.purchase_order_id``, and its index
``ix_invoice_purchase_order`` (declared once, in the model's
``__table_args__``, so ``create_all`` and this revision build the same name).

The column is plain ``VARCHAR(36)`` with no foreign key, matching ``GUID`` and
the cross-module convention: procurement is an optional module and an order may
be removed while the invoice and its payments survive.

DDL only, nothing is backfilled. Invoices that
``POST /procurement/{po_id}/create-invoice/`` raised before this revision carry
the same link as ``metadata["po_id"]``, and every reader accepts either
spelling (``app.modules.finance.po_link``). That is deliberate rather than a
gap: production gains this column through the boot schema heal, which adds
columns and never runs a backfill, so a reader that trusted the column alone
would lose those invoices on exactly the installs that matter.

Inspector-guarded, so an install whose schema came from ``create_all`` plus
the boot heal reaches this revision and adds nothing.

Revision ID: v47_invoice_purchase_order_link
Revises: v47_bid_award_links
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v47_invoice_purchase_order_link"
down_revision: Union[str, Sequence[str], None] = "v47_bid_award_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_finance_invoice"
_COLUMN = "purchase_order_id"
_INDEX = "ix_invoice_purchase_order"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return
    if _COLUMN not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=36), nullable=True))
    if _INDEX not in {ix["name"] for ix in inspector.get_indexes(_TABLE)}:
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return
    if _INDEX in {ix["name"] for ix in inspector.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    if _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.drop_column(_TABLE, _COLUMN)
