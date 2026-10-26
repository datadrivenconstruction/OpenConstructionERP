# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""cutting - cutting stock optimisation jobs, pieces, stock and plans.

Additive only:

* ``oe_cutting_job``: a cut list problem with kerf, trim, minimum offcut, yield
  threshold, source and links to a BOQ position and a requisition item;
* ``oe_cutting_piece`` and ``oe_cutting_stock``: the demanded pieces and the
  stock on offer (inventory offcuts included);
* ``oe_cutting_plan``: one optimiser run with its figures, layout and validation.

Every step is inspector-guarded, so a database whose tables ``create_all``
already built reaches this revision and does nothing.

Revision ID: v201_cutting_optimisation
Revises: v200_supplier_pricelists_discounts
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v201_cutting_optimisation"
down_revision: str | Sequence[str] | None = "v200_supplier_pricelists_discounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB = "oe_cutting_job"
_PIECE = "oe_cutting_piece"
_STOCK = "oe_cutting_stock"
_PLAN = "oe_cutting_plan"


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _job_fk() -> sa.Column:
    return sa.Column("job_id", GUID(), sa.ForeignKey(f"{_JOB}.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    """Create the four cutting tables when missing."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if _JOB not in tables:
        op.create_table(
            _JOB,
            *_stamps(),
            sa.Column(
                "project_id", GUID(), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("kind", sa.String(16), nullable=False, server_default="linear"),
            sa.Column("material", sa.String(120), nullable=False, server_default=""),
            sa.Column("kerf_mm", sa.Numeric(8, 2), nullable=False, server_default="0"),
            sa.Column("trim_mm", sa.Numeric(8, 2), nullable=False, server_default="0"),
            sa.Column("min_offcut_mm", sa.Numeric(12, 1), nullable=False, server_default="0"),
            sa.Column("yield_threshold_pct", sa.Numeric(5, 2), nullable=False, server_default="85"),
            sa.Column("unit_mass_kg", sa.Numeric(12, 4), nullable=True),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("source_type", sa.String(32), nullable=False, server_default="manual"),
            sa.Column("source_ref", sa.String(255), nullable=True),
            sa.Column("boq_position_id", GUID(), nullable=True),
            sa.Column("procurement_req_item_id", GUID(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        for column in ("project_id", "boq_position_id", "procurement_req_item_id", "status"):
            op.create_index(f"ix_{_JOB}_{column}", _JOB, [column])

    if _PIECE not in tables:
        op.create_table(
            _PIECE,
            *_stamps(),
            _job_fk(),
            sa.Column("ref", sa.String(64), nullable=False),
            sa.Column("label", sa.String(255), nullable=False, server_default=""),
            sa.Column("length_mm", sa.Numeric(12, 1), nullable=False),
            sa.Column("width_mm", sa.Numeric(12, 1), nullable=True),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("rotatable", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("source_ref", sa.String(255), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index(f"ix_{_PIECE}_job_id", _PIECE, ["job_id"])

    if _STOCK not in tables:
        op.create_table(
            _STOCK,
            *_stamps(),
            _job_fk(),
            sa.Column("ref", sa.String(64), nullable=False),
            sa.Column("label", sa.String(255), nullable=False, server_default=""),
            sa.Column("length_mm", sa.Numeric(12, 1), nullable=False),
            sa.Column("width_mm", sa.Numeric(12, 1), nullable=True),
            sa.Column("unit_cost", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("available", sa.Integer(), nullable=True),
            sa.Column("is_offcut", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("inventory_item_id", GUID(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index(f"ix_{_STOCK}_job_id", _STOCK, ["job_id"])
        op.create_index(f"ix_{_STOCK}_inventory_item_id", _STOCK, ["inventory_item_id"])

    if _PLAN not in tables:
        op.create_table(
            _PLAN,
            *_stamps(),
            _job_fk(),
            sa.Column("project_id", GUID(), nullable=False),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("algorithm", sa.String(64), nullable=False, server_default=""),
            sa.Column("stock_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("pieces_placed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("pieces_unplaced", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("stock_total", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("pieces_total", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("offcut_total", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("scrap_total", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("yield_pct", sa.Numeric(6, 2), nullable=False, server_default="0"),
            sa.Column("waste_pct", sa.Numeric(6, 2), nullable=False, server_default="0"),
            sa.Column("cost", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("exact", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("proven_optimal", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("elapsed_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("layout", sa.JSON(), nullable=False),
            sa.Column("stock_usage", sa.JSON(), nullable=False),
            sa.Column("offcuts", sa.JSON(), nullable=False),
            sa.Column("unplaced", sa.JSON(), nullable=False),
            sa.Column("validation", sa.JSON(), nullable=False),
            sa.Column("settings", sa.JSON(), nullable=False),
            sa.Column("inventory_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index(f"ix_{_PLAN}_job_id", _PLAN, ["job_id"])
        op.create_index(f"ix_{_PLAN}_project_id", _PLAN, ["project_id"])


def downgrade() -> None:
    """Drop the cutting tables when present, children first."""
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (_PLAN, _STOCK, _PIECE, _JOB):
        if table in tables:
            op.drop_table(table)
