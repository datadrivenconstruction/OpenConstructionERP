# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""bid_day: the live bid-day board, its change log and submitted snapshots

Creates ``oe_bid_day_board``, ``oe_bid_day_row``, ``oe_bid_day_quote``,
``oe_bid_day_event`` and ``oe_bid_day_snapshot``. New tables only; nothing
existing changes.

Revision ID: v3351_bid_day
Revises: v3327_accounting_sync
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v3351_bid_day"
down_revision: str | Sequence[str] | None = "v3327_accounting_sync"
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
    if "oe_bid_day_board" not in existing:
        op.create_table(
            "oe_bid_day_board",
            *_stamps(),
            sa.Column(
                "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("tender_id", sa.String(36), nullable=False, unique=True),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("overhead_pct", sa.String(20), nullable=False, server_default="0"),
            sa.Column("risk_pct", sa.String(20), nullable=False, server_default="0"),
            sa.Column("profit_pct", sa.String(20), nullable=False, server_default="0"),
            sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("markup_rev", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_bid_day_board_project_id", "oe_bid_day_board", ["project_id"])
    if "oe_bid_day_row" not in existing:
        op.create_table(
            "oe_bid_day_row",
            *_stamps(),
            sa.Column(
                "board_id", sa.String(36), sa.ForeignKey("oe_bid_day_board.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("bid_package_id", sa.String(36), nullable=True),
            sa.Column("name", sa.String(500), nullable=False, server_default=""),
            sa.Column("kind", sa.String(20), nullable=False, server_default="subcontract"),
            sa.Column("plug_amount", sa.String(50), nullable=False, server_default="0"),
            sa.Column("chosen_quote_id", sa.String(36), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rev", sa.Integer(), nullable=False, server_default="1"),
        )
        op.create_index("ix_oe_bid_day_row_board_id", "oe_bid_day_row", ["board_id"])
    if "oe_bid_day_quote" not in existing:
        op.create_table(
            "oe_bid_day_quote",
            *_stamps(),
            sa.Column("row_id", sa.String(36), sa.ForeignKey("oe_bid_day_row.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source", sa.String(20), nullable=False, server_default="late"),
            sa.Column("source_ref", sa.String(36), nullable=True),
            sa.Column("channel", sa.String(20), nullable=False, server_default="portal"),
            sa.Column("vendor", sa.String(255), nullable=False, server_default=""),
            sa.Column("amount", sa.String(50), nullable=False, server_default="0"),
            sa.Column("source_amount", sa.String(50), nullable=True),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("fx_rate", sa.String(30), nullable=False, server_default="1"),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("exclusions", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("rev", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_bid_day_quote_row_id", "oe_bid_day_quote", ["row_id"])
        op.create_index("ix_bid_day_quote_source", "oe_bid_day_quote", ["source", "source_ref"])
    if "oe_bid_day_event" not in existing:
        op.create_table(
            "oe_bid_day_event",
            *_stamps(),
            sa.Column(
                "board_id", sa.String(36), sa.ForeignKey("oe_bid_day_board.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("user_id", sa.String(36), nullable=True),
            sa.Column("user_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("message", sa.Text(), nullable=False, server_default=""),
            sa.Column("delta", sa.String(50), nullable=False, server_default="0"),
            sa.Column("total_after", sa.String(50), nullable=False, server_default="0"),
            sa.Column("params", sa.JSON(), nullable=False, server_default="{}"),
        )
        op.create_index("ix_bid_day_event_board_created", "oe_bid_day_event", ["board_id", "created_at"])
    if "oe_bid_day_snapshot" not in existing:
        op.create_table(
            "oe_bid_day_snapshot",
            *_stamps(),
            sa.Column(
                "board_id", sa.String(36), sa.ForeignKey("oe_bid_day_board.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("project_id", sa.String(36), nullable=False),
            sa.Column("tender_id", sa.String(36), nullable=False),
            sa.Column("submitted_by", sa.String(36), nullable=True),
            sa.Column("submitted_by_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("bid_total", sa.String(50), nullable=False, server_default="0"),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
        )
        for col in ("board_id", "project_id", "tender_id"):
            op.create_index(f"ix_oe_bid_day_snapshot_{col}", "oe_bid_day_snapshot", [col])


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("oe_bid_day_snapshot", "oe_bid_day_event", "oe_bid_day_quote", "oe_bid_day_row", "oe_bid_day_board"):
        if table in existing:
            op.drop_table(table)
