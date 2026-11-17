# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""setting-out: tolerance profiles, stakeout requests, design stakes, stakeout records

Additive new tables only, so a deploy that heals its schema at boot picks them
up without ``alembic upgrade``.

Revision ID: vsto01_setting_out
Revises: vsrv01_survey_core
Create Date: 2026-11-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vsto01_setting_out"
down_revision: str | Sequence[str] | None = "vsrv01_survey_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROF = "oe_setting_out_tolerance_profile"
_REQ = "oe_setting_out_request"
_PT = "oe_setting_out_point"
_REC = "oe_setting_out_record"


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
    if _PROF not in existing:
        op.create_table(
            _PROF,
            *_base(),
            _project_fk(),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("items", sa.JSON(), nullable=False),
            sa.Column("reference", sa.String(255), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_setting_out_tolerance_profile_project", _PROF, ["project_id"])
    if _REQ not in existing:
        op.create_table(
            _REQ,
            *_base(),
            _project_fk(),
            sa.Column("code", sa.String(32), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("item_type", sa.String(32), nullable=False, server_default="other"),
            sa.Column("tolerance_key", sa.String(80), nullable=False, server_default=""),
            sa.Column("tolerance_label", sa.String(255), nullable=False, server_default=""),
            sa.Column("tolerance_source", sa.String(20), nullable=False, server_default=""),
            sa.Column("tol_h_mm", sa.Numeric(8, 1), nullable=True),
            sa.Column("tol_v_mm", sa.Numeric(8, 1), nullable=True),
            sa.Column("element_ref_type", sa.String(20), nullable=False, server_default=""),
            sa.Column("element_ref_id", sa.String(255), nullable=False, server_default=""),
            sa.Column("element_ref_label", sa.String(255), nullable=False, server_default=""),
            sa.Column("alignment", sa.JSON(), nullable=True),
            sa.Column("instrument", sa.String(255), nullable=False, server_default=""),
            sa.Column("control_ref", sa.String(255), nullable=False, server_default=""),
            sa.Column("source_filename", sa.String(255), nullable=False, server_default=""),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_setting_out_request_project", _REQ, ["project_id"])
    if _PT not in existing:
        op.create_table(
            _PT,
            *_base(),
            _project_fk(),
            sa.Column("request_id", sa.String(36), sa.ForeignKey(f"{_REQ}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("point_id", sa.String(64), nullable=False),
            sa.Column("design_e", sa.Numeric(14, 4), nullable=False),
            sa.Column("design_n", sa.Numeric(14, 4), nullable=False),
            sa.Column("design_z", sa.Numeric(10, 4), nullable=True),
            sa.Column("chainage", sa.Numeric(14, 4), nullable=True),
            sa.Column("offset_m", sa.Numeric(12, 4), nullable=True),
            sa.Column("code", sa.String(64), nullable=False, server_default=""),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index("ix_oe_setting_out_point_request", _PT, ["request_id"])
    if _REC not in existing:
        op.create_table(
            _REC,
            *_base(),
            _project_fk(),
            sa.Column("request_id", sa.String(36), sa.ForeignKey(f"{_REQ}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("point_id", sa.String(36), sa.ForeignKey(f"{_PT}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("measured_e", sa.Numeric(14, 4), nullable=False),
            sa.Column("measured_n", sa.Numeric(14, 4), nullable=False),
            sa.Column("measured_z", sa.Numeric(10, 4), nullable=True),
            sa.Column("de_mm", sa.Numeric(10, 1), nullable=False),
            sa.Column("dn_mm", sa.Numeric(10, 1), nullable=False),
            sa.Column("d_mm", sa.Numeric(10, 1), nullable=False),
            sa.Column("dz_mm", sa.Numeric(10, 1), nullable=True),
            sa.Column("tol_h_mm", sa.Numeric(8, 1), nullable=True),
            sa.Column("tol_v_mm", sa.Numeric(8, 1), nullable=True),
            sa.Column("verdict", sa.String(20), nullable=False),
            sa.Column("instrument", sa.String(255), nullable=False, server_default=""),
            sa.Column("control_ref", sa.String(255), nullable=False, server_default=""),
            sa.Column("measured_by", sa.String(255), nullable=False, server_default=""),
            sa.Column("measured_by_id", sa.String(36), nullable=True),
            sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("ncr_id", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_setting_out_record_point", _REC, ["point_id"])
        op.create_index("ix_oe_setting_out_record_request", _REC, ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_oe_setting_out_record_request", table_name=_REC)
    op.drop_index("ix_oe_setting_out_record_point", table_name=_REC)
    op.drop_table(_REC)
    op.drop_index("ix_oe_setting_out_point_request", table_name=_PT)
    op.drop_table(_PT)
    op.drop_index("ix_oe_setting_out_request_project", table_name=_REQ)
    op.drop_table(_REQ)
    op.drop_index("ix_oe_setting_out_tolerance_profile_project", table_name=_PROF)
    op.drop_table(_PROF)
