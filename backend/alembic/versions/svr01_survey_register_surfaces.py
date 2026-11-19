# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""survey v2: control check shots, surface breaklines, control tolerance

Additive only: one new table, and nullable columns added under an inspector
guard, so a deploy that heals its schema at boot and a stamped database both
end up with the same shape.

Revision ID: svr01_survey_register_surfaces
Revises: svg01_survey_geodesy
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "svr01_survey_register_surfaces"
down_revision: str | Sequence[str] | None = "svg01_survey_geodesy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "oe_survey_control_check"
_NEW_COLUMNS: dict[str, list[tuple[str, sa.types.TypeEngine]]] = {
    "oe_survey_surface": [("breaklines", sa.JSON())],
    "oe_survey_profile": [("control_tol_mm", sa.Numeric(8, 2))],
}


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

    if _CHECK not in existing:
        op.create_table(
            _CHECK,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "control_point_id",
                sa.String(36),
                sa.ForeignKey("oe_survey_point.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "measured_point_id",
                sa.String(36),
                sa.ForeignKey("oe_survey_point.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("e", sa.Numeric(14, 4), nullable=False),
            sa.Column("n", sa.Numeric(14, 4), nullable=False),
            sa.Column("z", sa.Numeric(10, 4), nullable=True),
            sa.Column("note", sa.String(255), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_survey_control_check_point", _CHECK, ["control_point_id"])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    existing = set(insp.get_table_names())
    if _CHECK in existing:
        op.drop_table(_CHECK)
    for table, cols in _NEW_COLUMNS.items():
        if table not in existing:
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        for name, _kind in cols:
            if name in have:
                op.drop_column(table, name)
