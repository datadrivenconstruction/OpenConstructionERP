# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""procurement - material certificates, receiving requirements and receipt follow-ups (BF-01).

One new table, ``oe_procurement_gr_cert``: a material certificate (EN 10204 2.1 to 3.2 or any
other type of the certificate catalogue) delivered with one goods receipt line, with its number,
issuer, date, the attached document and the batch or heat number. It cascades with its line and
with its receipt.

Columns added to existing tables, all nullable or with a server default, so the auto-migrator
brings a running installation to the same shape on boot:

* ``oe_procurement_po_item.required_certificate_type`` and ``requires_inspection``: what a
  delivery of the line must arrive with.
* ``oe_procurement_goods_receipt.source``, ``portal_user_id`` (indexed), ``approval_instance_id``
  and ``inspection_id``: who put the receipt on file and the follow-ups started on confirmation.

Every constraint and index name is written out, matches the models and stays under 63
characters. Every step is inspector-guarded, so a database whose tables ``create_all`` already
built reaches this revision and does nothing. No data is written.

Revision ID: v83_bf01_supply_chain
Revises: v82_requisition_item_sources
Create Date: 2026-10-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v83_bf01_supply_chain"
down_revision: str | Sequence[str] | None = "v82_requisition_item_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PO_ITEM = "oe_procurement_po_item"
_GR = "oe_procurement_goods_receipt"
_GR_ITEM = "oe_procurement_gr_item"
_CERT = "oe_procurement_gr_cert"
_GR_PORTAL_INDEX = "ix_oe_procurement_goods_receipt_portal_user_id"
_CERT_INDEXES: list[tuple[str, list[str]]] = [
    ("ix_oe_procurement_gr_cert_receipt_id", ["receipt_id"]),
    ("ix_oe_procurement_gr_cert_gr_item_id", ["gr_item_id"]),
]


def _columns(bind: sa.engine.Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _indexes(bind: sa.engine.Connection, table: str) -> set[str]:
    return {ix["name"] for ix in sa.inspect(bind).get_indexes(table)}


def upgrade() -> None:
    """Add the requirement and provenance columns, then the certificate table; each only when missing."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if _PO_ITEM in tables:
        have = _columns(bind, _PO_ITEM)
        if "required_certificate_type" not in have:
            op.add_column(_PO_ITEM, sa.Column("required_certificate_type", sa.String(length=40), nullable=True))
        if "requires_inspection" not in have:
            op.add_column(
                _PO_ITEM,
                sa.Column("requires_inspection", sa.Boolean(), nullable=False, server_default=sa.false()),
            )

    if _GR in tables:
        have = _columns(bind, _GR)
        if "source" not in have:
            op.add_column(_GR, sa.Column("source", sa.String(length=30), nullable=False, server_default="site"))
        for name in ("portal_user_id", "approval_instance_id", "inspection_id"):
            if name not in have:
                op.add_column(_GR, sa.Column(name, GUID(), nullable=True))
        if _GR_PORTAL_INDEX not in _indexes(bind, _GR):
            op.create_index(_GR_PORTAL_INDEX, _GR, ["portal_user_id"])

    if _CERT not in tables:
        op.create_table(
            _CERT,
            sa.Column("id", GUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column(
                "receipt_id",
                GUID(),
                sa.ForeignKey(f"{_GR}.id", ondelete="CASCADE", name="fk_oe_procurement_gr_cert_receipt_id"),
                nullable=False,
            ),
            sa.Column(
                "gr_item_id",
                GUID(),
                sa.ForeignKey(f"{_GR_ITEM}.id", ondelete="CASCADE", name="fk_oe_procurement_gr_cert_gr_item_id"),
                nullable=False,
            ),
            sa.Column("certificate_type", sa.String(length=40), nullable=False),
            sa.Column("certificate_number", sa.String(length=100), nullable=False, server_default=""),
            sa.Column("issuer", sa.String(length=255), nullable=True),
            sa.Column("issue_date", sa.String(length=40), nullable=True),
            sa.Column("document_id", GUID(), nullable=True),
            sa.Column("batch_number", sa.String(length=100), nullable=True),
            sa.Column("source", sa.String(length=30), nullable=False, server_default="site"),
            sa.Column("created_by", sa.String(length=36), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_oe_procurement_gr_cert"),
        )
    existing = _indexes(bind, _CERT)
    for name, cols in _CERT_INDEXES:
        if name not in existing:
            op.create_index(name, _CERT, cols)


def downgrade() -> None:
    """Drop the certificate table, then the added columns."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if _CERT in tables:
        op.drop_table(_CERT)
    if _GR in tables:
        if _GR_PORTAL_INDEX in _indexes(bind, _GR):
            op.drop_index(_GR_PORTAL_INDEX, table_name=_GR)
        have = _columns(bind, _GR)
        with op.batch_alter_table(_GR) as batch:
            for name in ("inspection_id", "approval_instance_id", "portal_user_id", "source"):
                if name in have:
                    batch.drop_column(name)
    if _PO_ITEM in tables:
        have = _columns(bind, _PO_ITEM)
        with op.batch_alter_table(_PO_ITEM) as batch:
            for name in ("requires_inspection", "required_certificate_type"):
                if name in have:
                    batch.drop_column(name)
