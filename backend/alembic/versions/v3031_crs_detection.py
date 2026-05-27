# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CRS auto-detection columns for BIM models + DWG drawing versions.

Adds three nullable columns to ``oe_bim_model`` and
``oe_dwg_takeoff_drawing_version`` so the CAD/BIM ingest pipeline can
persist the EPSG code, human-readable name, and 0-1 confidence of the
detected coordinate reference system:

* ``crs_epsg``        — integer EPSG (4326, 25832, 32643, ...) or NULL.
* ``crs_name``        — display label ("WGS 84 / UTM zone 43N" / ...).
* ``crs_confidence``  — float 0..1 (Numeric(4,3)).
* ``crs_method``      — provenance string ("ifc_projected_crs",
  "dwg_geodata", "bbox_heuristic", "user_supplied").

Idempotent: each ``add_column`` is guarded so re-running on a DB that
already has the column is a no-op.

Revision ID: v3031_crs_detection
Revises: v3030_module4_extras
Created: 2026-05-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3031_crs_detection"
down_revision: Union[str, Sequence[str], None] = "v3030_module4_extras"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    column: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── BIM model: CRS guess persisted alongside bounding_box ───────────
    bim_additions: list[tuple[str, sa.Column]] = [
        (
            "crs_epsg",
            sa.Column("crs_epsg", sa.Integer(), nullable=True),
        ),
        (
            "crs_name",
            sa.Column(
                "crs_name",
                sa.String(120),
                nullable=False,
                server_default="",
            ),
        ),
        (
            "crs_confidence",
            sa.Column("crs_confidence", sa.Numeric(4, 3), nullable=True),
        ),
        (
            "crs_method",
            sa.Column(
                "crs_method",
                sa.String(40),
                nullable=False,
                server_default="",
            ),
        ),
    ]
    for col_name, col_def in bim_additions:
        if not _has_column(inspector, "oe_bim_model", col_name):
            with op.batch_alter_table("oe_bim_model") as batch:
                batch.add_column(col_def)

    # ── DWG drawing version: same four columns ──────────────────────────
    dwg_additions: list[tuple[str, sa.Column]] = [
        (
            "crs_epsg",
            sa.Column("crs_epsg", sa.Integer(), nullable=True),
        ),
        (
            "crs_name",
            sa.Column(
                "crs_name",
                sa.String(120),
                nullable=False,
                server_default="",
            ),
        ),
        (
            "crs_confidence",
            sa.Column("crs_confidence", sa.Numeric(4, 3), nullable=True),
        ),
        (
            "crs_method",
            sa.Column(
                "crs_method",
                sa.String(40),
                nullable=False,
                server_default="",
            ),
        ),
    ]
    for col_name, col_def in dwg_additions:
        if not _has_column(
            inspector,
            "oe_dwg_takeoff_drawing_version",
            col_name,
        ):
            with op.batch_alter_table(
                "oe_dwg_takeoff_drawing_version",
            ) as batch:
                batch.add_column(col_def)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    drops: list[tuple[str, str]] = [
        ("oe_dwg_takeoff_drawing_version", "crs_method"),
        ("oe_dwg_takeoff_drawing_version", "crs_confidence"),
        ("oe_dwg_takeoff_drawing_version", "crs_name"),
        ("oe_dwg_takeoff_drawing_version", "crs_epsg"),
        ("oe_bim_model", "crs_method"),
        ("oe_bim_model", "crs_confidence"),
        ("oe_bim_model", "crs_name"),
        ("oe_bim_model", "crs_epsg"),
    ]
    for table, col in drops:
        if _has_column(inspector, table, col):
            with op.batch_alter_table(table) as batch:
                batch.drop_column(col)
