# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""survey surfaces and volumes, traverses and survey profiles

Additive new tables only, so a deploy that heals its schema at boot picks them
up without ``alembic upgrade``.

Revision ID: vsrv02_surfaces_volumes
Revises: vsrv01_survey_core
Create Date: 2026-11-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vsrv02_surfaces_volumes"
down_revision: str | Sequence[str] | None = "vsrv01_survey_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRAV = "oe_survey_traverse"
_PROF = "oe_survey_profile"
_SURF = "oe_survey_surface"
_VOL = "oe_survey_volume"
_EVT = "oe_survey_volume_event"


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def _project_fk(nullable: bool = False) -> sa.Column:
    return sa.Column(
        "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=nullable
    )


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if _TRAV not in existing:
        op.create_table(
            _TRAV,
            *_base(),
            _project_fk(),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False, server_default="traverse"),
            sa.Column("method", sa.String(20), nullable=False, server_default="bowditch"),
            sa.Column("legs", sa.JSON(), nullable=False),
            sa.Column("length_m", sa.Numeric(14, 3), nullable=False),
            sa.Column("f_e", sa.Numeric(10, 4), nullable=True),
            sa.Column("f_n", sa.Numeric(10, 4), nullable=True),
            sa.Column("misclosure_m", sa.Numeric(10, 4), nullable=True),
            sa.Column("ratio", sa.Integer(), nullable=True),
            sa.Column("profile_ratio", sa.Integer(), nullable=True),
            sa.Column("distance_km", sa.Numeric(10, 4), nullable=True),
            sa.Column("misclosure_mm", sa.Numeric(10, 2), nullable=True),
            sa.Column("k_mm", sa.Numeric(8, 2), nullable=True),
            sa.Column("allowed_mm", sa.Numeric(10, 2), nullable=True),
            sa.Column("verdict", sa.String(20), nullable=False, server_default="no_profile"),
            sa.Column("profile_label", sa.String(255), nullable=False, server_default=""),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_survey_traverse_project", _TRAV, ["project_id"])
    if _PROF not in existing:
        op.create_table(
            _PROF,
            *_base(),
            _project_fk(nullable=True),
            sa.Column("label", sa.String(255), nullable=False, server_default=""),
            sa.Column("source", sa.String(20), nullable=False, server_default="user"),
            sa.Column("traverse_min_ratio", sa.Integer(), nullable=True),
            sa.Column("level_k_mm", sa.Numeric(8, 2), nullable=True),
            sa.Column("coverage_min_pct", sa.Numeric(5, 2), nullable=True),
        )
        op.create_index("ix_oe_survey_profile_project", _PROF, ["project_id"])
    if _SURF not in existing:
        op.create_table(
            _SURF,
            *_base(),
            _project_fk(),
            sa.Column("code", sa.String(20), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("source", sa.String(20), nullable=False, server_default="points"),
            sa.Column(
                "point_set_id",
                sa.String(36),
                sa.ForeignKey("oe_survey_point_set.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("source_filename", sa.String(255), nullable=False, server_default=""),
            sa.Column("epsg", sa.Integer(), nullable=True),
            sa.Column("accuracy_tier", sa.String(20), nullable=True),
            sa.Column("point_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("triangle_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("area_m2", sa.Numeric(16, 3), nullable=False, server_default="0"),
            sa.Column("z_min", sa.Numeric(10, 4), nullable=True),
            sa.Column("z_max", sa.Numeric(10, 4), nullable=True),
            sa.Column("vertices", sa.JSON(), nullable=False),
            sa.Column("faces", sa.JSON(), nullable=False),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_survey_surface_project", _SURF, ["project_id"])
    if _VOL not in existing:
        surface_fk = f"{_SURF}.id"
        op.create_table(
            _VOL,
            *_base(),
            _project_fk(),
            sa.Column("code", sa.String(20), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("base_surface_id", sa.String(36), sa.ForeignKey(surface_fk, ondelete="SET NULL"), nullable=True),
            sa.Column(
                "compare_surface_id", sa.String(36), sa.ForeignKey(surface_fk, ondelete="SET NULL"), nullable=True
            ),
            sa.Column("base_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("compare_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("method", sa.String(20), nullable=False, server_default="grid"),
            sa.Column("cell_size_m", sa.Numeric(10, 3), nullable=True),
            sa.Column("cell_auto", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("boundary", sa.JSON(), nullable=True),
            sa.Column("material", sa.String(120), nullable=False, server_default=""),
            sa.Column("swell_factor", sa.Numeric(6, 3), nullable=False, server_default="1"),
            sa.Column("shrink_factor", sa.Numeric(6, 3), nullable=False, server_default="1"),
            sa.Column("cut_m3", sa.Numeric(16, 3), nullable=False, server_default="0"),
            sa.Column("fill_m3", sa.Numeric(16, 3), nullable=False, server_default="0"),
            sa.Column("net_m3", sa.Numeric(16, 3), nullable=False, server_default="0"),
            sa.Column("calc_area_m2", sa.Numeric(16, 3), nullable=False, server_default="0"),
            sa.Column("covered_area_m2", sa.Numeric(16, 3), nullable=False, server_default="0"),
            sa.Column("coverage_pct", sa.Numeric(6, 2), nullable=False, server_default="0"),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("crs_epsg", sa.Integer(), nullable=True),
            sa.Column("accuracy_tier", sa.String(20), nullable=True),
            sa.Column("heat", sa.JSON(), nullable=True),
            sa.Column("sections", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("confirmed_by", sa.String(36), nullable=True),
            sa.Column("confirmed_by_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("acknowledged", sa.JSON(), nullable=True),
            sa.Column("override_reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("duplicated_from_id", sa.String(36), nullable=True),
            sa.Column("boq_position_id", sa.String(36), nullable=True),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_survey_volume_project", _VOL, ["project_id"])
    if _EVT not in existing:
        op.create_table(
            _EVT,
            *_base(),
            _project_fk(),
            sa.Column("volume_id", sa.String(36), sa.ForeignKey(f"{_VOL}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("action", sa.String(30), nullable=False),
            sa.Column("target_type", sa.String(40), nullable=False, server_default=""),
            sa.Column("target_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("quantity", sa.Numeric(16, 3), nullable=True),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("user_id", sa.String(36), nullable=True),
            sa.Column("user_name", sa.String(255), nullable=False, server_default=""),
        )
        op.create_index("ix_oe_survey_volume_event_volume", _EVT, ["volume_id"])


def downgrade() -> None:
    op.drop_index("ix_oe_survey_volume_event_volume", table_name=_EVT)
    op.drop_table(_EVT)
    op.drop_index("ix_oe_survey_volume_project", table_name=_VOL)
    op.drop_table(_VOL)
    op.drop_index("ix_oe_survey_surface_project", table_name=_SURF)
    op.drop_table(_SURF)
    op.drop_index("ix_oe_survey_profile_project", table_name=_PROF)
    op.drop_table(_PROF)
    op.drop_index("ix_oe_survey_traverse_project", table_name=_TRAV)
    op.drop_table(_TRAV)
