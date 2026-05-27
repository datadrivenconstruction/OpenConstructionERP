# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""geo_hub — initial schema (Cesium 3D Tiles + cross-module geo).

Adds seven tables for the Geo Hub module:

    oe_geo_hub_anchor
    oe_geo_hub_tileset
    oe_geo_hub_imagery_layer
    oe_geo_hub_terrain_source
    oe_geo_hub_viewpoint
    oe_geo_hub_overlay
    oe_geo_hub_tile_job

Strictly additive + inspector-guarded so a fresh install with
``Base.metadata.create_all`` applied is a no-op.

Down-revision: v3105_propdev_r6_merge (single linear head after the
R6 multi-head merge).

Revision ID: v3106_geo_hub_init
Revises: v3105_propdev_r6_merge
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3106_geo_hub_init"
down_revision: Union[str, Sequence[str], None] = "v3105_propdev_r6_merge"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Inspector helpers ───────────────────────────────────────────────────


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    name: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    ]


# ── upgrade ─────────────────────────────────────────────────────────────


def upgrade() -> None:  # noqa: C901 — flat sequential CREATE TABLEs.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    # ── GeoAnchor ───────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_geo_hub_anchor"):
        op.create_table(
            "oe_geo_hub_anchor",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "lat",
                sa.Numeric(10, 7),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "lon",
                sa.Numeric(10, 7),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "alt",
                sa.Numeric(8, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "epsg_code",
                sa.Integer(),
                nullable=False,
                server_default="4326",
            ),
            sa.Column("region_code", sa.String(8), nullable=True),
            sa.Column("address", sa.String(500), nullable=True),
            sa.Column("accuracy_m", sa.Numeric(6, 2), nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.UniqueConstraint(
                "project_id",
                name="uq_oe_geo_hub_anchor_project",
            ),
        )
        if not _has_index(inspector, "oe_geo_hub_anchor", "ix_oe_geo_hub_anchor_project_id"):
            op.create_index(
                "ix_oe_geo_hub_anchor_project_id",
                "oe_geo_hub_anchor",
                ["project_id"],
            )

    # ── Tileset ─────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_geo_hub_tileset"):
        op.create_table(
            "oe_geo_hub_tileset",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "source_kind",
                sa.String(32),
                nullable=False,
                server_default="bim_model",
            ),
            sa.Column("source_id", guid, nullable=False),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column("bucket", sa.String(100), nullable=False, server_default=""),
            sa.Column("prefix", sa.String(500), nullable=False, server_default=""),
            sa.Column("tileset_json_uri", sa.String(2000), nullable=True),
            sa.Column("bounding_volume", sa.JSON(), nullable=True),
            sa.Column(
                "geometric_error",
                sa.Numeric(10, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "tile_format",
                sa.String(8),
                nullable=False,
                server_default="b3dm",
            ),
            sa.Column(
                "tile_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "total_bytes",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="draft",
            ),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("generation_job_id", guid, nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )
        op.create_index(
            "ix_oe_geo_hub_tileset_project_id",
            "oe_geo_hub_tileset",
            ["project_id"],
        )
        op.create_index(
            "ix_oe_geo_hub_tileset_source_kind",
            "oe_geo_hub_tileset",
            ["source_kind"],
        )
        op.create_index(
            "ix_oe_geo_hub_tileset_source_id",
            "oe_geo_hub_tileset",
            ["source_id"],
        )
        op.create_index(
            "ix_oe_geo_hub_tileset_status",
            "oe_geo_hub_tileset",
            ["status"],
        )
        op.create_index(
            "ix_oe_geo_hub_tileset_generation_job_id",
            "oe_geo_hub_tileset",
            ["generation_job_id"],
        )

    # ── ImageryLayer ────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_geo_hub_imagery_layer"):
        op.create_table(
            "oe_geo_hub_imagery_layer",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("name", sa.String(120), nullable=False, server_default=""),
            sa.Column(
                "provider",
                sa.String(16),
                nullable=False,
                server_default="osm",
            ),
            sa.Column(
                "url_template",
                sa.String(2000),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "attribution",
                sa.String(500),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "requires_api_key",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "default_for_project",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "is_visible",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )
        op.create_index(
            "ix_oe_geo_hub_imagery_layer_project_id",
            "oe_geo_hub_imagery_layer",
            ["project_id"],
        )
        op.create_index(
            "ix_oe_geo_hub_imagery_layer_default_for_project",
            "oe_geo_hub_imagery_layer",
            ["default_for_project"],
        )

    # ── TerrainSource ───────────────────────────────────────────────────
    if not _has_table(inspector, "oe_geo_hub_terrain_source"):
        op.create_table(
            "oe_geo_hub_terrain_source",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column(
                "provider",
                sa.String(32),
                nullable=False,
                server_default="ellipsoid",
            ),
            sa.Column("endpoint", sa.String(2000), nullable=True),
            sa.Column("ion_token", sa.String(500), nullable=True),
            sa.Column(
                "is_default",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.UniqueConstraint("name", name="uq_oe_geo_hub_terrain_source_name"),
        )
        op.create_index(
            "ix_oe_geo_hub_terrain_source_is_default",
            "oe_geo_hub_terrain_source",
            ["is_default"],
        )

    # ── Viewpoint ───────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_geo_hub_viewpoint"):
        op.create_table(
            "oe_geo_hub_viewpoint",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("name", sa.String(120), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "camera_lat",
                sa.Numeric(10, 7),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "camera_lon",
                sa.Numeric(10, 7),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "camera_alt",
                sa.Numeric(8, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "heading",
                sa.Numeric(7, 3),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "pitch",
                sa.Numeric(7, 3),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "roll",
                sa.Numeric(7, 3),
                nullable=False,
                server_default="0",
            ),
            sa.Column("created_by", guid, nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )
        op.create_index(
            "ix_oe_geo_hub_viewpoint_project_id",
            "oe_geo_hub_viewpoint",
            ["project_id"],
        )

    # ── GeoOverlay ──────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_geo_hub_overlay"):
        op.create_table(
            "oe_geo_hub_overlay",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column(
                "kind",
                sa.String(32),
                nullable=False,
                server_default="boundary",
            ),
            sa.Column(
                "geojson",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("source_file", sa.String(500), nullable=True),
            sa.Column(
                "style",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "is_visible",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column("source_event_id", sa.String(64), nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )
        op.create_index(
            "ix_oe_geo_hub_overlay_project_id",
            "oe_geo_hub_overlay",
            ["project_id"],
        )
        op.create_index(
            "ix_oe_geo_hub_overlay_kind",
            "oe_geo_hub_overlay",
            ["kind"],
        )
        op.create_index(
            "ix_oe_geo_hub_overlay_source_event_id",
            "oe_geo_hub_overlay",
            ["source_event_id"],
        )

    # ── TileGenerationJob ───────────────────────────────────────────────
    if not _has_table(inspector, "oe_geo_hub_tile_job"):
        op.create_table(
            "oe_geo_hub_tile_job",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "tileset_id",
                guid,
                sa.ForeignKey(
                    "oe_geo_hub_tileset.id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            ),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "source_kind",
                sa.String(32),
                nullable=False,
                server_default="bim_model",
            ),
            sa.Column("source_id", guid, nullable=False),
            sa.Column("requested_by", guid, nullable=True),
            sa.Column(
                "state",
                sa.String(20),
                nullable=False,
                server_default="queued",
            ),
            sa.Column(
                "progress_pct",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("output_uri", sa.String(2000), nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )
        op.create_index(
            "ix_oe_geo_hub_tile_job_project_id",
            "oe_geo_hub_tile_job",
            ["project_id"],
        )
        op.create_index(
            "ix_oe_geo_hub_tile_job_tileset_id",
            "oe_geo_hub_tile_job",
            ["tileset_id"],
        )
        op.create_index(
            "ix_oe_geo_hub_tile_job_state",
            "oe_geo_hub_tile_job",
            ["state"],
        )
        op.create_index(
            "ix_oe_geo_hub_tile_job_source_id",
            "oe_geo_hub_tile_job",
            ["source_id"],
        )


# ── downgrade ───────────────────────────────────────────────────────────


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in (
        "oe_geo_hub_tile_job",
        "oe_geo_hub_overlay",
        "oe_geo_hub_viewpoint",
        "oe_geo_hub_terrain_source",
        "oe_geo_hub_imagery_layer",
        "oe_geo_hub_tileset",
        "oe_geo_hub_anchor",
    ):
        if _has_table(inspector, table):
            op.drop_table(table)
