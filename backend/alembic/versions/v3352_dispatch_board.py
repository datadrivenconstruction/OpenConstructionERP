# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""dispatch module: board columns, crews, placements, scheduled moves, view preferences

Creates ``oe_dispatch_location``, ``oe_dispatch_crew``, ``oe_dispatch_placement``,
``oe_dispatch_scheduled_move`` and ``oe_dispatch_view_pref``. New tables only,
inspector-guarded, so a database that ``create_all`` already built does nothing.

Revision ID: v3352_dispatch_board
Revises: v3327_accounting_sync
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v3352_dispatch_board"
down_revision: str | Sequence[str] | None = "v3327_accounting_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "oe_dispatch_location" not in tables:
        op.create_table(
            "oe_dispatch_location",
            *_base(),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False, server_default="project"),
            sa.Column(
                "project_id", GUID(), sa.ForeignKey("oe_projects_project.id", ondelete="SET NULL"), nullable=True
            ),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.create_index("ix_oe_dispatch_location_project_id", "oe_dispatch_location", ["project_id"])
        op.create_index("ix_dispatch_location_kind_active", "oe_dispatch_location", ["kind", "is_active"])
    if "oe_dispatch_crew" not in tables:
        op.create_table(
            "oe_dispatch_crew",
            *_base(),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("foreman_resource_id", sa.String(36), nullable=True),
            sa.Column("foreman_user_id", GUID(), nullable=True),
            sa.Column("member_ids", sa.JSON(), nullable=False),
            sa.Column("min_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("trade", sa.String(120), nullable=False, server_default=""),
            sa.Column("labor_crew_id", GUID(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.create_index("ix_oe_dispatch_crew_foreman_user_id", "oe_dispatch_crew", ["foreman_user_id"])
    if "oe_dispatch_placement" not in tables:
        op.create_table(
            "oe_dispatch_placement",
            *_base(),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("card_kind", sa.String(20), nullable=False),
            sa.Column("card_ref", sa.String(36), nullable=False),
            sa.Column(
                "location_id",
                GUID(),
                sa.ForeignKey("oe_dispatch_location.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("operator_ref", sa.String(36), nullable=True),
            sa.Column("start_time", sa.String(5), nullable=False, server_default="07:00"),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.UniqueConstraint(
                "day", "card_kind", "card_ref", "location_id", name="uq_dispatch_placement_card_day_loc"
            ),
        )
        op.create_index("ix_dispatch_placement_day_loc", "oe_dispatch_placement", ["day", "location_id"])
        op.create_index("ix_dispatch_placement_card_day", "oe_dispatch_placement", ["card_kind", "card_ref", "day"])
    if "oe_dispatch_scheduled_move" not in tables:
        op.create_table(
            "oe_dispatch_scheduled_move",
            *_base(),
            sa.Column("card_kind", sa.String(20), nullable=False),
            sa.Column("card_ref", sa.String(36), nullable=False),
            sa.Column(
                "to_location_id",
                GUID(),
                sa.ForeignKey("oe_dispatch_location.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("effective_date", sa.Date(), nullable=False),
            sa.Column("start_time", sa.String(5), nullable=False, server_default="07:00"),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_dispatch_move_status_date", "oe_dispatch_scheduled_move", ["status", "effective_date"])
    if "oe_dispatch_view_pref" not in tables:
        op.create_table(
            "oe_dispatch_view_pref",
            *_base(),
            sa.Column("user_id", GUID(), nullable=False, unique=True),
            sa.Column("card_density", sa.String(10), nullable=False, server_default="detailed"),
            sa.Column("settings", sa.JSON(), nullable=False),
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for name in (
        "oe_dispatch_view_pref",
        "oe_dispatch_scheduled_move",
        "oe_dispatch_placement",
        "oe_dispatch_crew",
        "oe_dispatch_location",
    ):
        if name in tables:
            op.drop_table(name)
