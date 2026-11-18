# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""stockpiles, their surveys and inventory adjustment proposals

Additive new tables only, so a deploy that heals its schema at boot picks them
up without ``alembic upgrade``.

Revision ID: vstk01_stockpiles
Revises: vsrv02_surfaces_volumes
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vstk01_stockpiles"
down_revision: str | Sequence[str] | None = "vsrv02_surfaces_volumes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PILE = "oe_stockpile"
_SURVEY = "oe_stockpile_survey"
_ADJ = "oe_stockpile_adjustment"
_SURF = "oe_survey_surface"


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
    if _PILE not in existing:
        op.create_table(
            _PILE,
            *_base(),
            _project_fk(),
            sa.Column("code", sa.String(20), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("material", sa.String(120), nullable=False, server_default=""),
            sa.Column("location_note", sa.String(255), nullable=False, server_default=""),
            sa.Column("base_surface_id", sa.String(36), sa.ForeignKey(f"{_SURF}.id", ondelete="SET NULL")),
            sa.Column("base_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("site_inventory_item_id", sa.String(36), nullable=True),
            sa.Column("book_tonnes", sa.Numeric(16, 3), nullable=True),
            sa.Column("variance_tolerance_pct", sa.Numeric(6, 2), nullable=True),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_stockpile_project", _PILE, ["project_id"])
    if _SURVEY not in existing:
        op.create_table(
            _SURVEY,
            *_base(),
            _project_fk(),
            sa.Column("stockpile_id", sa.String(36), sa.ForeignKey(f"{_PILE}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("surveyed_on", sa.Date(), nullable=False),
            sa.Column("source_kind", sa.String(20), nullable=False, server_default="surface"),
            sa.Column("pile_surface_id", sa.String(36), sa.ForeignKey(f"{_SURF}.id", ondelete="SET NULL")),
            sa.Column("pile_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("volume_m3", sa.Numeric(16, 3), nullable=False, server_default="0"),
            sa.Column("cell_size_m", sa.Numeric(10, 3), nullable=True),
            sa.Column("coverage_pct", sa.Numeric(6, 2), nullable=True),
            sa.Column("crs_epsg", sa.Integer(), nullable=True),
            sa.Column("density_t_m3", sa.Numeric(8, 4), nullable=False),
            sa.Column("density_source", sa.String(20), nullable=False, server_default="assumed"),
            sa.Column("tonnes", sa.Numeric(16, 2), nullable=False, server_default="0"),
            sa.Column("book_tonnes", sa.Numeric(16, 3), nullable=True),
            sa.Column("variance_t", sa.Numeric(16, 2), nullable=True),
            sa.Column("variance_pct", sa.Numeric(8, 2), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_stockpile_survey_stockpile", _SURVEY, ["stockpile_id"])
    if _ADJ not in existing:
        op.create_table(
            _ADJ,
            *_base(),
            _project_fk(),
            sa.Column("stockpile_id", sa.String(36), sa.ForeignKey(f"{_PILE}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("survey_id", sa.String(36), sa.ForeignKey(f"{_SURVEY}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("delta_t", sa.Numeric(16, 2), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="proposed"),
            sa.Column("item_id", sa.String(36), nullable=True),
            sa.Column("movement_id", sa.String(36), nullable=True),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("proposed_by", sa.String(36), nullable=True),
            sa.Column("confirmed_by", sa.String(36), nullable=True),
            sa.Column("confirmed_by_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_oe_stockpile_adjustment_survey", _ADJ, ["survey_id"])


def downgrade() -> None:
    op.drop_index("ix_oe_stockpile_adjustment_survey", table_name=_ADJ)
    op.drop_table(_ADJ)
    op.drop_index("ix_oe_stockpile_survey_stockpile", table_name=_SURVEY)
    op.drop_table(_SURVEY)
    op.drop_index("ix_oe_stockpile_project", table_name=_PILE)
    op.drop_table(_PILE)
