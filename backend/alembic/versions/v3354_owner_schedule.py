# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""owner_schedule: owner bid schedule profiles, schedules and pay items

Creates ``oe_owner_schedule_profile`` (profiles saved from the mapping wizard),
``oe_owner_schedule`` (one owner schedule per BOQ with the owner's latest file)
and ``oe_owner_schedule_item`` (the owner's pay items and the pricing position).

Revision ID: v3354_owner_schedule
Revises: v3353_haul_tickets
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v3354_owner_schedule"
down_revision: str | Sequence[str] | None = "v3353_haul_tickets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROFILE = "oe_owner_schedule_profile"
_SCHED = "oe_owner_schedule"
_ITEM = "oe_owner_schedule_item"


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _PROFILE not in tables:
        op.create_table(
            _PROFILE,
            *_base(),
            sa.Column("key", sa.String(80), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("definition", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("key", name="uq_owner_schedule_profile_key"),
        )
    if _SCHED not in tables:
        op.create_table(
            _SCHED,
            *_base(),
            sa.Column(
                "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("boq_id", sa.String(36), sa.ForeignKey("oe_boq_boq.id", ondelete="CASCADE"), nullable=False),
            sa.Column("profile_key", sa.String(80), nullable=False),
            sa.Column("profile", sa.JSON(), nullable=False),
            sa.Column("file_name", sa.String(255), nullable=False),
            sa.Column("file_content", sa.LargeBinary(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("boq_id", name="uq_owner_schedule_boq"),
        )
        op.create_index(f"ix_{_SCHED}_project_id", _SCHED, ["project_id"])
        op.create_index(f"ix_{_SCHED}_boq_id", _SCHED, ["boq_id"])
    if _ITEM not in tables:
        op.create_table(
            _ITEM,
            *_base(),
            sa.Column("schedule_id", sa.String(36), sa.ForeignKey(f"{_SCHED}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("row_index", sa.Integer(), nullable=False),
            sa.Column("item_no", sa.String(80), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("unit", sa.String(40), nullable=False, server_default=""),
            sa.Column("quantity", sa.Numeric(20, 6), nullable=True),
            sa.Column("is_section", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_alternate", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_lump_sum", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("removed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "position_id", sa.String(36), sa.ForeignKey("oe_boq_position.id", ondelete="SET NULL"), nullable=True
            ),
            sa.UniqueConstraint("schedule_id", "item_no", name="uq_owner_schedule_item_no"),
        )
        op.create_index(f"ix_{_ITEM}_schedule_id", _ITEM, ["schedule_id"])
        op.create_index(f"ix_{_ITEM}_position_id", _ITEM, ["position_id"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for name in (_ITEM, _SCHED, _PROFILE):
        if name in tables:
            op.drop_table(name)
