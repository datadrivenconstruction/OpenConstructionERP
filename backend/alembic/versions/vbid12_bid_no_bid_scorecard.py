# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""bid_no_bid: the tender scorecard and its audit trail

Creates ``oe_bid_no_bid_scorecard`` and ``oe_bid_no_bid_event``. New tables only; nothing existing changes.

Revision ID: vbid12
Revises: vdee9_schedule_constraint_names
Create Date: 2026-11-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vbid12"
down_revision: str | Sequence[str] | None = "vwin12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "oe_bid_no_bid_scorecard" not in existing:
        op.create_table(
            "oe_bid_no_bid_scorecard",
            *_stamps(),
            sa.Column(
                "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("tender_id", sa.String(36), nullable=False, unique=True),
            sa.Column("opportunity_id", sa.String(36), nullable=True),
            sa.Column("weights", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("scores", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("notes", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("threshold", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("decision", sa.String(10), nullable=False, server_default=""),
            sa.Column("decision_reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("decided_by", sa.String(36), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_bid_no_bid_scorecard_project_id", "oe_bid_no_bid_scorecard", ["project_id"])
    if "oe_bid_no_bid_event" not in existing:
        op.create_table(
            "oe_bid_no_bid_event",
            *_stamps(),
            sa.Column(
                "scorecard_id",
                sa.String(36),
                sa.ForeignKey("oe_bid_no_bid_scorecard.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("user_id", sa.String(36), nullable=True),
            sa.Column("user_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("kind", sa.String(30), nullable=False),
            sa.Column("message", sa.Text(), nullable=False, server_default=""),
            sa.Column("params", sa.JSON(), nullable=False, server_default="{}"),
        )
        op.create_index("ix_bid_no_bid_event_card_created", "oe_bid_no_bid_event", ["scorecard_id", "created_at"])


def downgrade() -> None:
    op.drop_table("oe_bid_no_bid_event")
    op.drop_table("oe_bid_no_bid_scorecard")
