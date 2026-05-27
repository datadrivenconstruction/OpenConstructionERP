"""‌⁠‍Equipment & Fleet ORM models.

Tables:
    oe_equipment_type                   — Catalog of equipment types
    oe_equipment_equipment              — Equipment units
    oe_equipment_telemetry              — Time-series telemetry readings
    oe_equipment_maintenance_schedule   — Maintenance intervals & triggers
    oe_equipment_work_order             — Maintenance work orders
    oe_equipment_inspection             — Periodic inspections & certificates
    oe_equipment_rental                 — Internal project rentals
    oe_equipment_fuel_log               — Fuel fills with cost
    oe_equipment_parts_log              — Replaced parts records
    oe_equipment_damage_report          — Damage reports with auto WO
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class EquipmentType(Base):
    """‌⁠‍Catalog of equipment types with default maintenance intervals."""

    __tablename__ = "oe_equipment_type"

    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="other")
    default_service_interval_hours: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )
    default_service_interval_km: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )
    default_inspection_interval_days: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<EquipmentType {self.code} ({self.name})>"


class Equipment(Base):
    """‌⁠‍A single piece of equipment in the fleet."""

    __tablename__ = "oe_equipment_equipment"
    __table_args__ = (
        Index("ix_oe_equipment_equipment_status", "status"),
        Index("ix_oe_equipment_equipment_type", "type_code"),
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type_code: Mapped[str] = mapped_column(String(50), nullable=False, default="other")
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    serial: Mapped[str | None] = mapped_column(String(255), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ownership: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="owned",
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="active",
    )

    # Location & meters
    location_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    hour_meter: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    odometer_km: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    last_telemetry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Accounting
    purchase_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    purchase_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    depreciation_method: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="linear",
    )
    useful_life_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    residual_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="",
        server_default="",
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<Equipment {self.code} ({self.name}/{self.status})>"


class TelemetryReading(Base):
    """A single telemetry reading from an equipment unit."""

    __tablename__ = "oe_equipment_telemetry"
    __table_args__ = (
        Index(
            "ix_oe_equipment_telemetry_equipment_recorded",
            "equipment_id",
            "recorded_at",
        ),
    )

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_equipment_equipment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    fuel_level: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    hour_meter: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    odometer_km: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    engine_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<TelemetryReading equipment={self.equipment_id} at={self.recorded_at}>"


class MaintenanceSchedule(Base):
    """A recurring maintenance schedule for an equipment unit."""

    __tablename__ = "oe_equipment_maintenance_schedule"
    __table_args__ = (Index("ix_oe_equipment_maintenance_schedule_next_due_date", "next_due_date"),)

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_equipment_equipment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # For hours / km this stores the numeric interval; ignored for date triggers.
    trigger_threshold: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    last_completed_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_completed_meter: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )
    next_due_meter: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    next_due_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<MaintenanceSchedule equipment={self.equipment_id} {self.trigger_type}>"


class MaintenanceWorkOrder(Base):
    """A maintenance work order generated or created for an equipment unit."""

    __tablename__ = "oe_equipment_work_order"
    __table_args__ = (Index("ix_oe_equipment_work_order_status", "status"),)

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_equipment_equipment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_equipment_maintenance_schedule.id", ondelete="SET NULL"),
        nullable=True,
    )
    scheduled_for: Mapped[str | None] = mapped_column(String(20), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="scheduled",
    )
    technician_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    work_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="",
        server_default="",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<MaintenanceWorkOrder equipment={self.equipment_id} {self.status}>"


class Inspection(Base):
    """A periodic equipment inspection with validity window."""

    __tablename__ = "oe_equipment_inspection"
    __table_args__ = (Index("ix_oe_equipment_inspection_valid_until", "valid_until"),)

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_equipment_equipment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    inspection_type: Mapped[str] = mapped_column(String(40), nullable=False)
    inspected_at: Mapped[str] = mapped_column(String(20), nullable=False)
    valid_until: Mapped[str] = mapped_column(String(20), nullable=False)
    inspector_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result: Mapped[str] = mapped_column(String(20), nullable=False, default="pass")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    certificate_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<Inspection equipment={self.equipment_id} {self.inspection_type} valid_until={self.valid_until}>"


class EquipmentRental(Base):
    """Internal rental of equipment to a project with billing rates."""

    __tablename__ = "oe_equipment_rental"
    __table_args__ = (Index("ix_oe_equipment_rental_status", "status"),)

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_equipment_equipment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_date: Mapped[str] = mapped_column(String(20), nullable=False)
    end_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    internal_rate_per_day: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    internal_rate_per_hour: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="",
        server_default="",
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<EquipmentRental equipment={self.equipment_id} project={self.project_id} {self.status}>"


class FuelLog(Base):
    """A single fuel fill event."""

    __tablename__ = "oe_equipment_fuel_log"

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_equipment_equipment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    logged_at: Mapped[str] = mapped_column(String(20), nullable=False)
    fuel_liters: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    hour_meter_at_fill: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )
    odometer_km_at_fill: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )
    cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="",
        server_default="",
    )
    supplier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String(40), nullable=True)

    def __repr__(self) -> str:
        return f"<FuelLog equipment={self.equipment_id} {self.fuel_liters}L>"


class PartsLog(Base):
    """A part consumed during a work order or standalone replacement."""

    __tablename__ = "oe_equipment_parts_log"

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_equipment_equipment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_equipment_work_order.id", ondelete="SET NULL"),
        nullable=True,
    )
    part_number: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("1"),
        server_default="1",
    )
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="",
        server_default="",
    )
    logged_at: Mapped[str | None] = mapped_column(String(20), nullable=True)

    def __repr__(self) -> str:
        return f"<PartsLog equipment={self.equipment_id} part={self.part_number}>"


class DamageReport(Base):
    """A damage report filed against an equipment unit."""

    __tablename__ = "oe_equipment_damage_report"

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_equipment_equipment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reported_at: Mapped[str] = mapped_column(String(20), nullable=False)
    reported_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="minor")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    photos: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    repair_cost_estimate: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="",
        server_default="",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="reported",
    )
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_equipment_work_order.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<DamageReport equipment={self.equipment_id} {self.severity}/{self.status}>"
