# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""one order and one receipt per delivery: event effects and stock identity on order lines

Creates ``oe_event_effect`` (once-only claims for event side effects) and adds
the catalogue item and warehouse an order line is delivered against to
``oe_procurement_po_item``.

Revision ID: vdup9_orders_receipts_role_split
Revises: vai01_doc_assistant_agent_catalogue
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vdup9_orders_receipts_role_split"
down_revision: str | Sequence[str] | None = "vai01_doc_assistant_agent_catalogue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EFFECT = "oe_event_effect"
_ITEM = "oe_procurement_po_item"


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _EFFECT not in insp.get_table_names():
        op.create_table(
            _EFFECT,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("key", sa.String(200), nullable=False),
            sa.Column("effect", sa.String(100), nullable=False, server_default=""),
        )
        op.create_index("ix_oe_event_effect_key", _EFFECT, ["key"], unique=True)

    have = _columns(_ITEM)
    if "catalog_item_id" not in have:
        op.add_column(_ITEM, sa.Column("catalog_item_id", sa.String(36), nullable=True))
        op.create_index("ix_oe_procurement_po_item_catalog_item_id", _ITEM, ["catalog_item_id"])
    if "warehouse_id" not in have:
        op.add_column(_ITEM, sa.Column("warehouse_id", sa.String(36), nullable=True))


def downgrade() -> None:
    have = _columns(_ITEM)
    if "warehouse_id" in have:
        op.drop_column(_ITEM, "warehouse_id")
    if "catalog_item_id" in have:
        op.drop_index("ix_oe_procurement_po_item_catalog_item_id", table_name=_ITEM)
        op.drop_column(_ITEM, "catalog_item_id")
    if _EFFECT in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(_EFFECT)
