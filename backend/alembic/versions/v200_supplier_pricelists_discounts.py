# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""supplier_catalogs - contractor discounts, net prices, product links and item documents.

Additive only, no data rewrite:

* new table ``oe_supplier_catalogs_discount_agreement``: a contractor discount on a vendor's
  list prices, scoped to the vendor, one price list, one item category or one item;
* new table ``oe_supplier_catalogs_item_attachment``: links a documents row (datasheet,
  drawing) to a catalog item;
* nullable columns: ``catalog_item.product_url``; ``catalog_entry.net_price``,
  ``discount_pct``, ``discount_source``, ``discount_agreement_id``; ``po_line.gross_unit_price``,
  ``discount_pct``, ``discount_source``, ``catalog_entry_id``; ``pr_line.gross_unit_price``,
  ``discount_source``.

Every step is inspector-guarded, so a database whose tables ``create_all`` already built
reaches this revision and does nothing.

Revision ID: v200_supplier_pricelists_discounts
Revises: v199_subcontractor_contact_link
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v200_supplier_pricelists_discounts"
down_revision: str | Sequence[str] | None = "v199_subcontractor_contact_link"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_P = "oe_supplier_catalogs_"
_AGREEMENT = _P + "discount_agreement"
_ATTACHMENT = _P + "item_attachment"

_COLUMNS: dict[str, list[sa.Column]] = {
    _P + "catalog_item": [sa.Column("product_url", sa.String(1000), nullable=True)],
    _P + "catalog_entry": [
        sa.Column("net_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("discount_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("discount_source", sa.String(32), nullable=True),
        sa.Column("discount_agreement_id", GUID(), nullable=True),
    ],
    _P + "po_line": [
        sa.Column("gross_unit_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("discount_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("discount_source", sa.String(32), nullable=True),
        sa.Column("catalog_entry_id", GUID(), nullable=True),
    ],
    _P + "pr_line": [
        sa.Column("gross_unit_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("discount_source", sa.String(32), nullable=True),
    ],
}


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    """Create the two tables and add the columns when missing."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if _AGREEMENT not in tables and _P + "vendor" in tables:
        op.create_table(
            _AGREEMENT,
            *_stamps(),
            sa.Column("vendor_id", GUID(), sa.ForeignKey(_P + "vendor.id", ondelete="CASCADE"), nullable=False),
            sa.Column("price_list_id", GUID(), sa.ForeignKey(_P + "price_list.id", ondelete="CASCADE"), nullable=True),
            sa.Column("category_id", GUID(), sa.ForeignKey(_P + "item_category.id", ondelete="CASCADE"), nullable=True),
            sa.Column(
                "catalog_item_id", GUID(), sa.ForeignKey(_P + "catalog_item.id", ondelete="CASCADE"), nullable=True
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("reference", sa.String(100), nullable=True),
            sa.Column("discount_pct", sa.Numeric(7, 4), nullable=True),
            sa.Column("fixed_net_price", sa.Numeric(18, 4), nullable=True),
            sa.Column("valid_from", sa.String(20), nullable=True),
            sa.Column("valid_to", sa.String(20), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.create_index(f"ix_{_AGREEMENT}_vendor_id", _AGREEMENT, ["vendor_id"])
        op.create_index(f"ix_{_AGREEMENT}_price_list_id", _AGREEMENT, ["price_list_id"])

    if _ATTACHMENT not in tables and _P + "catalog_item" in tables:
        op.create_table(
            _ATTACHMENT,
            *_stamps(),
            sa.Column(
                "catalog_item_id",
                GUID(),
                sa.ForeignKey(_P + "catalog_item.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("document_id", GUID(), nullable=False),
            sa.Column("project_id", GUID(), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False, server_default="datasheet"),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("added_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("catalog_item_id", "document_id", name="uq_supplier_catalogs_item_attachment_doc"),
        )
        op.create_index(f"ix_{_ATTACHMENT}_catalog_item_id", _ATTACHMENT, ["catalog_item_id"])
        op.create_index(f"ix_{_ATTACHMENT}_document_id", _ATTACHMENT, ["document_id"])

    for table, columns in _COLUMNS.items():
        if table not in tables:
            continue
        present = {c["name"] for c in insp.get_columns(table)}
        for column in columns:
            if column.name not in present:
                op.add_column(table, column.copy())


def downgrade() -> None:
    """Drop the columns and the two tables when present."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for table, columns in _COLUMNS.items():
        if table not in tables:
            continue
        present = {c["name"] for c in insp.get_columns(table)}
        for column in columns:
            if column.name in present:
                op.drop_column(table, column.name)
    for table in (_ATTACHMENT, _AGREEMENT):
        if table in tables:
            op.drop_table(table)
