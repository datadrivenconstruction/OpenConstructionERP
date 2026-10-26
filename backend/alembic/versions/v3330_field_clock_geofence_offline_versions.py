# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""field time clock with site geofences, and version columns for offline edits​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

New tables (field_time):

* ``oe_field_time_geofence``: per-project site boundary, circle or polygon.
* ``oe_field_time_clock_settings``: per-project switch, position retention, break.
* ``oe_field_time_clock_consent``: a worker's consent to position capture.
* ``oe_field_time_clock_event``: one clock-in or clock-out with the position at
  that moment only, its inside/outside verdict and the supervisor decision.

New column ``version`` (integer, default 1) on the daily diary header and entry,
the punch item and the quality inspection, for optimistic concurrency of edits
made offline (If-Match, 409 on a stale version).

Every step is inspector-guarded, so a database whose tables ``create_all``
already built reaches this revision and does nothing.

Revision ID: v3330_field_clock_geofence_offline_versions
Revises: v201_takeoff_measurement_drawing_ref
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v3330_field_clock_geofence_offline_versions"
down_revision: str | Sequence[str] | None = "v201_takeoff_measurement_drawing_ref"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VERSIONED = (
    "oe_daily_diary_diary",
    "oe_daily_diary_entry",
    "oe_punchlist_item",
    "oe_inspections_inspection",
)


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _project_fk() -> sa.Column:
    return sa.Column(
        "project_id", GUID(), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )


def upgrade() -> None:
    """Create the clock tables and add the version columns when missing."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "oe_field_time_geofence" not in tables:
        op.create_table(
            "oe_field_time_geofence",
            *_base(),
            _project_fk(),
            sa.Column("name", sa.String(200), nullable=False, server_default=""),
            sa.Column("shape", sa.String(20), nullable=False, server_default="circle"),
            sa.Column("center_lat", sa.Numeric(10, 7), nullable=True),
            sa.Column("center_lng", sa.Numeric(10, 7), nullable=True),
            sa.Column("radius_m", sa.Numeric(10, 2), nullable=True),
            sa.Column("polygon", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("tolerance_m", sa.Numeric(10, 2), nullable=False, server_default="0"),
            sa.Column("supervisor_user_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("default_cost_code", sa.String(100), nullable=False, server_default=""),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by", GUID(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )
        op.create_index("ix_oe_field_time_geofence_project_active", "oe_field_time_geofence", ["project_id", "active"])

    if "oe_field_time_clock_settings" not in tables:
        op.create_table(
            "oe_field_time_clock_settings",
            *_base(),
            sa.Column(
                "project_id", GUID(), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("retention_days", sa.Integer(), nullable=False, server_default="90"),
            sa.Column("default_break_minutes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("consent_text_version", sa.String(20), nullable=False, server_default="1"),
            sa.UniqueConstraint("project_id", name="uq_oe_field_time_clock_settings_project"),
        )

    if "oe_field_time_clock_consent" not in tables:
        op.create_table(
            "oe_field_time_clock_consent",
            *_base(),
            _project_fk(),
            sa.Column(
                "resource_id",
                GUID(),
                sa.ForeignKey("oe_resources_resource.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("granted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("text_version", sa.String(20), nullable=False, server_default="1"),
            sa.Column("recorded_by", GUID(), nullable=True),
            sa.UniqueConstraint("project_id", "resource_id", name="uq_oe_field_time_clock_consent_project_resource"),
        )

    if "oe_field_time_clock_event" not in tables:
        op.create_table(
            "oe_field_time_clock_event",
            *_base(),
            _project_fk(),
            sa.Column(
                "resource_id", GUID(), sa.ForeignKey("oe_resources_resource.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("kind", sa.String(5), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("latitude", sa.Numeric(10, 7), nullable=True),
            sa.Column("longitude", sa.Numeric(10, 7), nullable=True),
            sa.Column("accuracy_m", sa.Numeric(10, 2), nullable=True),
            sa.Column("position_purged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "geofence_id",
                GUID(),
                sa.ForeignKey("oe_field_time_geofence.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("inside", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("distance_m", sa.Numeric(12, 1), nullable=True),
            sa.Column("approval_status", sa.String(20), nullable=False, server_default="not_required"),
            sa.Column("approval_reason", sa.Text(), nullable=True),
            sa.Column("approved_by", GUID(), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("pair_event_id", GUID(), nullable=True),
            sa.Column("timesheet_id", GUID(), nullable=True),
            sa.Column("client_op_id", sa.String(64), nullable=True),
            sa.Column("recorded_by", GUID(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.UniqueConstraint("project_id", "client_op_id", name="uq_oe_field_time_clock_event_client_op"),
        )
        op.create_index(
            "ix_oe_field_time_clock_event_project_time", "oe_field_time_clock_event", ["project_id", "occurred_at"]
        )
        op.create_index(
            "ix_oe_field_time_clock_event_resource_time", "oe_field_time_clock_event", ["resource_id", "occurred_at"]
        )
        op.create_index(
            "ix_oe_field_time_clock_event_approval", "oe_field_time_clock_event", ["project_id", "approval_status"]
        )

    for table in _VERSIONED:
        if table not in tables:
            continue
        present = {c["name"] for c in sa.inspect(bind).get_columns(table)}
        if "version" not in present:
            op.add_column(table, sa.Column("version", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    """Drop the version columns and the clock tables when present."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table in _VERSIONED:
        if table in tables and "version" in {c["name"] for c in sa.inspect(bind).get_columns(table)}:
            op.drop_column(table, "version")
    for table in (
        "oe_field_time_clock_event",
        "oe_field_time_clock_consent",
        "oe_field_time_clock_settings",
        "oe_field_time_geofence",
    ):
        if table in tables:
            op.drop_table(table)
