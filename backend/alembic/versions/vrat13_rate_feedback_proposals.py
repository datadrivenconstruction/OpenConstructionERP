# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""rate_feedback - proposals to update cost item rates from closed projects.

Creates ``oe_rate_feedback_proposal``. New table only, no data rewrite.
Inspector-guarded, so a database whose tables ``create_all`` already built is a no-op.

Revision ID: vrat13
Revises: vdee9_schedule_constraint_names
Create Date: 2026-11-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vrat13"
down_revision: str | Sequence[str] | None = "vles12_lessons_learned"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_T = "oe_rate_feedback_proposal"


def upgrade() -> None:
    if _T in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _T,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("cost_item_id", sa.String(36), sa.ForeignKey("oe_costs_item.id", ondelete="CASCADE"), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("current_rate", sa.Numeric(18, 4), nullable=False),
        sa.Column("suggested_rate", sa.Numeric(18, 4), nullable=False),
        sa.Column("variance_pct", sa.Numeric(9, 2), nullable=True),
        sa.Column("current_hours_per_unit", sa.Numeric(14, 4), nullable=True),
        sa.Column("observed_hours_per_unit", sa.Numeric(14, 4), nullable=True),
        sa.Column("hours_variance_pct", sa.Numeric(9, 2), nullable=True),
        sa.Column("project_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("line_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("spread_pct", sa.Numeric(9, 2), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.Column("project_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.String(36), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_rate", sa.Numeric(18, 4), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
    )
    op.create_index("ix_oe_rate_feedback_proposal_status", _T, ["status"])
    op.create_index("ix_oe_rate_feedback_proposal_item_status", _T, ["cost_item_id", "status"])


def downgrade() -> None:
    if _T in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(_T)
