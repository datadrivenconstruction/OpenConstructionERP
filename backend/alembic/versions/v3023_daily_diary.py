# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""daily_diary — legally significant daily site diary tables.

Adds eight tables for Module 8:

    oe_daily_diary_diary
    oe_daily_diary_weather
    oe_daily_diary_entry
    oe_daily_diary_photo
    oe_daily_diary_video
    oe_daily_diary_drone_survey
    oe_daily_diary_reality_capture
    oe_daily_diary_archive_signature

Idempotent: every CREATE TABLE / CREATE INDEX is guarded against
re-runs by introspecting the live schema, and op.create_index is
additionally wrapped in try/except OperationalError so a partial
migration on shared SQLite databases can be resumed safely.

Revision ID: v3023_daily_diary
Revises: v3017_carbon
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3023_daily_diary"
down_revision: Union[str, Sequence[str], None] = "v3022_hse_advanced"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Per-table list of (index_name, columns, unique?). Kept in module
# scope so both upgrade and downgrade share the same source of truth.
_INDEXES: dict[str, tuple[tuple[str, tuple[str, ...], bool], ...]] = {
    "oe_daily_diary_diary": (
        ("ix_oe_daily_diary_diary_project_id", ("project_id",), False),
        ("ix_oe_daily_diary_diary_diary_date", ("diary_date",), False),
        ("ix_oe_daily_diary_diary_status", ("status",), False),
        (
            "ix_oe_daily_diary_diary_project_status",
            ("project_id", "status"),
            False,
        ),
        (
            "uq_oe_daily_diary_diary_project_date",
            ("project_id", "diary_date"),
            True,
        ),
    ),
    "oe_daily_diary_weather": (
        ("ix_oe_daily_diary_weather_project_id", ("project_id",), False),
        (
            "ix_oe_daily_diary_weather_project_time",
            ("project_id", "captured_at"),
            False,
        ),
    ),
    "oe_daily_diary_entry": (
        ("ix_oe_daily_diary_entry_diary_id", ("diary_id",), False),
        ("ix_oe_daily_diary_entry_entry_type", ("entry_type",), False),
        (
            "ix_oe_daily_diary_entry_diary_type",
            ("diary_id", "entry_type"),
            False,
        ),
        (
            "ix_oe_daily_diary_entry_source",
            ("source_module", "source_ref"),
            False,
        ),
    ),
    "oe_daily_diary_photo": (
        ("ix_oe_daily_diary_photo_project_id", ("project_id",), False),
        ("ix_oe_daily_diary_photo_taken_at", ("taken_at",), False),
        (
            "ix_oe_daily_diary_photo_project_taken_at",
            ("project_id", "taken_at"),
            False,
        ),
    ),
    "oe_daily_diary_video": (
        ("ix_oe_daily_diary_video_project_id", ("project_id",), False),
        (
            "ix_oe_daily_diary_video_project_recorded_at",
            ("project_id", "recorded_at"),
            False,
        ),
    ),
    "oe_daily_diary_drone_survey": (
        ("ix_oe_daily_diary_drone_survey_project_id", ("project_id",), False),
        (
            "ix_oe_daily_diary_drone_survey_project_flown_at",
            ("project_id", "flown_at"),
            False,
        ),
    ),
    "oe_daily_diary_reality_capture": (
        (
            "ix_oe_daily_diary_reality_capture_project_id",
            ("project_id",),
            False,
        ),
        (
            "ix_oe_daily_diary_reality_capture_project_captured_at",
            ("project_id", "captured_at"),
            False,
        ),
    ),
    "oe_daily_diary_archive_signature": (
        (
            "ix_oe_daily_diary_archive_signature_diary_id",
            ("diary_id",),
            False,
        ),
        (
            "uq_oe_daily_diary_archive_signature_diary",
            ("diary_id",),
            True,
        ),
    ),
}


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    index: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def _create_index_safe(
    name: str,
    table: str,
    cols: tuple[str, ...],
    unique: bool,
) -> None:
    """Wrap ``op.create_index`` in try/except for resilience on shared DBs."""
    try:
        op.create_index(name, table, list(cols), unique=unique)
    except sa.exc.OperationalError:
        # Index probably already exists under a slightly different name
        # (e.g. SQLite auto-named unique index); skip silently rather
        # than aborting the entire migration.
        pass


