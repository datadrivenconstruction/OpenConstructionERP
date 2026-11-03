# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""supplier invoice inbox: purchase order link

Adds ``purchase_order_id`` and ``po_reference`` to ``oe_finance_captured_invoice``
so a captured invoice can be matched against its order and goods receipts.

Revision ID: vap01_inbox_po_match
Revises: vbm01_budget_ledger
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vap01_inbox_po_match"
down_revision: str | Sequence[str] | None = "vbm01_budget_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_finance_captured_invoice"
_INDEX = "ix_oe_finance_captured_invoice_purchase_order_id"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    if "purchase_order_id" not in existing:
        op.add_column(_TABLE, sa.Column("purchase_order_id", sa.String(36), nullable=True))
    if "po_reference" not in existing:
        op.add_column(_TABLE, sa.Column("po_reference", sa.String(100), nullable=True))
    if _INDEX not in {i["name"] for i in inspector.get_indexes(_TABLE)}:
        op.create_index(_INDEX, _TABLE, ["purchase_order_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if _INDEX in {i["name"] for i in inspector.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    for name in ("po_reference", "purchase_order_id"):
        if name in existing:
            op.drop_column(_TABLE, name)
