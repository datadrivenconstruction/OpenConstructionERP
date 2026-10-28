# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""equipment telematics​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ and site sensors

Equipment: idle hours, fuel used, fault codes and source on telemetry; cost
code and emission class on the machine; per-device ingest tokens; one
utilisation row per machine and day with its hire allocation.

Site sensors: devices, concrete mix curves, a compact raw reading table keyed
by (device, time), an hourly rollup, alerts and formwork strikes.

Revision ID: v3327_equipment_telematics_site_sensors
Revises: v3327_tender_clarifications
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v3327_equipment_telematics_site_sensors"
down_revision: str | Sequence[str] | None = "v3327_tender_clarifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    with op.batch_alter_table("oe_equipment_telemetry") as b:
        b.add_column(sa.Column("idle_hours", sa.Numeric(18, 4), nullable=True))
        b.add_column(sa.Column("fuel_used_l", sa.Numeric(18, 4), nullable=True))
        b.add_column(sa.Column("fault_codes", sa.JSON(), nullable=False, server_default="[]"))
        b.add_column(sa.Column("source", sa.String(20), nullable=False, server_default="manual"))
    with op.batch_alter_table("oe_equipment_equipment") as b:
        b.add_column(sa.Column("cost_code", sa.String(100), nullable=False, server_default=""))
        b.add_column(sa.Column("emission_class", sa.String(30), nullable=True))

    op.create_table(
        "oe_equipment_telematics_device",
        *_base(),
        sa.Column(
            "equipment_id",
            sa.String(36),
            sa.ForeignKey("oe_equipment_equipment.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(200), nullable=False, server_default=""),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token_prefix", sa.String(12), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_oe_equipment_telematics_device_equipment_id", "oe_equipment_telematics_device", ["equipment_id"]
    )
    op.create_index(
        "ix_oe_equipment_telematics_device_token_hash", "oe_equipment_telematics_device", ["token_hash"], unique=True
    )

    op.create_table(
        "oe_equipment_utilisation_day",
        *_base(),
        sa.Column(
            "equipment_id",
            sa.String(36),
            sa.ForeignKey("oe_equipment_equipment.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("worked_hours", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("idle_hours", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("off_hours", sa.Numeric(10, 4), nullable=False, server_default="24"),
        sa.Column("fuel_l", sa.Numeric(18, 4), nullable=True),
        sa.Column("co2_kg", sa.Numeric(18, 4), nullable=True),
        sa.Column("engine_hours_end", sa.Numeric(18, 4), nullable=True),
        sa.Column("outside_geofence_m", sa.Numeric(12, 1), nullable=True),
        sa.Column("cost_code", sa.String(100), nullable=False, server_default=""),
        sa.Column("hire_cost", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default=""),
        sa.Column("allocated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("equipment_id", "day", name="uq_oe_equipment_utilisation_day"),
    )
    op.create_index("ix_oe_equipment_utilisation_day_equipment_id", "oe_equipment_utilisation_day", ["equipment_id"])
    op.create_index(
        "ix_oe_equipment_utilisation_day_project_day", "oe_equipment_utilisation_day", ["project_id", "day"]
    )

    op.create_table(
        "oe_site_sensors_mix",
        *_base(),
        sa.Column(
            "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("datum_temp_c", sa.Numeric(6, 2), nullable=False, server_default="-10"),
        sa.Column("curve_a", sa.Numeric(10, 4), nullable=False),
        sa.Column("curve_b", sa.Numeric(10, 4), nullable=False),
        sa.Column("strip_strength_mpa", sa.Numeric(8, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_oe_site_sensors_mix_project_id", "oe_site_sensors_mix", ["project_id"])

    op.create_table(
        "oe_site_sensors_device",
        *_base(),
        sa.Column(
            "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False, server_default=""),
        sa.Column("limit_value", sa.Numeric(14, 4), nullable=True),
        sa.Column("country_code", sa.String(2), nullable=False, server_default=""),
        sa.Column("offline_after_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("token_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("token_prefix", sa.String(12), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_value", sa.Float(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("mix_id", sa.String(36), sa.ForeignKey("oe_site_sensors_mix.id", ondelete="SET NULL"), nullable=True),
        sa.Column("pour_ref", sa.String(200), nullable=False, server_default=""),
        sa.Column("cast_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("schedule_activity_id", sa.String(36), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("project_id", "code", name="uq_oe_site_sensors_device_code"),
    )
    op.create_index("ix_oe_site_sensors_device_project_id", "oe_site_sensors_device", ["project_id"])

    op.create_table(
        "oe_site_sensors_reading",
        sa.Column(
            "device_id",
            sa.String(36),
            sa.ForeignKey("oe_site_sensors_device.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("value", sa.Float(), nullable=False),
    )
    op.create_table(
        "oe_site_sensors_reading_hourly",
        sa.Column(
            "device_id",
            sa.String(36),
            sa.ForeignKey("oe_site_sensors_device.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("hour", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("v_min", sa.Float(), nullable=False),
        sa.Column("v_max", sa.Float(), nullable=False),
        sa.Column("v_avg", sa.Float(), nullable=False),
    )

    op.create_table(
        "oe_site_sensors_alert",
        *_base(),
        sa.Column(
            "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "device_id", sa.String(36), sa.ForeignKey("oe_site_sensors_device.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("limit_value", sa.Float(), nullable=True),
        sa.Column("limit_source", sa.String(300), nullable=False, server_default=""),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(36), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("diary_id", sa.String(36), nullable=True),
        sa.Column("inspection_id", sa.String(36), nullable=True),
        sa.Column("punch_item_id", sa.String(36), nullable=True),
    )
    op.create_index("ix_oe_site_sensors_alert_project_status", "oe_site_sensors_alert", ["project_id", "status"])
    op.create_index("ix_oe_site_sensors_alert_device_kind", "oe_site_sensors_alert", ["device_id", "kind"])

    op.create_table(
        "oe_site_sensors_strip",
        *_base(),
        sa.Column(
            "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "device_id", sa.String(36), sa.ForeignKey("oe_site_sensors_device.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("element", sa.String(200), nullable=False, server_default=""),
        sa.Column("schedule_activity_id", sa.String(36), nullable=True),
        sa.Column("target_strength_mpa", sa.Numeric(8, 2), nullable=False),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("struck_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("strength_at_strike_mpa", sa.Numeric(8, 2), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="planned"),
    )
    op.create_index("ix_oe_site_sensors_strip_project_id", "oe_site_sensors_strip", ["project_id"])
    op.create_index("ix_oe_site_sensors_strip_device_id", "oe_site_sensors_strip", ["device_id"])


def downgrade() -> None:
    for table in (
        "oe_site_sensors_strip",
        "oe_site_sensors_alert",
        "oe_site_sensors_reading_hourly",
        "oe_site_sensors_reading",
        "oe_site_sensors_device",
        "oe_site_sensors_mix",
        "oe_equipment_utilisation_day",
        "oe_equipment_telematics_device",
    ):
        op.drop_table(table)
    with op.batch_alter_table("oe_equipment_equipment") as b:
        b.drop_column("emission_class")
        b.drop_column("cost_code")
    with op.batch_alter_table("oe_equipment_telemetry") as b:
        b.drop_column("source")
        b.drop_column("fault_codes")
        b.drop_column("fuel_used_l")
        b.drop_column("idle_hours")
