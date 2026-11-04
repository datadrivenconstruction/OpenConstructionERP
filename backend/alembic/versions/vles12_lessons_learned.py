# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Lessons learned register: oe_lessons_learned_lesson

Revision ID: vles12_lessons_learned
Revises: vdee9_schedule_constraint_names
Create Date: 2026-11-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "vles12_lessons_learned"
down_revision: str | Sequence[str] | None = "vbid12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_lessons_learned_lesson"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _TABLE in set(insp.get_table_names()):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "project_id",
            GUID(),
            sa.ForeignKey(
                "oe_projects_project.id", ondelete="CASCADE", name="fk_oe_lessons_learned_lesson_project_id_project"
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("recommendation", sa.Text(), nullable=False, server_default=""),
        sa.Column("trade", sa.String(100), nullable=False, server_default=""),
        sa.Column("cost_code", sa.String(100), nullable=False, server_default=""),
        sa.Column("risk_category", sa.String(50), nullable=False, server_default=""),
        sa.Column("impact", sa.String(10), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(10), nullable=False, server_default="draft"),
        sa.Column("confirmed_by", sa.String(36), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
    )
    op.create_index("ix_oe_lessons_learned_lesson_project_id", _TABLE, ["project_id"])
    op.create_index("ix_lessons_learned_project_status", _TABLE, ["project_id", "status"])
    op.create_index("ix_lessons_learned_trade", _TABLE, ["trade"])
    op.create_index("ix_lessons_learned_risk_category", _TABLE, ["risk_category"])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _TABLE in set(insp.get_table_names()):
        op.drop_table(_TABLE)
