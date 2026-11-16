# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""payroll hours export: hour type on lines, payroll reference, profiles and runs

Additive only (two columns and three new tables), so a deploy that heals its schema at boot
picks it up without ``alembic upgrade``. Every step is guarded so it is safe on a database that
``create_all`` already built.

Revision ID: vpx01_payroll_hours_export
Revises: vrc01_equipment_rate_catalogue
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vpx01_payroll_hours_export"
down_revision: str | Sequence[str] | None = "vrc01_equipment_rate_catalogue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LINE = "oe_field_time_line"
_RES = "oe_resources_resource"
_PROFILE = "oe_field_time_payroll_profile"
_RUN = "oe_field_time_payroll_run"
_RUN_LINE = "oe_field_time_payroll_run_line"


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def _add_column(table: str, column: sa.Column) -> None:
    inspector = sa.inspect(op.get_bind())
    if table in inspector.get_table_names() and column.name not in {c["name"] for c in inspector.get_columns(table)}:
        op.add_column(table, column)


def _index(table: str, name: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    if table in inspector.get_table_names() and name not in {i["name"] for i in inspector.get_indexes(table)}:
        op.create_index(name, table, columns)


def upgrade() -> None:
    _add_column(_LINE, sa.Column("hour_type", sa.String(20), nullable=False, server_default="regular"))
    _add_column(_RES, sa.Column("payroll_ref", sa.String(100), nullable=True))

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _PROFILE not in tables:
        op.create_table(
            _PROFILE,
            *_stamps(),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("legal_entity_id", sa.String(36), nullable=True),
            sa.Column("is_sample", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("config", sa.JSON(), nullable=False),
            sa.UniqueConstraint("name", name="uq_oe_field_time_payroll_profile_name"),
        )
    if _RUN not in tables:
        op.create_table(
            _RUN,
            *_stamps(),
            sa.Column("number", sa.Integer(), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=True),
            sa.Column("profile_name", sa.String(200), nullable=False, server_default=""),
            sa.Column("profile_snapshot", sa.JSON(), nullable=False),
            sa.Column("period_from", sa.Date(), nullable=False),
            sa.Column("period_to", sa.Date(), nullable=False),
            sa.Column("project_ids", sa.JSON(), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("correction_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("worker_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_hours", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("filename", sa.String(200), nullable=False, server_default=""),
            sa.Column("sha256", sa.String(64), nullable=False, server_default=""),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("number", name="uq_oe_field_time_payroll_run_number"),
        )
    _index(_RUN, "ix_oe_field_time_payroll_run_period", ["period_from", "period_to"])
    if _RUN_LINE not in tables:
        op.create_table(
            _RUN_LINE,
            *_stamps(),
            sa.Column("run_id", sa.String(36), sa.ForeignKey(f"{_RUN}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("resource_id", sa.String(36), nullable=False),
            sa.Column("work_date", sa.Date(), nullable=False),
            sa.Column("project_id", sa.String(36), nullable=False),
            sa.Column("cost_code", sa.String(100), nullable=False, server_default=""),
            sa.Column("hour_type", sa.String(20), nullable=False, server_default="regular"),
            sa.Column("hours", sa.Numeric(18, 2), nullable=False),
            sa.Column("is_correction", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    _index(_RUN_LINE, "ix_oe_field_time_payroll_run_line_run", ["run_id"])
    _index(_RUN_LINE, "ix_oe_field_time_payroll_run_line_key", ["resource_id", "work_date"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table in (_RUN_LINE, _RUN, _PROFILE):
        if table in tables:
            op.drop_table(table)
    for table, column in ((_RES, "payroll_ref"), (_LINE, "hour_type")):
        if table in tables and column in {c["name"] for c in inspector.get_columns(table)}:
            op.drop_column(table, column)
