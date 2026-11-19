# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""survey geodesy: linear unit, local grid tie and grid/ground inputs per project

Additive new table only, so a deploy that heals its schema at boot picks it up
without ``alembic upgrade``.

Revision ID: svg01_survey_geodesy
Revises: awl_subcontract_levies
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "svg01_survey_geodesy"
down_revision: str | Sequence[str] | None = "awl_subcontract_levies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_T = "oe_survey_geodesy"


def upgrade() -> None:
    if _T in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _T,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("linear_unit", sa.String(8), nullable=False, server_default=""),
        sa.Column("local_grid_epsg", sa.Integer(), nullable=True),
        sa.Column("local_points", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("helmert_a", sa.Float(), nullable=True),
        sa.Column("helmert_b", sa.Float(), nullable=True),
        sa.Column("helmert_te", sa.Float(), nullable=True),
        sa.Column("helmert_tn", sa.Float(), nullable=True),
        sa.Column("rms_mm", sa.Float(), nullable=True),
        sa.Column("apply_local_grid", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("residual_tol_mm", sa.Numeric(8, 1), nullable=True),
        sa.Column("scale_tol_ppm", sa.Numeric(10, 1), nullable=True),
        sa.Column("csf_height_m", sa.Numeric(10, 3), nullable=True),
        sa.Column("reference_distance_m", sa.Numeric(10, 3), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.UniqueConstraint("project_id", name="uq_oe_survey_geodesy_project_id"),
    )


def downgrade() -> None:
    op.drop_table(_T)
