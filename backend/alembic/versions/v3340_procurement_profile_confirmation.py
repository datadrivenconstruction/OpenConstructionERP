# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""procurement concept - per-instance confirmations of procurement profile values.

One new table, nothing existing touched. A row says that this instance (tenant)
checked one profile value, identified by jurisdiction, path and value hash,
against a source. A changed value has a new hash and is unconfirmed again.
Inspector-guarded.

Revision ID: v3340_procurement_profile_confirmation
Revises: v3331_cost_benchmarks_payroll_periods
Create Date: 2026-10-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v3340_procurement_profile_confirmation"
down_revision: str | Sequence[str] | None = "v3331_cost_benchmarks_payroll_periods"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_procurement_concept_profile_confirmation"


def upgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("jurisdiction", sa.String(6), nullable=False),
        sa.Column("path", sa.String(255), nullable=False),
        sa.Column("value_hash", sa.String(64), nullable=False),
        sa.Column("confirmed_by", GUID(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_checked", sa.String(1000), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.UniqueConstraint("tenant_id", "jurisdiction", "path", "value_hash", name="uq_oe_pcc_profile_confirmation"),
    )
    op.create_index("ix_oe_pcc_profile_confirmation_tenant", _TABLE, ["tenant_id", "jurisdiction"])


def downgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(_TABLE)
