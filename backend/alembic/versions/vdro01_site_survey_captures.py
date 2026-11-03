# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""site survey captures and observed progress

Creates ``oe_geo_survey_capture`` (a dated orthophoto or scan of a site) and
``oe_geo_survey_observation`` (observed percent complete per schedule activity
on that capture).

Revision ID: vdro01_site_survey_captures
Revises: vai01_doc_assistant_agent_catalogue
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vdro01_site_survey_captures"
down_revision: str | Sequence[str] | None = "vai01_doc_assistant_agent_catalogue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CAPTURE = "oe_geo_survey_capture"
_OBSERVATION = "oe_geo_survey_observation"
_OVERLAY = "oe_geo_hub_raster_overlay"
_SCAN = "oe_pointcloud_scan_dataset"
_ACTIVITY = "oe_schedule_activity"


def _fk(tables: set[str], target: str, ondelete: str) -> list[sa.ForeignKey]:
    """A foreign key only when the optional module's table exists in this database."""
    return [sa.ForeignKey(f"{target}.id", ondelete=ondelete)] if target in tables else []


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _CAPTURE not in tables:
        op.create_table(
            _CAPTURE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("platform", sa.String(16), nullable=False, server_default="drone"),
            sa.Column("captured_on", sa.Date(), nullable=False),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column("overlay_id", sa.String(36), *_fk(tables, _OVERLAY, "CASCADE"), nullable=True),
            sa.Column("scan_id", sa.String(36), *_fk(tables, _SCAN, "CASCADE"), nullable=True),
            sa.Column("gsd_cm", sa.Numeric(8, 2), nullable=True),
            sa.Column("crs_epsg", sa.Integer(), nullable=True),
            sa.Column("bbox_min_lat", sa.Numeric(10, 7), nullable=True),
            sa.Column("bbox_min_lon", sa.Numeric(10, 7), nullable=True),
            sa.Column("bbox_max_lat", sa.Numeric(10, 7), nullable=True),
            sa.Column("bbox_max_lon", sa.Numeric(10, 7), nullable=True),
            sa.Column("sensor", sa.String(120), nullable=True),
            sa.Column("width_px", sa.Integer(), nullable=True),
            sa.Column("height_px", sa.Integer(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.CheckConstraint(
                "(kind = 'orthophoto' AND overlay_id IS NOT NULL AND scan_id IS NULL)"
                " OR (kind = 'point_cloud' AND scan_id IS NOT NULL AND overlay_id IS NULL)"
                " OR (kind = 'dsm' AND (overlay_id IS NOT NULL OR scan_id IS NOT NULL))",
                name="ck_oe_geo_survey_capture_source",
            ),
        )
        op.create_index(f"ix_{_CAPTURE}_project_id", _CAPTURE, ["project_id"])
        op.create_index(f"ix_{_CAPTURE}_tenant_id", _CAPTURE, ["tenant_id"])
        op.create_index("ix_oe_geo_survey_capture_project_date", _CAPTURE, ["project_id", "captured_on"])
    if _OBSERVATION not in tables:
        op.create_table(
            _OBSERVATION,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("capture_id", sa.String(36), sa.ForeignKey(f"{_CAPTURE}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("activity_id", sa.String(36), *_fk(tables, _ACTIVITY, "CASCADE"), nullable=False),
            sa.Column("observed_pct", sa.Numeric(5, 2), nullable=False),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("confirmed_by", sa.String(36), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("capture_id", "activity_id", name="uq_oe_geo_survey_observation"),
        )
        op.create_index(f"ix_{_OBSERVATION}_capture_id", _OBSERVATION, ["capture_id"])
        op.create_index(f"ix_{_OBSERVATION}_activity_id", _OBSERVATION, ["activity_id"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (_OBSERVATION, _CAPTURE):
        if table in tables:
            op.drop_table(table)
