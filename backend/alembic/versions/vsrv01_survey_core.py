# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""survey register: project CRS, point sets and points

Additive new tables only, so a deploy that heals its schema at boot picks them
up without ``alembic upgrade``.

Revision ID: vsrv01_survey_core
Revises: vsub01_agreement_documents
Create Date: 2026-11-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vsrv01_survey_core"
down_revision: str | Sequence[str] | None = "vsub01_agreement_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CRS = "oe_survey_project_crs"
_SET = "oe_survey_point_set"
_PT = "oe_survey_point"


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
    if _CRS not in existing:
        op.create_table(
            _CRS,
            *_base(),
            _project_fk(),
            sa.Column("horizontal_epsg", sa.Integer(), nullable=True),
            sa.Column("horizontal_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("vertical_mode", sa.String(20), nullable=False, server_default="same_as_source"),
            sa.Column("vertical_epsg", sa.Integer(), nullable=True),
            sa.Column("is_local_grid", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("local_origin_e", sa.Numeric(14, 4), nullable=True),
            sa.Column("local_origin_n", sa.Numeric(14, 4), nullable=True),
            sa.Column("local_rotation_deg", sa.Numeric(12, 8), nullable=True),
            sa.Column("local_scale_factor", sa.Numeric(12, 10), nullable=True),
            sa.Column("source", sa.String(20), nullable=False, server_default="user"),
            sa.Column("detected_confidence", sa.Float(), nullable=True),
            sa.Column("confirmed_by", sa.String(36), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("project_id", name="uq_oe_survey_project_crs_project_id"),
        )
    if _SET not in existing:
        op.create_table(
            _SET,
            *_base(),
            _project_fk(),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("source_filename", sa.String(255), nullable=False, server_default=""),
            sa.Column("file_format", sa.String(20), nullable=False, server_default="csv"),
            sa.Column("column_preset", sa.String(20), nullable=False, server_default=""),
            sa.Column("instrument", sa.String(255), nullable=False, server_default=""),
            sa.Column("surveyed_by", sa.String(255), nullable=False, server_default=""),
            sa.Column("survey_date", sa.Date(), nullable=True),
            sa.Column("source_epsg", sa.Integer(), nullable=True),
            sa.Column("stored_epsg", sa.Integer(), nullable=True),
            sa.Column("transformed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("duplicate_policy", sa.String(20), nullable=False, server_default="keep_first"),
            sa.Column("rows_read", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("point_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_survey_point_set_project", _SET, ["project_id"])
    if _PT not in existing:
        op.create_table(
            _PT,
            *_base(),
            _project_fk(),
            sa.Column("point_set_id", sa.String(36), sa.ForeignKey(f"{_SET}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("point_id", sa.String(64), nullable=False),
            sa.Column("e", sa.Numeric(14, 4), nullable=False),
            sa.Column("n", sa.Numeric(14, 4), nullable=False),
            sa.Column("z", sa.Numeric(10, 4), nullable=True),
            sa.Column("code", sa.String(64), nullable=False, server_default=""),
            sa.Column("kind", sa.String(20), nullable=False, server_default="topo"),
            sa.Column("sigma", sa.Numeric(8, 4), nullable=True),
            sa.Column("description", sa.String(255), nullable=False, server_default=""),
            sa.Column("source_line", sa.Integer(), nullable=True),
        )
        op.create_index("ix_oe_survey_point_project_pid", _PT, ["project_id", "point_id"])
        op.create_index("ix_oe_survey_point_set", _PT, ["point_set_id"])


def downgrade() -> None:
    op.drop_index("ix_oe_survey_point_set", table_name=_PT)
    op.drop_index("ix_oe_survey_point_project_pid", table_name=_PT)
    op.drop_table(_PT)
    op.drop_index("ix_oe_survey_point_set_project", table_name=_SET)
    op.drop_table(_SET)
    op.drop_table(_CRS)
