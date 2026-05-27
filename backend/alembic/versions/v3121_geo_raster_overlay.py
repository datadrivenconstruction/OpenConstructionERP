# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""geo_hub: raster overlays (PDF / DWG / image pinned on the globe).

Adds ``oe_geo_hub_raster_overlay`` — the table backing the new
"PDF / DWG / image overlay on the Geo Hub globe with on-map crop"
feature. Distinct from ``oe_geo_hub_overlay`` (which holds GeoJSON /
KML feature collections); raster overlays carry a rasterised PNG plus
four corner cartographic coordinates so the frontend can mount them as
a Cesium ``SingleTileImageryProvider`` and optionally clip them with a
GeoJSON crop polygon.

Following the post-v4.4.1 server-default discipline (memory note on
issue #154): every NOT NULL column ships ``server_default`` so the
``create_all`` fresh-DB path can't trip ``IntegrityError`` from a
seed insert.

Revision ID: v3121_geo_raster_overlay
Revises: v3120_accommodation_init
Create Date: 2026-05-24

Originally written as v3120 — bumped to v3121 because the parallel
Accommodation agent had already merged ``v3120_accommodation_init``
onto main while this worktree was in flight. Depending on that head
keeps the single-head invariant intact (see CLAUDE.md memory note on
the worktree-isolation stale-base trap).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v3121_geo_raster_overlay"
down_revision: Union[str, Sequence[str], None] = "v3120_accommodation_init"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "oe_geo_hub_raster_overlay"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(TABLE):
        # Idempotent: ``create_all`` already materialised the table on a
        # fresh install. Migration is no-op in that case.
        return

    op.create_table(
        TABLE,
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("project_id", GUID(), nullable=False),
        sa.Column(
            "name",
            sa.String(255),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "source_kind",
            sa.String(16),
            nullable=False,
            server_default="image",
        ),
        sa.Column("source_blob_url", sa.String(500), nullable=True),
        sa.Column(
            "source_page",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("raster_blob_url", sa.String(500), nullable=True),
        sa.Column(
            "raster_width_px",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "raster_height_px",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "corners_geojson",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "rotation_deg",
            sa.Numeric(7, 3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "opacity",
            sa.Numeric(4, 3),
            nullable=False,
            server_default="0.7",
        ),
        sa.Column("crop_polygon_geojson", sa.JSON(), nullable=True),
        sa.Column(
            "z_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "visible",
            sa.Boolean(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("created_by", GUID(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["oe_projects_project.id"],
            ondelete="CASCADE",
            name="fk_oe_geo_hub_raster_overlay_project_id_oe_projects_project",
        ),
    )
    op.create_index(
        "ix_oe_geo_hub_raster_overlay_project_id",
        TABLE,
        ["project_id"],
    )
    op.create_index(
        "ix_oe_geo_hub_raster_overlay_source_kind",
        TABLE,
        ["source_kind"],
    )
    op.create_index(
        "ix_oe_geo_hub_raster_overlay_deleted_at",
        TABLE,
        ["deleted_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE):
        return
    op.drop_index("ix_oe_geo_hub_raster_overlay_deleted_at", table_name=TABLE)
    op.drop_index("ix_oe_geo_hub_raster_overlay_source_kind", table_name=TABLE)
    op.drop_index("ix_oe_geo_hub_raster_overlay_project_id", table_name=TABLE)
    op.drop_table(TABLE)
