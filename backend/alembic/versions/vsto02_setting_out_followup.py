# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""setting-out: project settings, tolerance source on requests, accepted deviations

Additive only (a new table and nullable or defaulted columns), so a deploy that
heals its schema at boot picks them up without ``alembic upgrade``.

Revision ID: vsto02_setting_out_followup
Revises: hvx01_haul_ticket_survey_links
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vsto02_setting_out_followup"
down_revision: str | Sequence[str] | None = "hvx01_haul_ticket_survey_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SET = "oe_setting_out_settings"
_REQ = "oe_setting_out_request"
_REC = "oe_setting_out_record"


def _req_columns() -> list[sa.Column]:
    return [sa.Column("tolerance_reference", sa.String(500), nullable=False, server_default="")]


def _rec_columns() -> list[sa.Column]:
    return [
        sa.Column("deviation_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deviation_accepted_by", sa.String(255), nullable=False, server_default=""),
        sa.Column("deviation_note", sa.Text(), nullable=False, server_default=""),
    ]


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if _SET not in existing:
        op.create_table(
            _SET,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("default_tolerance_key", sa.String(80), nullable=False, server_default=""),
            sa.Column("auto_ncr", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.UniqueConstraint("project_id", name="uq_oe_setting_out_settings_project_id"),
        )
    for table, columns in ((_REQ, _req_columns()), (_REC, _rec_columns())):
        if table not in existing:
            continue
        have = _columns(table)
        for column in columns:
            if column.name not in have:
                op.add_column(table, column)


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table, columns in ((_REC, _rec_columns()), (_REQ, _req_columns())):
        if table not in existing:
            continue
        have = _columns(table)
        for column in columns:
            if column.name in have:
                op.drop_column(table, column.name)
    if _SET in existing:
        op.drop_table(_SET)
