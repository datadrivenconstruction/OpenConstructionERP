# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Point Cloud / Reality Capture - initial schema.

Creates the two Phase 0 tables of the oe_pointcloud module:

    oe_pointcloud_scan_dataset      - one registered reality-capture scan (laser
                                      scan, photogrammetry, drone or handheld
                                      LiDAR). Stores metadata only: the point
                                      bytes live in MinIO and this row carries
                                      the keys / URIs, the accuracy tier, the
                                      JSON + Numeric bbox (NO PostGIS) and the
                                      retention policy.
    oe_pointcloud_scan_registration - an alignment / deviation result tying a
                                      scan to a design target or a prior scan,
                                      with the mandatory accuracy companions
                                      (RMS, coverage, hole area, out-of-tolerance
                                      count, confidence).

The embedded PostgreSQL runtime materialises these via ``create_all`` at
startup, so this migration is for external-PostgreSQL deployments that manage
schema with Alembic. Every CREATE is guarded with a table-presence check so a
re-run, or a DB the runtime already auto-created, is a no-op. PostgreSQL-only -
no SQLite shims, no PostGIS (the spatial extent is a JSON bbox plus plain
Numeric min/max lat/lon for cheap B-tree range filters).

Revision ID: v3174_pointcloud_init
Revises: v3174_project_gross_floor_area
Create Date: 2026-06-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v3174_pointcloud_init"
down_revision = "v3174_project_gross_floor_area"
branch_labels = None
depends_on = None

_SCAN = "oe_pointcloud_scan_dataset"
_REGISTRATION = "oe_pointcloud_scan_registration"


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def _pk() -> sa.Column:
    # GUID() stores as String(36); mirror the platform UUID column shape used
    # across the existing table-creation migrations.
    return sa.Column("id", sa.String(36), primary_key=True)


def _timestamps() -> list[sa.Column]:
    # Base mixin provides created_at / updated_at with a DB-side now() default.
    return [
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
    ]


def upgrade() -> None:
    if not _has_table(_SCAN):
        op.create_table(
            _SCAN,
            _pk(),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            # Tenant boundary - resolved from the project owner at register time
            # and woven into the MinIO upload key so blobs are tenant-namespaced.
            sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
            sa.Column(
                "source_type",
                sa.String(32),
                nullable=False,
                server_default="laser_scan",
            ),
            sa.Column(
                "original_format",
                sa.String(8),
                nullable=False,
                server_default="las",
            ),
            # USIBD Level of Accuracy tier: survey / standard / coarse.
            sa.Column(
                "accuracy_tier",
                sa.String(16),
                nullable=False,
                server_default="standard",
            ),
            sa.Column(
                "registration_status",
                sa.String(16),
                nullable=False,
                server_default="unregistered",
            ),
            sa.Column("crs_epsg", sa.Integer, nullable=True),
            sa.Column("crs_confidence", sa.Numeric(4, 3), nullable=True),
            sa.Column(
                "point_count",
                sa.Numeric(18, 0),
                nullable=False,
                server_default="0",
            ),
            # Full axis-aligned bbox in the cloud's own units as a JSON blob; the
            # Numeric min/max lat/lon columns below mirror the WGS84 corners for
            # cheap range filters (no PostGIS).
            sa.Column("bbox_json", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("bbox_min_lat", sa.Numeric(10, 7), nullable=True),
            sa.Column("bbox_min_lon", sa.Numeric(10, 7), nullable=True),
            sa.Column("bbox_max_lat", sa.Numeric(10, 7), nullable=True),
            sa.Column("bbox_max_lon", sa.Numeric(10, 7), nullable=True),
            sa.Column(
                "upload_key",
                sa.String(500),
                nullable=False,
                server_default="",
            ),
            sa.Column("copc_uri", sa.String(2000), nullable=True),
            sa.Column("tileset_uri", sa.String(2000), nullable=True),
            sa.Column("dtm_uri", sa.String(2000), nullable=True),
            sa.Column(
                "classification_stats",
                sa.JSON,
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "status",
                sa.String(16),
                nullable=False,
                server_default="uploading",
                index=True,
            ),
            sa.Column("generation_job_id", sa.String(36), nullable=True, index=True),
            sa.Column(
                "retention_policy",
                sa.String(32),
                nullable=False,
                server_default="keep_raw",
            ),
            sa.Column("created_by", sa.String(36), nullable=True, index=True),
            *_timestamps(),
            sa.Index(
                "ix_oe_pointcloud_scan_dataset_project_tenant",
                "project_id",
                "tenant_id",
            ),
            sa.Index(
                "ix_oe_pointcloud_scan_dataset_bbox_sw",
                "bbox_min_lat",
                "bbox_min_lon",
            ),
        )

    if not _has_table(_REGISTRATION):
        op.create_table(
            _REGISTRATION,
            _pk(),
            sa.Column(
                "scan_id",
                sa.String(36),
                sa.ForeignKey("oe_pointcloud_scan_dataset.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "target_ref",
                sa.String(255),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "transform_matrix",
                sa.JSON,
                nullable=False,
                server_default="[]",
            ),
            sa.Column("rms_error", sa.Numeric(12, 4), nullable=True),
            sa.Column("deviation_map_uri", sa.String(2000), nullable=True),
            sa.Column(
                "out_of_tolerance_count",
                sa.Numeric(18, 0),
                nullable=False,
                server_default="0",
            ),
            sa.Column("coverage_pct", sa.Numeric(6, 3), nullable=True),
            sa.Column("hole_area", sa.Numeric(18, 6), nullable=True),
            sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
            *_timestamps(),
            sa.Index("ix_oe_pointcloud_scan_registration_scan", "scan_id"),
        )


def downgrade() -> None:
    if _has_table(_REGISTRATION):
        op.drop_table(_REGISTRATION)
    if _has_table(_SCAN):
        op.drop_table(_SCAN)
