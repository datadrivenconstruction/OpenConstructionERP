# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""bid outcome ledger: one row per submitted bid and how it ended

Revision ID: vwin12
Revises: vdee9_schedule_constraint_names
Create Date: 2026-11-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vwin12"
down_revision: str | Sequence[str] | None = "vdee9_schedule_constraint_names"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_T = "oe_win_loss_entry"


def upgrade() -> None:
    if _T in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _T,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("client_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("trade", sa.String(100), nullable=False, server_default=""),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("tender_id", sa.String(36), nullable=True),
        sa.Column("submitted_on", sa.Date(), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("currency", sa.String(10), nullable=False, server_default=""),
        sa.Column("our_price", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("winning_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("second_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("competitor_count", sa.Integer(), nullable=True),
        sa.Column("lost_reason", sa.String(30), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
    )
    for col in ("client_name", "trade", "project_id", "outcome"):
        op.create_index(f"ix_{_T}_{col}", _T, [col])
    op.create_index("ux_win_loss_tender", _T, ["tender_id"], unique=True)


def downgrade() -> None:
    op.drop_table(_T)
