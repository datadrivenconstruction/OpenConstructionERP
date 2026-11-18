# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""mine units, reporting periods and period lines

Additive new tables only, so a deploy that heals its schema at boot picks them
up without ``alembic upgrade``.

Revision ID: vmin01_mine_survey
Revises: vstk01_stockpiles
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vmin01_mine_survey"
down_revision: str | Sequence[str] | None = "vstk01_stockpiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNIT = "oe_mine_unit"
_PERIOD = "oe_mine_period"
_ENTRY = "oe_mine_period_entry"
_VOL = "oe_survey_volume"


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def _project_fk() -> sa.Column:
    return sa.Column(
        "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if _UNIT not in existing:
        op.create_table(
            _UNIT,
            *_base(),
            _project_fk(),
            sa.Column("code", sa.String(20), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("unit_type", sa.String(20), nullable=False, server_default="bench"),
            sa.Column("density_t_m3", sa.Numeric(8, 4), nullable=True),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_mine_unit_project", _UNIT, ["project_id"])
    if _PERIOD not in existing:
        op.create_table(
            _PERIOD,
            *_base(),
            _project_fk(),
            sa.Column("label", sa.String(20), nullable=False),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("band_lo_pct", sa.Numeric(6, 2), nullable=True),
            sa.Column("band_hi_pct", sa.Numeric(6, 2), nullable=True),
            sa.Column("truck_tolerance_pct", sa.Numeric(6, 2), nullable=True),
            sa.Column("profile_label", sa.String(120), nullable=False, server_default=""),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_mine_period_project", _PERIOD, ["project_id"])
    if _ENTRY not in existing:
        op.create_table(
            _ENTRY,
            *_base(),
            _project_fk(),
            sa.Column("period_id", sa.String(36), sa.ForeignKey(f"{_PERIOD}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("unit_id", sa.String(36), sa.ForeignKey(f"{_UNIT}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("plan_m3", sa.Numeric(16, 3), nullable=False, server_default="0"),
            sa.Column("plan_t", sa.Numeric(16, 2), nullable=True),
            sa.Column("plan_advance_m", sa.Numeric(12, 2), nullable=True),
            sa.Column("actual_advance_m", sa.Numeric(12, 2), nullable=True),
            sa.Column("density_t_m3", sa.Numeric(8, 4), nullable=True),
            sa.Column("actual_volume_id", sa.String(36), sa.ForeignKey(f"{_VOL}.id", ondelete="SET NULL")),
            sa.Column("truck_loads", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("truck_t", sa.Numeric(16, 2), nullable=True),
            sa.Column("truck_source", sa.String(255), nullable=False, server_default=""),
            sa.Column("claim_entry_id", sa.String(36), nullable=True),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("claimed_by_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("claimed_m3", sa.Numeric(16, 3), nullable=True),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("period_id", "unit_id", name="uq_oe_mine_entry_period_unit"),
        )
        op.create_index("ix_oe_mine_entry_period", _ENTRY, ["period_id"])


def downgrade() -> None:
    for table in (_ENTRY, _PERIOD, _UNIT):
        op.drop_table(table)
