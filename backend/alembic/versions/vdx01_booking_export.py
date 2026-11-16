# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""booking export batches and invoice stamps

Additive only (two new tables); every step is guarded so it is safe on a database that
``create_all`` already built.

Revision ID: vdx01_booking_export
Revises: vpx01_payroll_hours_export
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vdx01_booking_export"
down_revision: str | Sequence[str] | None = "vpx01_payroll_hours_export"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BATCH = "oe_finance_booking_batch"
_ITEM = "oe_finance_booking_batch_item"


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if _BATCH not in tables:
        op.create_table(
            _BATCH,
            *_stamps(),
            sa.Column("number", sa.Integer(), nullable=False),
            sa.Column("connector_config_id", sa.String(36), nullable=True),
            sa.Column("connector_type", sa.String(50), nullable=False),
            sa.Column("period_from", sa.Date(), nullable=False),
            sa.Column("period_to", sa.Date(), nullable=False),
            sa.Column("reexport", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("invoice_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("filename", sa.String(200), nullable=False, server_default=""),
            sa.Column("sha256", sa.String(64), nullable=False, server_default=""),
            sa.Column("encoding", sa.String(20), nullable=False, server_default="utf-8"),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("findings", sa.JSON(), nullable=False),
            sa.Column("sync_log_id", sa.String(36), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("number", name="uq_oe_finance_booking_batch_number"),
        )
    if _ITEM not in tables:
        op.create_table(
            _ITEM,
            *_stamps(),
            sa.Column("batch_id", sa.String(36), sa.ForeignKey(f"{_BATCH}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("invoice_id", sa.String(36), nullable=False),
            sa.Column("invoice_number", sa.String(100), nullable=False, server_default=""),
        )
        op.create_index("ix_oe_finance_booking_batch_item_batch_id", _ITEM, ["batch_id"])
        op.create_index("ix_oe_finance_booking_batch_item_invoice_id", _ITEM, ["invoice_id"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (_ITEM, _BATCH):
        if table in tables:
            op.drop_table(table)
