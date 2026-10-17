# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""costmodel - cost control snapshots and manual forecasts.

Two new tables, nothing changed in an existing one:

* ``oe_costmodel_forecast_snapshot``: the cost control report frozen at a date, optionally tagged with the cost
  stage it records (budget, estimate, detailed estimate, pre-tender, award, forecast, final), with the totals and
  one row per cost line as JSON. Never edited after it is taken.
* ``oe_costmodel_forecast_override``: a person's forecast for one cost line with the reason and the document it
  rests on. Append-only; the row with no ``closed_at`` is the one in force. Rows cascade with their cost line and
  their project.

Purely additive, so an installed base gets the tables from ``create_all`` on boot as well. Every constraint and
index name is written out and matches the models. Every step is inspector-guarded, so a database whose tables
``create_all`` already built reaches this revision and does nothing.

Revision ID: v89_costmodel_cost_control
Revises: v88_finance_payment_runs
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.db_types import MoneyType
from app.database import GUID

revision: str = "v89_costmodel_cost_control"
down_revision: str | Sequence[str] | None = "v88_finance_payment_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SNAP = "oe_costmodel_forecast_snapshot"
_OVR = "oe_costmodel_forecast_override"


def upgrade() -> None:
    """Create the snapshot table, then the override table; each only when missing."""
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if _SNAP not in tables:
        op.create_table(
            _SNAP,
            sa.Column("id", GUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column(
                "project_id",
                GUID(),
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                    name="fk_costmodel_forecast_snapshot_project",
                ),
                nullable=False,
            ),
            sa.Column("taken_on", sa.String(length=10), nullable=False),
            sa.Column("stage", sa.String(length=30), nullable=False, server_default="forecast"),
            sa.Column("label", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("currency", sa.String(length=10), nullable=False, server_default=""),
            sa.Column("totals", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("rows", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("created_by", sa.String(length=36), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_oe_costmodel_forecast_snapshot"),
        )
    existing = {ix["name"] for ix in sa.inspect(bind).get_indexes(_SNAP)}
    if "ix_oe_costmodel_forecast_snapshot_project_id" not in existing:
        op.create_index("ix_oe_costmodel_forecast_snapshot_project_id", _SNAP, ["project_id"])
    if "ix_costmodel_forecast_snapshot_proj_date" not in existing:
        op.create_index("ix_costmodel_forecast_snapshot_proj_date", _SNAP, ["project_id", "taken_on"])

    if _OVR not in tables:
        op.create_table(
            _OVR,
            sa.Column("id", GUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column(
                "project_id",
                GUID(),
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                    name="fk_costmodel_forecast_override_project",
                ),
                nullable=False,
            ),
            sa.Column(
                "cost_line_id",
                GUID(),
                sa.ForeignKey(
                    "oe_costmodel_cost_line.id",
                    ondelete="CASCADE",
                    name="fk_costmodel_forecast_override_cost_line",
                ),
                nullable=False,
            ),
            sa.Column("amount", MoneyType(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column(
                "document_id",
                GUID(),
                sa.ForeignKey(
                    "oe_documents_document.id",
                    ondelete="SET NULL",
                    name="fk_costmodel_forecast_override_document",
                ),
                nullable=True,
            ),
            sa.Column("document_ref", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(length=36), nullable=True),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("closed_by", sa.String(length=36), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_oe_costmodel_forecast_override"),
        )
    existing = {ix["name"] for ix in sa.inspect(bind).get_indexes(_OVR)}
    if "ix_oe_costmodel_forecast_override_project_id" not in existing:
        op.create_index("ix_oe_costmodel_forecast_override_project_id", _OVR, ["project_id"])
    if "ix_oe_costmodel_forecast_override_cost_line_id" not in existing:
        op.create_index("ix_oe_costmodel_forecast_override_cost_line_id", _OVR, ["cost_line_id"])
    if "ix_costmodel_forecast_override_line_open" not in existing:
        op.create_index("ix_costmodel_forecast_override_line_open", _OVR, ["cost_line_id", "closed_at"])
    if "uq_costmodel_forecast_override_open" not in existing:
        # One open manual forecast per line: two concurrent saves cannot both stay open.
        op.create_index(
            "uq_costmodel_forecast_override_open",
            _OVR,
            ["cost_line_id"],
            unique=True,
            postgresql_where=sa.text("closed_at IS NULL"),
            sqlite_where=sa.text("closed_at IS NULL"),
        )


def downgrade() -> None:
    """Drop the override table, then the snapshot table."""
    tables = sa.inspect(op.get_bind()).get_table_names()
    if _OVR in tables:
        op.drop_table(_OVR)
    if _SNAP in tables:
        op.drop_table(_SNAP)
