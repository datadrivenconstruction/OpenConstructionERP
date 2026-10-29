# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""accounting_sync​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: connections, mappings, external ids and the sync log

Creates the five tables of the accounting sync module: ``oe_acctsync_connection``
(one company ledger in Xero, QuickBooks Online or a file target, OAuth secrets
encrypted), ``oe_acctsync_account_map`` and ``oe_acctsync_tax_map`` (mapping per
connection), ``oe_acctsync_external_ref`` (remote id per pushed record, the
idempotency anchor) and ``oe_acctsync_log`` (one row per record attempt).

Revision ID: v3327_accounting_sync
Revises: v3331_user_avatar_key
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v3327_accounting_sync"
down_revision: str | Sequence[str] | None = "v3331_user_avatar_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONN = "oe_acctsync_connection"
_ACC = "oe_acctsync_account_map"
_TAX = "oe_acctsync_tax_map"
_REF = "oe_acctsync_external_ref"
_LOG = "oe_acctsync_log"


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _conn_fk() -> sa.Column:
    return sa.Column("connection_id", sa.String(36), sa.ForeignKey(f"{_CONN}.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _CONN not in tables:
        op.create_table(
            _CONN,
            *_base(),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("provider", sa.String(30), nullable=False),
            sa.Column("country_code", sa.String(2), nullable=True),
            sa.Column("chart_template", sa.String(40), nullable=False, server_default="generic"),
            sa.Column("base_currency", sa.String(3), nullable=False, server_default="EUR"),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("is_sandbox", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("client_id", sa.String(255), nullable=True),
            sa.Column("client_secret_enc", sa.Text(), nullable=True),
            sa.Column("tokens_enc", sa.Text(), nullable=True),
            sa.Column("external_tenant_id", sa.String(120), nullable=True),
            sa.Column("lock_date", sa.Date(), nullable=True),
            sa.Column("project_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("last_sync_at", sa.String(40), nullable=True),
            sa.Column("last_sync_status", sa.String(20), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("name", name="uq_acctsync_connection_name"),
        )
    if _ACC not in tables:
        op.create_table(
            _ACC,
            *_base(),
            _conn_fk(),
            sa.Column("category", sa.String(60), nullable=False),
            sa.Column("account_code", sa.String(40), nullable=False, server_default=""),
            sa.Column("account_name", sa.String(255), nullable=False, server_default=""),
            sa.UniqueConstraint("connection_id", "category", name="uq_acctsync_account_map"),
        )
        op.create_index(f"ix_{_ACC}_connection_id", _ACC, ["connection_id"])
    if _TAX not in tables:
        op.create_table(
            _TAX,
            *_base(),
            _conn_fk(),
            sa.Column("tax_code", sa.String(40), nullable=False),
            sa.Column("direction", sa.String(10), nullable=False),
            sa.Column("external_code", sa.String(40), nullable=False, server_default=""),
            sa.Column("rate_pct", sa.Numeric(7, 4), nullable=True),
            sa.UniqueConstraint("connection_id", "tax_code", "direction", name="uq_acctsync_tax_map"),
        )
        op.create_index(f"ix_{_TAX}_connection_id", _TAX, ["connection_id"])
    if _REF not in tables:
        op.create_table(
            _REF,
            *_base(),
            _conn_fk(),
            sa.Column("record_type", sa.String(30), nullable=False),
            sa.Column("record_id", sa.String(80), nullable=False),
            sa.Column("external_id", sa.String(120), nullable=False),
            sa.Column("external_version", sa.String(40), nullable=True),
            sa.Column("payload_hash", sa.String(64), nullable=False, server_default=""),
            sa.Column("pushed_total", sa.Numeric(18, 2), nullable=True),
            sa.Column("remote_total", sa.Numeric(18, 2), nullable=True),
            sa.Column("last_pushed_at", sa.String(40), nullable=True),
            sa.UniqueConstraint("connection_id", "record_type", "record_id", name="uq_acctsync_external_ref"),
        )
        op.create_index(f"ix_{_REF}_connection_id", _REF, ["connection_id"])
    if _LOG not in tables:
        op.create_table(
            _LOG,
            *_base(),
            _conn_fk(),
            sa.Column("project_id", sa.String(36), nullable=True),
            sa.Column("action", sa.String(20), nullable=False),
            sa.Column("record_type", sa.String(30), nullable=False),
            sa.Column("record_id", sa.String(80), nullable=False, server_default=""),
            sa.Column("record_label", sa.String(255), nullable=False, server_default=""),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("error_reason", sa.Text(), nullable=True),
            sa.Column("external_id", sa.String(120), nullable=True),
            sa.Column("amount", sa.Numeric(18, 2), nullable=True),
            sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
        )
        op.create_index(f"ix_{_LOG}_connection_id", _LOG, ["connection_id"])
        op.create_index(f"ix_{_LOG}_project_id", _LOG, ["project_id"])
        op.create_index("ix_acctsync_log_conn_status", _LOG, ["connection_id", "status"])
        op.create_index("ix_acctsync_log_record", _LOG, ["connection_id", "record_type", "record_id"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for name in (_LOG, _REF, _TAX, _ACC, _CONN):
        if name in tables:
            op.drop_table(name)
