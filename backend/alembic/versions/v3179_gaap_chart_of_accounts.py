# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""GAAP general ledger - chart of accounts table.

Task #77: adds ``oe_finance_ledger_account``, the chart-of-accounts master that
every ``oe_finance_ledger.account_code`` maps to. Accounts are project- or
workspace-scoped (``project_id`` nullable), carry their account type
(asset/liability/equity/revenue/expense) and GAAP normal balance (debit/credit),
and a self-referential ``parent_id`` gives the roll-up hierarchy.

The embedded PostgreSQL runtime materialises this via ``create_all`` at startup,
so this migration is for external-PostgreSQL deployments that manage schema with
Alembic. The CREATE is guarded with a table-presence check so a re-run, or a DB
the runtime already auto-created, is a no-op. PostgreSQL-only, no SQLite shims.

Revision ID: v3179_gaap_chart_of_accounts
Revises: v3178_users_deleted_at
Create Date: 2026-06-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v3179_gaap_chart_of_accounts"
down_revision = "v3178_users_deleted_at"
branch_labels = None
depends_on = None

_TABLE = "oe_finance_ledger_account"


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def upgrade() -> None:
    if _has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        # GUID() stores as String(36); mirror the platform UUID column shape.
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=True, index=True),
        sa.Column("account_code", sa.String(100), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("account_type", sa.String(20), nullable=False, index=True),
        sa.Column("normal_balance", sa.String(10), nullable=False),
        sa.Column(
            "parent_id",
            sa.String(36),
            sa.ForeignKey("oe_finance_ledger_account.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("statement_section", sa.String(50), nullable=True),
        sa.Column("is_cash", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("currency_code", sa.String(10), nullable=False, server_default=""),
        sa.Column("metadata", sa.JSON, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("project_id", "account_code", name="uq_ledger_account_scope_code"),
        sa.Index("ix_ledger_account_project_type", "project_id", "account_type"),
    )


def downgrade() -> None:
    if _has_table(_TABLE):
        op.drop_table(_TABLE)
