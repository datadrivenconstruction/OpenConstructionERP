# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""measurement book entries and manual bar bending schedule rows

New tables only, inspector-guarded, so a database that ``create_all`` already built
reaches this revision and does nothing.

Revision ID: v3343_measurement_book_and_bbs
Revises: v3342_service_charges
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v3343_measurement_book_and_bbs"
down_revision: str | Sequence[str] | None = "v3342_service_charges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _num(name: str, precision: int = 18, scale: int = 4, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.Numeric(precision, scale), nullable=nullable)


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "oe_measurement_book_entry" not in tables:
        op.create_table(
            "oe_measurement_book_entry",
            *_base(),
            sa.Column(
                "project_id", GUID(), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column(
                "boq_position_id", GUID(), sa.ForeignKey("oe_boq_position.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("entry_date", sa.Date(), nullable=False),
            sa.Column("location", sa.String(255), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            _num("length"),
            _num("breadth"),
            _num("height"),
            _num("number"),
            _num("direct_quantity"),
            sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("measured_by", sa.String(255), nullable=False, server_default=""),
            sa.Column("check_status", sa.String(16), nullable=False, server_default="unchecked"),
            _num("check_quantity"),
            sa.Column("checked_by", sa.String(255), nullable=True),
            sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("bill_ref", sa.String(40), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        for col in ("project_id", "boq_position_id", "entry_date", "check_status"):
            op.create_index(f"ix_oe_measurement_book_entry_{col}", "oe_measurement_book_entry", [col])
    if "oe_rebar_bbs_entry" not in tables:
        op.create_table(
            "oe_rebar_bbs_entry",
            *_base(),
            sa.Column(
                "project_id", GUID(), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("member", sa.String(120), nullable=False),
            sa.Column("bar_mark", sa.String(32), nullable=False),
            _num("diameter_mm", 6, 2, nullable=False),
            sa.Column("shape_standard", sa.String(16), nullable=False),
            sa.Column("shape_code", sa.String(8), nullable=False),
            *[_num(f"dim_{d}", 10, 1) for d in "abcde"],
            sa.Column("members_count", sa.Integer(), nullable=False),
            sa.Column("bars_per_member", sa.Integer(), nullable=False),
            sa.Column("steel_grade", sa.String(32), nullable=True),
            _num("lap_length_mm", 10, 1),
            sa.Column("boq_position_id", GUID(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            _num("cut_length_mm", 10, 1, nullable=False),
            _num("unit_weight_kg_m", 10, 4, nullable=False),
            _num("total_length_m", 14, 3, nullable=False),
            _num("weight_kg", 14, 3, nullable=False),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("project_id", "member", "bar_mark", name="uq_rebar_bbs_member_mark"),
        )
        op.create_index("ix_oe_rebar_bbs_entry_project_id", "oe_rebar_bbs_entry", ["project_id"])
        op.create_index("ix_oe_rebar_bbs_entry_boq_position_id", "oe_rebar_bbs_entry", ["boq_position_id"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for name in ("oe_rebar_bbs_entry", "oe_measurement_book_entry"):
        if name in tables:
            op.drop_table(name)
