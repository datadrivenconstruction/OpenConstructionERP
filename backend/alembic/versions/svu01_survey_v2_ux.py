# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""survey v2: mine materials, drive faces and profiles, blast patterns

Additive only: new tables, and nullable columns added under an inspector guard,
so a deploy that heals its schema at boot and a stamped database both end up
with the same shape.

Revision ID: svu01_survey_v2_ux
Revises: vcrm01_deal_activities
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "svu01_survey_v2_ux"
down_revision: str | Sequence[str] | None = "vcrm01_deal_activities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNIT = "oe_mine_unit"
_PERIOD = "oe_mine_period"
_MATERIAL = "oe_mine_material"
_FACE = "oe_mine_drive_face"
_PROFILE = "oe_mine_drive_profile"
_PATTERN = "oe_mine_blast_pattern"
_HOLE = "oe_mine_blast_hole"

_NEW_COLUMNS: dict[str, list[tuple[str, sa.types.TypeEngine]]] = {
    _UNIT: [
        ("design_ch_from_m", sa.Numeric(12, 3)),
        ("design_ch_to_m", sa.Numeric(12, 3)),
        ("design_area_m2", sa.Numeric(10, 3)),
    ],
    _PERIOD: [("overbreak_tol_pct", sa.Numeric(6, 2))],
}


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


def _unit_fk(nullable: bool = False, ondelete: str = "CASCADE") -> sa.Column:
    return sa.Column("unit_id", sa.String(36), sa.ForeignKey(f"{_UNIT}.id", ondelete=ondelete), nullable=nullable)


def _period_fk() -> sa.Column:
    return sa.Column("period_id", sa.String(36), sa.ForeignKey(f"{_PERIOD}.id", ondelete="CASCADE"), nullable=True)


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    existing = set(insp.get_table_names())
    for table, cols in _NEW_COLUMNS.items():
        if table not in existing:
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        for name, kind in cols:
            if name not in have:
                op.add_column(table, sa.Column(name, kind, nullable=True))

    if _MATERIAL not in existing:
        op.create_table(
            _MATERIAL,
            *_base(),
            _project_fk(),
            _unit_fk(),
            sa.Column("material", sa.String(20), nullable=False, server_default="ore"),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column("density_t_m3", sa.Numeric(8, 4), nullable=True),
            sa.Column("ring", sa.JSON(), nullable=False),
            sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
            sa.Column("source_filename", sa.String(255), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_mine_material_unit", _MATERIAL, ["unit_id"])
    if _FACE not in existing:
        op.create_table(
            _FACE,
            *_base(),
            _project_fk(),
            _unit_fk(),
            _period_fk(),
            sa.Column("chainage_m", sa.Numeric(12, 3), nullable=False),
            sa.Column("picked_on", sa.Date(), nullable=True),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
        )
        op.create_index("ix_oe_mine_drive_face_unit", _FACE, ["unit_id"])
    if _PROFILE not in existing:
        op.create_table(
            _PROFILE,
            *_base(),
            _project_fk(),
            _unit_fk(),
            _period_fk(),
            sa.Column("chainage_m", sa.Numeric(12, 3), nullable=False),
            sa.Column("actual_area_m2", sa.Numeric(10, 3), nullable=False),
            sa.Column("design_area_m2", sa.Numeric(10, 3), nullable=True),
            sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        )
        op.create_index("ix_oe_mine_drive_profile_unit", _PROFILE, ["unit_id"])
    if _PATTERN not in existing:
        op.create_table(
            _PATTERN,
            *_base(),
            _project_fk(),
            _unit_fk(nullable=True, ondelete="SET NULL"),
            sa.Column("code", sa.String(20), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("collar_tol_m", sa.Numeric(8, 3), nullable=True),
            sa.Column("depth_tol_m", sa.Numeric(8, 3), nullable=True),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_mine_blast_pattern_project", _PATTERN, ["project_id"])
    if _HOLE not in existing:
        op.create_table(
            _HOLE,
            *_base(),
            _project_fk(),
            sa.Column("pattern_id", sa.String(36), sa.ForeignKey(f"{_PATTERN}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("hole_id", sa.String(64), nullable=False),
            sa.Column("design_e", sa.Numeric(14, 4), nullable=False),
            sa.Column("design_n", sa.Numeric(14, 4), nullable=False),
            sa.Column("design_z", sa.Numeric(10, 4), nullable=True),
            sa.Column("design_depth_m", sa.Numeric(8, 3), nullable=True),
            sa.Column("drilled_e", sa.Numeric(14, 4), nullable=True),
            sa.Column("drilled_n", sa.Numeric(14, 4), nullable=True),
            sa.Column("drilled_z", sa.Numeric(10, 4), nullable=True),
            sa.Column("drilled_depth_m", sa.Numeric(8, 3), nullable=True),
            sa.Column("drilled_on", sa.Date(), nullable=True),
        )
        op.create_index("ix_oe_mine_blast_hole_pattern", _HOLE, ["pattern_id"])


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (_HOLE, _PATTERN, _PROFILE, _FACE, _MATERIAL):
        if table in existing:
            op.drop_table(table)
    for table, cols in _NEW_COLUMNS.items():
        if table in existing:
            for name, _kind in cols:
                op.drop_column(table, name)
