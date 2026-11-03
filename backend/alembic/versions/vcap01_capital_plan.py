# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""capital plan: envelopes, scenarios and phased items

Creates ``oe_capital_plan`` (a multi-year plan scoped to a portfolio node),
``oe_capital_plan_envelope`` (money per year and funding source),
``oe_capital_plan_scenario`` (baseline and what-if variants) and
``oe_capital_plan_item`` (projects competing for the envelope, with phasing).

Revision ID: vcap01_capital_plan
Revises: vai01_doc_assistant_agent_catalogue
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vcap01_capital_plan"
down_revision: str | Sequence[str] | None = "vdro01_site_survey_captures"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLAN = "oe_capital_plan"
_ENVELOPE = "oe_capital_plan_envelope"
_SCENARIO = "oe_capital_plan_scenario"
_ITEM = "oe_capital_plan_item"


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _PLAN not in tables:
        op.create_table(
            _PLAN,
            *_base(),
            sa.Column("node_id", sa.String(36), sa.ForeignKey("oe_portfolio_node.id", ondelete="SET NULL")),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column("start_year", sa.Integer(), nullable=False),
            sa.Column("horizon_years", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )
        op.create_index(f"ix_{_PLAN}_node_id", _PLAN, ["node_id"])
    if _ENVELOPE not in tables:
        op.create_table(
            _ENVELOPE,
            *_base(),
            sa.Column("plan_id", sa.String(36), sa.ForeignKey(f"{_PLAN}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("label", sa.String(100), nullable=False, server_default=""),
            sa.UniqueConstraint("plan_id", "year", "label", name="uq_capital_plan_envelope_year_label"),
        )
        op.create_index(f"ix_{_ENVELOPE}_plan_id", _ENVELOPE, ["plan_id"])
    if _SCENARIO not in tables:
        op.create_table(
            _SCENARIO,
            *_base(),
            sa.Column("plan_id", sa.String(36), sa.ForeignKey(f"{_PLAN}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("is_baseline", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        )
        op.create_index(f"ix_{_SCENARIO}_plan_id", _SCENARIO, ["plan_id"])
    if _ITEM not in tables:
        op.create_table(
            _ITEM,
            *_base(),
            sa.Column(
                "scenario_id", sa.String(36), sa.ForeignKey(f"{_SCENARIO}.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("project_id", sa.String(36), nullable=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("start_year", sa.Integer(), nullable=False),
            sa.Column("duration_years", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("total_cost", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("phasing_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("status", sa.String(20), nullable=False, server_default="proposed"),
            sa.Column("score", sa.Integer(), nullable=True),
        )
        op.create_index(f"ix_{_ITEM}_scenario_id", _ITEM, ["scenario_id"])
        op.create_index(f"ix_{_ITEM}_project_id", _ITEM, ["project_id"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (_ITEM, _SCENARIO, _ENVELOPE, _PLAN):
        if table in tables:
            op.drop_table(table)
