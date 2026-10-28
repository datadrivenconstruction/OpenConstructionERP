# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""wip_report​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ - month-end WIP snapshots and the project manager's forecast.

Creates ``oe_wip_report_period`` (one closed month per project) and
``oe_wip_report_forecast`` (the estimate at completion overriding the cost report).
New tables only, no data rewrite. Inspector-guarded, so a database whose tables
``create_all`` already built is a no-op.

Revision ID: vw01_wip_report_periods
Revises: v201_drawing_revision_compare
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vw01_wip_report_periods"
down_revision: str | Sequence[str] | None = "v201_drawing_revision_compare"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_P = "oe_wip_report_period"
_F = "oe_wip_report_forecast"
_MONEY = (
    "original_contract_value",
    "approved_changes",
    "contract_value",
    "estimated_cost",
    "cost_to_date",
    "earned_revenue",
    "billed_to_date",
    "over_billing",
    "under_billing",
    "projected_gross_profit",
    "backlog",
)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


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
    have = _tables()
    if _P not in have:
        op.create_table(
            _P,
            *_base(),
            _project_fk(),
            sa.Column("period", sa.String(7), nullable=False),
            sa.Column("as_of", sa.Date(), nullable=False),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            *[sa.Column(name, sa.Numeric(18, 4), nullable=False, server_default="0") for name in _MONEY],
            sa.Column("percent_complete", sa.Numeric(9, 4), nullable=False, server_default="0"),
            sa.Column("previous_gross_profit", sa.Numeric(18, 4), nullable=True),
            sa.Column("fade", sa.Numeric(18, 4), nullable=True),
            sa.Column("loss_job", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("sources", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("flags", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("closed_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("project_id", "period", name="uq_wip_report_project_period"),
        )
        op.create_index("ix_oe_wip_report_period_project_id", _P, ["project_id"])
        op.create_index("ix_wip_report_period_period", _P, ["period"])
    if _F not in have:
        op.create_table(
            _F,
            *_base(),
            _project_fk(),
            sa.Column("estimated_cost", sa.Numeric(18, 4), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("updated_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("project_id", name="uq_wip_report_forecast_project"),
        )


def downgrade() -> None:
    have = _tables()
    if _F in have:
        op.drop_table(_F)
    if _P in have:
        op.drop_index("ix_wip_report_period_period", table_name=_P)
        op.drop_index("ix_oe_wip_report_period_project_id", table_name=_P)
        op.drop_table(_P)
