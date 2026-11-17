# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""accounting_sync: cost-centre and supplier maps, export batches, ledger imports

Adds ``oe_acctsync_costcode_map``, ``oe_acctsync_supplier_map``,
``oe_acctsync_export_batch`` (numbered, hashed export files),
``oe_acctsync_batch_item`` (one active batch per record) and
``oe_acctsync_import`` (ledger lines read from a books file).

Revision ID: vacx01_accounting_export_batches
Revises: vsai01_site_assistant_prefs
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vacx01_accounting_export_batches"
down_revision: str | Sequence[str] | None = "vsai01_site_assistant_prefs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONN = "oe_acctsync_connection"
_CC = "oe_acctsync_costcode_map"
_SUP = "oe_acctsync_supplier_map"
_BATCH = "oe_acctsync_export_batch"
_ITEM = "oe_acctsync_batch_item"
_IMP = "oe_acctsync_import"


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _fk(name: str, table: str) -> sa.Column:
    return sa.Column(name, sa.String(36), sa.ForeignKey(f"{table}.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _CC not in tables:
        op.create_table(
            _CC,
            *_base(),
            _fk("connection_id", _CONN),
            sa.Column("platform_code", sa.String(60), nullable=False),
            sa.Column("standard", sa.String(40), nullable=False, server_default="project"),
            sa.Column("external_cost_center", sa.String(40), nullable=False, server_default=""),
            sa.UniqueConstraint("connection_id", "platform_code", "standard", name="uq_acctsync_costcode_map"),
        )
        op.create_index(f"ix_{_CC}_connection_id", _CC, ["connection_id"])
    if _SUP not in tables:
        op.create_table(
            _SUP,
            *_base(),
            _fk("connection_id", _CONN),
            sa.Column("contact_id", sa.String(80), nullable=False),
            sa.Column("external_account", sa.String(40), nullable=False, server_default=""),
            sa.UniqueConstraint("connection_id", "contact_id", name="uq_acctsync_supplier_map"),
        )
        op.create_index(f"ix_{_SUP}_connection_id", _SUP, ["connection_id"])
    if _BATCH not in tables:
        op.create_table(
            _BATCH,
            *_base(),
            _fk("connection_id", _CONN),
            sa.Column("batch_no", sa.Integer(), nullable=False),
            sa.Column("format", sa.String(20), nullable=False),
            sa.Column("period_from", sa.Date(), nullable=False),
            sa.Column("period_to", sa.Date(), nullable=False),
            sa.Column("record_types", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_net", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("total_tax", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("total_gross", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("sha256", sa.String(64), nullable=False, server_default=""),
            sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
            sa.Column("idempotency_key", sa.String(120), nullable=True),
            sa.Column("file_name", sa.String(200), nullable=False, server_default=""),
            sa.Column("media_type", sa.String(80), nullable=False, server_default=""),
            sa.Column("content", sa.LargeBinary(), nullable=True),
            sa.Column("void_reason", sa.Text(), nullable=True),
            sa.Column("voided_by", sa.String(36), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("connection_id", "batch_no", name="uq_acctsync_batch_no"),
            sa.UniqueConstraint("connection_id", "idempotency_key", name="uq_acctsync_batch_idem"),
        )
        op.create_index(f"ix_{_BATCH}_connection_id", _BATCH, ["connection_id"])
    if _ITEM not in tables:
        op.create_table(
            _ITEM,
            *_base(),
            _fk("batch_id", _BATCH),
            _fk("connection_id", _CONN),
            sa.Column("record_type", sa.String(30), nullable=False),
            sa.Column("record_id", sa.String(80), nullable=False),
            sa.Column("payload_hash", sa.String(64), nullable=False, server_default=""),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.create_index(f"ix_{_ITEM}_batch_id", _ITEM, ["batch_id"])
        op.create_index(
            "uq_acctsync_batch_item_active",
            _ITEM,
            ["connection_id", "record_type", "record_id"],
            unique=True,
            postgresql_where=sa.text("active"),
        )
    if _IMP not in tables:
        op.create_table(
            _IMP,
            *_base(),
            _fk("connection_id", _CONN),
            sa.Column("import_id", sa.String(36), nullable=False),
            sa.Column("file_name", sa.String(200), nullable=False, server_default=""),
            sa.Column("line_no", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("posting_date", sa.Date(), nullable=True),
            sa.Column("document_number", sa.String(80), nullable=False, server_default=""),
            sa.Column("account", sa.String(40), nullable=False, server_default=""),
            sa.Column("debit", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("credit", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column("payment_status", sa.String(20), nullable=False, server_default=""),
            sa.Column("description", sa.String(255), nullable=False, server_default=""),
        )
        op.create_index(f"ix_{_IMP}_connection_id", _IMP, ["connection_id"])
        op.create_index(f"ix_{_IMP}_import_id", _IMP, ["import_id"])
        op.create_index("ix_acctsync_import_conn_doc", _IMP, ["connection_id", "document_number"])


def downgrade() -> None:
    for table in (_IMP, _ITEM, _BATCH, _SUP, _CC):
        op.drop_table(table)
