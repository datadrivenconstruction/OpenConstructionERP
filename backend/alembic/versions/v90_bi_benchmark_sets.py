# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""bi_dashboards - saved benchmark sets.

One new table, nothing changed in an existing one:

* ``oe_bi_dashboards_benchmark_set``: a named cross-project benchmark. Which projects (explicit ids, clients,
  regions, project types, row filters such as a classification code, a period), which KPIs, the statistic it
  leads with, the minimum projects and records before a group counts as a benchmark, and whether compatible
  units are converted. Definitions only; every figure is computed when the set is read.

Purely additive, so an installed base gets the table from ``create_all`` on boot as well. The primary key and
index names are written out and match the models. Every step is inspector-guarded, so a database whose table
``create_all`` already built reaches this revision and does nothing.

Revision ID: v90_bi_benchmark_sets
Revises: v89_costmodel_cost_control
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v90_bi_benchmark_sets"
down_revision: str | Sequence[str] | None = "v89_costmodel_cost_control"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SET = "oe_bi_dashboards_benchmark_set"


def upgrade() -> None:
    """Create the benchmark set table and its owner index, each only when missing."""
    bind = op.get_bind()
    if _SET not in sa.inspect(bind).get_table_names():
        op.create_table(
            _SET,
            sa.Column("id", GUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("owner_user_id", GUID(), nullable=True),
            sa.Column("scope", sa.String(length=16), nullable=False, server_default="personal"),
            sa.Column("kpis_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("cohort_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("statistic", sa.String(length=16), nullable=False, server_default="weighted"),
            sa.Column("min_projects", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("min_records", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("convert_units", sa.Boolean(), nullable=False, server_default="1"),
            sa.PrimaryKeyConstraint("id", name="pk_oe_bi_dashboards_benchmark_set"),
        )
    existing = {ix["name"] for ix in sa.inspect(bind).get_indexes(_SET)}
    if "ix_oe_bi_dashboards_benchmark_set_owner_user_id" not in existing:
        op.create_index("ix_oe_bi_dashboards_benchmark_set_owner_user_id", _SET, ["owner_user_id"])


def downgrade() -> None:
    """Drop the benchmark set table."""
    if _SET in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(_SET)
