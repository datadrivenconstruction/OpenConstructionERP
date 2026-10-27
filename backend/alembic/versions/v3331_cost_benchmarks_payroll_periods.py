# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""cost​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ benchmarks register and payroll export periods

Creates ``oe_cost_benchmarks_record`` and ``oe_cost_benchmarks_element`` (tenant
scoped benchmark records of completed projects and estimates), and
``oe_payroll_period``, ``oe_payroll_period_line`` and ``oe_payroll_period_event``
(payroll export periods with pay type lines and the lock / reopen / export audit).
New tables only, so nothing that runs today changes.

Revision ID: v3331_cost_benchmarks_payroll_periods
Revises: v3326_subcontractor_insurance_compliance
Create Date: 2026-10-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v3331_cost_benchmarks_payroll_periods"
down_revision: str | Sequence[str] | None = "v3326_subcontractor_insurance_compliance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _money(name: str, scale: int = 2, precision: int = 18) -> sa.Column:
    return sa.Column(name, sa.Numeric(precision, scale), nullable=False, server_default="0")


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "oe_cost_benchmarks_record" not in tables:
        op.create_table(
            "oe_cost_benchmarks_record",
            *_base(),
            sa.Column("tenant_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("kind", sa.String(20), nullable=False, server_default="completed"),
            sa.Column("project_id", sa.String(36), nullable=True),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column("project_type", sa.String(50), nullable=False, server_default=""),
            sa.Column("country", sa.String(2), nullable=False, server_default=""),
            sa.Column("region", sa.String(64), nullable=False, server_default=""),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column("cost_date", sa.Date(), nullable=False),
            sa.Column("standard", sa.String(20), nullable=False, server_default="din276"),
            sa.Column("gfa_m2", sa.Numeric(14, 2), nullable=True),
            sa.Column("functional_unit", sa.String(30), nullable=False, server_default=""),
            sa.Column("functional_units", sa.Numeric(14, 2), nullable=True),
            _money("total_cost"),
            sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("source", sa.String(40), nullable=False, server_default="manual"),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )
        op.create_index("ix_oe_cost_benchmarks_record_tenant_id", "oe_cost_benchmarks_record", ["tenant_id"])
        op.create_index("ix_oe_cost_benchmarks_record_project_id", "oe_cost_benchmarks_record", ["project_id"])
        op.create_index("ix_cost_benchmarks_record_tenant_kind", "oe_cost_benchmarks_record", ["tenant_id", "kind"])
        op.create_index(
            "ix_cost_benchmarks_record_type_country", "oe_cost_benchmarks_record", ["project_type", "country"]
        )
    if "oe_cost_benchmarks_element" not in tables:
        op.create_table(
            "oe_cost_benchmarks_element",
            *_base(),
            sa.Column(
                "record_id",
                sa.String(36),
                sa.ForeignKey("oe_cost_benchmarks_record.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("code", sa.String(30), nullable=False),
            sa.Column("label", sa.String(255), nullable=False, server_default=""),
            _money("amount"),
        )
        op.create_index("ix_oe_cost_benchmarks_element_record_id", "oe_cost_benchmarks_element", ["record_id"])
    if "oe_payroll_period" not in tables:
        op.create_table(
            "oe_payroll_period",
            *_base(),
            sa.Column(
                "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("label", sa.String(120), nullable=False, server_default=""),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("country", sa.String(2), nullable=False, server_default=""),
            sa.Column("rule_profile", sa.String(60), nullable=False, server_default="neutral"),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            _money("total_hours", 2, 14),
            _money("total_gross"),
            _money("total_burden"),
            sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("locked_by", sa.String(36), nullable=True),
            sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("posted_ref", sa.String(100), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )
        op.create_index("ix_oe_payroll_period_project_id", "oe_payroll_period", ["project_id"])
        op.create_index("ix_oe_payroll_period_status", "oe_payroll_period", ["status"])
        op.create_index(
            "ix_oe_payroll_period_project_dates", "oe_payroll_period", ["project_id", "period_start", "period_end"]
        )
    if "oe_payroll_period_line" not in tables:
        op.create_table(
            "oe_payroll_period_line",
            *_base(),
            sa.Column(
                "period_id", sa.String(36), sa.ForeignKey("oe_payroll_period.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("employee_id", sa.String(36), nullable=True),
            sa.Column("employee_number", sa.String(60), nullable=False, server_default=""),
            sa.Column("employee_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("work_date", sa.Date(), nullable=False),
            sa.Column("cost_code", sa.String(100), nullable=False, server_default=""),
            sa.Column("pay_type", sa.String(30), nullable=False, server_default="regular"),
            _money("hours", 2, 10),
            _money("rate", 4, 14),
            sa.Column("multiplier", sa.Numeric(8, 4), nullable=False, server_default="1"),
            _money("amount"),
            sa.Column("overtime_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("source_refs", sa.JSON(), nullable=False, server_default="[]"),
        )
        op.create_index("ix_oe_payroll_period_line_period_id", "oe_payroll_period_line", ["period_id"])
        op.create_index("ix_oe_payroll_period_line_period_emp", "oe_payroll_period_line", ["period_id", "employee_id"])
    if "oe_payroll_period_event" not in tables:
        op.create_table(
            "oe_payroll_period_event",
            *_base(),
            sa.Column(
                "period_id", sa.String(36), sa.ForeignKey("oe_payroll_period.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("action", sa.String(30), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("actor_id", sa.String(36), nullable=True),
            sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
        )
        op.create_index("ix_oe_payroll_period_event_period_id", "oe_payroll_period_event", ["period_id"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for name in (
        "oe_payroll_period_event",
        "oe_payroll_period_line",
        "oe_payroll_period",
        "oe_cost_benchmarks_element",
        "oe_cost_benchmarks_record",
    ):
        if name in tables:
            op.drop_table(name)
