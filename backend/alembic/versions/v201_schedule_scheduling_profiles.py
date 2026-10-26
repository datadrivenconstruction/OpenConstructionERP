# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""schedule - scheduling profiles (CPM settings per project).

Additive only: new table ``oe_schedule_scheduling_profile``. Progress sheets and
the source of imported schedules keep their state in existing JSON columns
(``Schedule.metadata`` / ``Activity.metadata``) and the progress records, so they
need no schema change. Inspector-guarded: a database whose tables ``create_all``
already built reaches this revision and does nothing.

Revision ID: v201_schedule_scheduling_profiles
Revises: v200_supplier_pricelists_discounts
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v201_schedule_scheduling_profiles"
down_revision: str | Sequence[str] | None = "v200_supplier_pricelists_discounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_schedule_scheduling_profile"


def upgrade() -> None:
    """Create the profile table when missing."""
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if _TABLE in tables or "oe_projects_project" not in tables:
        return
    op.create_table(
        _TABLE,
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("project_id", GUID(), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("progress_mode", sa.String(20), nullable=False, server_default="retained_logic"),
        sa.Column("lag_calendar", sa.String(20), nullable=False, server_default="elapsed"),
        sa.Column("open_ends", sa.String(20), nullable=False, server_default="project_finish"),
        sa.Column("critical_rule", sa.String(20), nullable=False, server_default="total_float"),
        sa.Column("critical_float_threshold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index(f"ix_{_TABLE}_project_id", _TABLE, ["project_id"])
    op.create_index("ix_sched_profile_project_name", _TABLE, ["project_id", "name"])


def downgrade() -> None:
    """Drop the profile table when present."""
    insp = sa.inspect(op.get_bind())
    if _TABLE in set(insp.get_table_names()):
        op.drop_table(_TABLE)