def _create_indexes_for(
    inspector: sa.engine.reflection.Inspector,
    table: str,
) -> None:
    for name, cols, unique in _INDEXES.get(table, ()):
        if _has_index(inspector, table, name):
            continue
        _create_index_safe(name, table, cols, unique)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    common_audit_cols = (
        sa.Column("id", guid_type, primary_key=True),
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
    )

    # ── oe_daily_diary_diary ───────────────────────────────────────────
    if not _has_table(inspector, "oe_daily_diary_diary"):
        op.create_table(
            "oe_daily_diary_diary",
            *common_audit_cols,
            sa.Column(
                "project_id",
                guid_type,
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("diary_date", sa.String(20), nullable=False),
            sa.Column(
                "site_supervisor_id",
                guid_type,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "weather_summary",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "labour_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "equipment_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="open",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "closed_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "closed_by",
                guid_type,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("owner_signature_ref", sa.String(255), nullable=True),
            sa.Column(
                "supervisor_signature_ref",
                sa.String(255),
                nullable=True,
            ),
            sa.Column("pdf_export_ref", guid_type, nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )

    # ── oe_daily_diary_weather ─────────────────────────────────────────
    if not _has_table(inspector, "oe_daily_diary_weather"):
        op.create_table(
            "oe_daily_diary_weather",
            *common_audit_cols,
            sa.Column(
                "project_id",
                guid_type,
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "captured_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "source",
                sa.String(32),
                nullable=False,
                server_default="manual",
            ),
            sa.Column("temperature_c", sa.Numeric(6, 2), nullable=True),
            sa.Column("humidity_pct", sa.Numeric(5, 2), nullable=True),
            sa.Column("wind_speed_kmh", sa.Numeric(6, 2), nullable=True),
            sa.Column("precipitation_mm", sa.Numeric(6, 2), nullable=True),
            sa.Column("conditions_code", sa.String(32), nullable=True),
            sa.Column("conditions_text", sa.String(255), nullable=True),
            sa.Column("sunrise", sa.String(40), nullable=True),
            sa.Column("sunset", sa.String(40), nullable=True),
            sa.Column("location_lat", sa.Float(), nullable=True),
            sa.Column("location_lng", sa.Float(), nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )

    # ── oe_daily_diary_entry ───────────────────────────────────────────
    if not _has_table(inspector, "oe_daily_diary_entry"):
        op.create_table(
            "oe_daily_diary_entry",
            *common_audit_cols,
            sa.Column(
                "diary_id",
                guid_type,
                sa.ForeignKey(
                    "oe_daily_diary_diary.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("entry_type", sa.String(32), nullable=False),
            sa.Column(
                "entry_time",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "title",
                sa.String(500),
                nullable=False,
                server_default="",
            ),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("source_module", sa.String(64), nullable=True),
            sa.Column("source_ref", guid_type, nullable=True),
            sa.Column(
                "author_id",
                guid_type,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "photo_ids",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )

    # ── oe_daily_diary_photo ───────────────────────────────────────────
    if not _has_table(inspector, "oe_daily_diary_photo"):
        op.create_table(
            "oe_daily_diary_photo",
            *common_audit_cols,
            sa.Column(
                "diary_id",
                guid_type,
                sa.ForeignKey(
                    "oe_daily_diary_diary.id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            ),
            sa.Column(
                "project_id",
                guid_type,
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "taken_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "photographer_id",
                guid_type,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("lat", sa.Float(), nullable=True),
            sa.Column("lng", sa.Float(), nullable=True),
            sa.Column("location_label", sa.String(255), nullable=True),
            sa.Column("file_url", sa.String(2000), nullable=False),
            sa.Column("thumbnail_url", sa.String(2000), nullable=True),
            sa.Column(
                "mime_type",
                sa.String(80),
                nullable=False,
                server_default="image/jpeg",
            ),
            sa.Column(
                "file_size_bytes",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "tags",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "is_360",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0") if is_sqlite else sa.text("false"),
            ),
            sa.Column(
                "is_drone",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0") if is_sqlite else sa.text("false"),
            ),
            sa.Column(
                "is_archived",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0") if is_sqlite else sa.text("false"),
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )

    # ── oe_daily_diary_video ───────────────────────────────────────────
    if not _has_table(inspector, "oe_daily_diary_video"):
        op.create_table(
            "oe_daily_diary_video",
            *common_audit_cols,
            sa.Column(
                "diary_id",
                guid_type,
                sa.ForeignKey(
                    "oe_daily_diary_diary.id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            ),
            sa.Column(
                "project_id",
                guid_type,
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "recorded_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column("file_url", sa.String(2000), nullable=False),
            sa.Column("thumbnail_url", sa.String(2000), nullable=True),
            sa.Column(
                "duration_seconds",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "file_size_bytes",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "tags",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )

    # ── oe_daily_diary_drone_survey ────────────────────────────────────
    if not _has_table(inspector, "oe_daily_diary_drone_survey"):
        op.create_table(
            "oe_daily_diary_drone_survey",
            *common_audit_cols,
            sa.Column(
                "project_id",
                guid_type,
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("flown_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("pilot_name", sa.String(255), nullable=True),
            sa.Column("drone_model", sa.String(255), nullable=True),
            sa.Column("area_m2", sa.Numeric(14, 2), nullable=True),
            sa.Column("ortho_file_url", sa.String(2000), nullable=True),
            sa.Column("dsm_file_url", sa.String(2000), nullable=True),
            sa.Column("point_cloud_url", sa.String(2000), nullable=True),
            sa.Column("elevation_min_m", sa.Numeric(10, 2), nullable=True),
            sa.Column("elevation_max_m", sa.Numeric(10, 2), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )

    # ── oe_daily_diary_reality_capture ─────────────────────────────────
    if not _has_table(inspector, "oe_daily_diary_reality_capture"):
        op.create_table(
            "oe_daily_diary_reality_capture",
            *common_audit_cols,
            sa.Column(
                "project_id",
                guid_type,
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "captured_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "capture_type",
                sa.String(32),
                nullable=False,
                server_default="laser_scan",
            ),
            sa.Column("file_url", sa.String(2000), nullable=False),
            sa.Column("point_count_estimate", sa.Integer(), nullable=True),
            sa.Column("bbox_min", sa.JSON(), nullable=True),
            sa.Column("bbox_max", sa.JSON(), nullable=True),
            sa.Column("accuracy_mm", sa.Numeric(8, 2), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("linked_bim_model_ref", guid_type, nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )

    # ── oe_daily_diary_archive_signature ───────────────────────────────
    if not _has_table(inspector, "oe_daily_diary_archive_signature"):
        op.create_table(
            "oe_daily_diary_archive_signature",
            *common_audit_cols,
            sa.Column(
                "diary_id",
                guid_type,
                sa.ForeignKey(
                    "oe_daily_diary_diary.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column("signed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "signed_by",
                guid_type,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "signature_payload",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "revision",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )

    # Refresh inspector so post-CREATE indexes are visible.
    inspector = sa.inspect(bind)
    for table in _INDEXES:
        if _has_table(inspector, table):
            _create_indexes_for(inspector, table)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop indexes first, then tables — reverse of upgrade.
    for table, indexes in _INDEXES.items():
        if not _has_table(inspector, table):
            continue
        for name, _cols, _unique in indexes:
            if _has_index(inspector, table, name):
                try:
                    op.drop_index(name, table_name=table)
                except sa.exc.OperationalError:
                    pass

    for table in (
        "oe_daily_diary_archive_signature",
        "oe_daily_diary_reality_capture",
        "oe_daily_diary_drone_survey",
        "oe_daily_diary_video",
        "oe_daily_diary_photo",
        "oe_daily_diary_entry",
        "oe_daily_diary_weather",
        "oe_daily_diary_diary",
    ):
        if _has_table(inspector, table):
            op.drop_table(table)
