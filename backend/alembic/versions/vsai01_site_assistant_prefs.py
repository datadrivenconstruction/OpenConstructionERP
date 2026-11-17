# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""site assistant preferences

Per user and project settings for the morning site briefing (time of day, enabled sections).
Schema only and idempotent: create_all on an existing install makes the same table.

Revision ID: vsai01_site_assistant_prefs
Revises: vpin01_plan_pin_targets
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vsai01_site_assistant_prefs"
down_revision: str | Sequence[str] | None = "vpin01_plan_pin_targets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_T = "oe_ai_agents_site_pref"


def upgrade() -> None:
    if _T in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        _T,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("briefing_time", sa.String(5), nullable=False, server_default="06:30"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("enabled_sections", sa.JSON, nullable=False, server_default="[]"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_ai_agents_site_pref"),
    )
    op.create_index("ix_oe_ai_agents_site_pref_project_id", _T, ["project_id"])
    op.create_index("ix_oe_ai_agents_site_pref_user_id", _T, ["user_id"])


def downgrade() -> None:
    if _T in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(_T)
