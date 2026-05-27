# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""equipment_fleet — Module 5: Equipment & Fleet Management.

Adds 10 tables for owned/rented fleet management:

    oe_equipment_type
    oe_equipment_equipment
    oe_equipment_telemetry
    oe_equipment_maintenance_schedule
    oe_equipment_work_order
    oe_equipment_inspection
    oe_equipment_rental
    oe_equipment_fuel_log
    oe_equipment_parts_log
    oe_equipment_damage_report

Idempotent — re-applying on a DB where ``Base.metadata.create_all`` has
already created the tables is a no-op.

Revision ID: v3012_equipment
Revises: v2943_compliance_docs
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3012_equipment"
down_revision: Union[str, Sequence[str], None] = "v3011_subcontractors"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, index: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def _guid_type(is_sqlite: bool) -> sa.types.TypeEngine:
    return sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)


def _base_columns(guid_type: sa.types.TypeEngine) -> list[sa.Column]:
    return [
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
    ]


# Tables + indexes spec
_NUMERIC = sa.Numeric(precision=18, scale=4)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid = _guid_type(is_sqlite)

    # ── oe_equipment_type ────────────────────────────────────────────────
    table = "oe_equipment_type"
    if not _has_table(inspector, table):
        op.create_table(
            table,
            *_base_columns(guid),
            sa.Column("code", sa.String(50), nullable=False, unique=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("category", sa.String(50), nullable=False, server_default="other"),
            sa.Column("default_service_interval_hours", _NUMERIC, nullable=True),
            sa.Column("default_service_interval_km", _NUMERIC, nullable=True),
            sa.Column("default_inspection_interval_days", sa.Integer(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
        )

    # ── oe_equipment_equipment ───────────────────────────────────────────
    table = "oe_equipment_equipment"
    if not _has_table(inspector, table):
        op.create_table(
            table,
            *_base_columns(guid),
            sa.Column("code", sa.String(50), nullable=False, unique=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("type_code", sa.String(50), nullable=False, server_default="other"),
            sa.Column("manufacturer", sa.String(255), nullable=True),
            sa.Column("model", sa.String(255), nullable=True),
            sa.Column("serial", sa.String(255), nullable=True),
            sa.Column("year", sa.Integer(), nullable=True),
            sa.Column("ownership", sa.String(20), nullable=False, server_default="owned"),
            sa.Column("status", sa.String(30), nullable=False, server_default="active"),
            sa.Column("location_lat", sa.Float(), nullable=True),
            sa.Column("location_lng", sa.Float(), nullable=True),
            sa.Column("hour_meter", _NUMERIC, nullable=False, server_default="0"),
            sa.Column("odometer_km", _NUMERIC, nullable=False, server_default="0"),
            sa.Column("last_telemetry_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("purchase_date", sa.String(20), nullable=True),
            sa.Column("purchase_value", _NUMERIC, nullable=True),
            sa.Column(
                "depreciation_method",
                sa.String(30),
                nullable=False,
                server_default="linear",
            ),
            sa.Column("useful_life_years", sa.Integer(), nullable=True),
            sa.Column("residual_value", _NUMERIC, nullable=True),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── oe_equipment_telemetry ───────────────────────────────────────────
    table = "oe_equipment_telemetry"
    if not _has_table(inspector, table):
        op.create_table(
            table,
            *_base_columns(guid),
            sa.Column(
                "equipment_id",
                guid,
                sa.ForeignKey("oe_equipment_equipment.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("fuel_level", _NUMERIC, nullable=True),
            sa.Column("hour_meter", _NUMERIC, nullable=True),
            sa.Column("odometer_km", _NUMERIC, nullable=True),
            sa.Column("lat", sa.Float(), nullable=True),
            sa.Column("lng", sa.Float(), nullable=True),
            sa.Column("engine_status", sa.String(30), nullable=True),
            sa.Column("raw_payload", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── oe_equipment_maintenance_schedule ────────────────────────────────
    table = "oe_equipment_maintenance_schedule"
    if not _has_table(inspector, table):
        op.create_table(
            table,
            *_base_columns(guid),
            sa.Column(
                "equipment_id",
                guid,
                sa.ForeignKey("oe_equipment_equipment.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("trigger_type", sa.String(20), nullable=False),
            sa.Column("trigger_threshold", _NUMERIC, nullable=False, server_default="0"),
            sa.Column("description", sa.String(500), nullable=False, server_default=""),
            sa.Column("last_completed_at", sa.String(20), nullable=True),
            sa.Column("last_completed_meter", _NUMERIC, nullable=True),
            sa.Column("next_due_meter", _NUMERIC, nullable=True),
            sa.Column("next_due_date", sa.String(20), nullable=True),
            sa.Column(
                "active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1") if is_sqlite else sa.text("true"),
            ),
        )

    # ── oe_equipment_work_order ──────────────────────────────────────────
    table = "oe_equipment_work_order"
    if not _has_table(inspector, table):
        op.create_table(
            table,
            *_base_columns(guid),
            sa.Column(
                "equipment_id",
                guid,
                sa.ForeignKey("oe_equipment_equipment.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "schedule_id",
                guid,
                sa.ForeignKey("oe_equipment_maintenance_schedule.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("scheduled_for", sa.String(20), nullable=True),
            sa.Column("completed_at", sa.String(20), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="scheduled"),
            sa.Column("technician_id", sa.String(36), nullable=True),
            sa.Column("work_summary", sa.Text(), nullable=True),
            sa.Column("cost", _NUMERIC, nullable=False, server_default="0"),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── oe_equipment_inspection ──────────────────────────────────────────
    table = "oe_equipment_inspection"
    if not _has_table(inspector, table):
        op.create_table(
            table,
            *_base_columns(guid),
            sa.Column(
                "equipment_id",
                guid,
                sa.ForeignKey("oe_equipment_equipment.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("inspection_type", sa.String(40), nullable=False),
            sa.Column("inspected_at", sa.String(20), nullable=False),
            sa.Column("valid_until", sa.String(20), nullable=False),
            sa.Column("inspector_name", sa.String(255), nullable=True),
            sa.Column("result", sa.String(20), nullable=False, server_default="pass"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("certificate_url", sa.String(1000), nullable=True),
            sa.Column("approved_by", sa.String(36), nullable=True),
        )

    # ── oe_equipment_rental ──────────────────────────────────────────────
    table = "oe_equipment_rental"
    if not _has_table(inspector, table):
        op.create_table(
            table,
            *_base_columns(guid),
            sa.Column(
                "equipment_id",
                guid,
                sa.ForeignKey("oe_equipment_equipment.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("start_date", sa.String(20), nullable=False),
            sa.Column("end_date", sa.String(20), nullable=True),
            sa.Column("internal_rate_per_day", _NUMERIC, nullable=False, server_default="0"),
            sa.Column("internal_rate_per_hour", _NUMERIC, nullable=False, server_default="0"),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── oe_equipment_fuel_log ────────────────────────────────────────────
    table = "oe_equipment_fuel_log"
    if not _has_table(inspector, table):
        op.create_table(
            table,
            *_base_columns(guid),
            sa.Column(
                "equipment_id",
                guid,
                sa.ForeignKey("oe_equipment_equipment.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("logged_at", sa.String(20), nullable=False),
            sa.Column("fuel_liters", _NUMERIC, nullable=False, server_default="0"),
            sa.Column("hour_meter_at_fill", _NUMERIC, nullable=True),
            sa.Column("odometer_km_at_fill", _NUMERIC, nullable=True),
            sa.Column("cost", _NUMERIC, nullable=False, server_default="0"),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column("supplier", sa.String(255), nullable=True),
            sa.Column("fuel_type", sa.String(40), nullable=True),
        )

    # ── oe_equipment_parts_log ───────────────────────────────────────────
    table = "oe_equipment_parts_log"
    if not _has_table(inspector, table):
        op.create_table(
            table,
            *_base_columns(guid),
            sa.Column(
                "equipment_id",
                guid,
                sa.ForeignKey("oe_equipment_equipment.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "work_order_id",
                guid,
                sa.ForeignKey("oe_equipment_work_order.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("part_number", sa.String(100), nullable=False),
            sa.Column("description", sa.String(500), nullable=False, server_default=""),
            sa.Column("quantity", _NUMERIC, nullable=False, server_default="1"),
            sa.Column("unit_cost", _NUMERIC, nullable=False, server_default="0"),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column("logged_at", sa.String(20), nullable=True),
        )

    # ── oe_equipment_damage_report ───────────────────────────────────────
    table = "oe_equipment_damage_report"
    if not _has_table(inspector, table):
        op.create_table(
            table,
            *_base_columns(guid),
            sa.Column(
                "equipment_id",
                guid,
                sa.ForeignKey("oe_equipment_equipment.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("reported_at", sa.String(20), nullable=False),
            sa.Column("reported_by", sa.String(36), nullable=True),
            sa.Column("severity", sa.String(20), nullable=False, server_default="minor"),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("photos", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("repair_cost_estimate", _NUMERIC, nullable=True),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column("status", sa.String(20), nullable=False, server_default="reported"),
            sa.Column(
                "work_order_id",
                guid,
                sa.ForeignKey("oe_equipment_work_order.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    # ── Indexes ──────────────────────────────────────────────────────────
    inspector = sa.inspect(bind)
    index_specs: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("ix_oe_equipment_type_code", "oe_equipment_type", ("code",)),
        ("ix_oe_equipment_equipment_code", "oe_equipment_equipment", ("code",)),
        ("ix_oe_equipment_equipment_status", "oe_equipment_equipment", ("status",)),
        ("ix_oe_equipment_equipment_type", "oe_equipment_equipment", ("type_code",)),
        (
            "ix_oe_equipment_telemetry_equipment_id",
            "oe_equipment_telemetry",
            ("equipment_id",),
        ),
        (
            "ix_oe_equipment_telemetry_recorded_at",
            "oe_equipment_telemetry",
            ("recorded_at",),
        ),
        (
            "ix_oe_equipment_telemetry_equipment_recorded",
            "oe_equipment_telemetry",
            ("equipment_id", "recorded_at"),
        ),
        (
            "ix_oe_equipment_maintenance_schedule_equipment_id",
            "oe_equipment_maintenance_schedule",
            ("equipment_id",),
        ),
        (
            "ix_oe_equipment_maintenance_schedule_next_due_date",
            "oe_equipment_maintenance_schedule",
            ("next_due_date",),
        ),
        (
            "ix_oe_equipment_work_order_equipment_id",
            "oe_equipment_work_order",
            ("equipment_id",),
        ),
        (
            "ix_oe_equipment_work_order_status",
            "oe_equipment_work_order",
            ("status",),
        ),
        (
            "ix_oe_equipment_inspection_equipment_id",
            "oe_equipment_inspection",
            ("equipment_id",),
        ),
        (
            "ix_oe_equipment_inspection_valid_until",
            "oe_equipment_inspection",
            ("valid_until",),
        ),
        (
            "ix_oe_equipment_rental_equipment_id",
            "oe_equipment_rental",
            ("equipment_id",),
        ),
        (
            "ix_oe_equipment_rental_project_id",
            "oe_equipment_rental",
            ("project_id",),
        ),
        (
            "ix_oe_equipment_rental_status",
            "oe_equipment_rental",
            ("status",),
        ),
        (
            "ix_oe_equipment_fuel_log_equipment_id",
            "oe_equipment_fuel_log",
            ("equipment_id",),
        ),
        (
            "ix_oe_equipment_parts_log_equipment_id",
            "oe_equipment_parts_log",
            ("equipment_id",),
        ),
        (
            "ix_oe_equipment_damage_report_equipment_id",
            "oe_equipment_damage_report",
            ("equipment_id",),
        ),
    )
    for name, tbl, cols in index_specs:
        if not _has_index(inspector, tbl, name):
            try:
                op.create_index(name, tbl, list(cols), unique=False)
            except sa.exc.OperationalError:
                pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop in reverse dependency order (parts → work_order → schedule → equipment ...)
    for table in (
        "oe_equipment_damage_report",
        "oe_equipment_parts_log",
        "oe_equipment_fuel_log",
        "oe_equipment_rental",
        "oe_equipment_inspection",
        "oe_equipment_work_order",
        "oe_equipment_maintenance_schedule",
        "oe_equipment_telemetry",
        "oe_equipment_equipment",
        "oe_equipment_type",
    ):
        if _has_table(inspector, table):
            op.drop_table(table)
