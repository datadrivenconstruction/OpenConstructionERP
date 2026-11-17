# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Deformation monitoring ORM models.

Tables:
    oe_monitoring_settings - which threshold profile a project uses (demo, pack or project profile).
    oe_monitoring_profile - a project's own threshold profile (displacement and rate levels).
    oe_monitoring_point - a monitoring point: prism, settlement pin, convergence chord or inclinometer.
    oe_monitoring_epoch - one round of readings (a date).
    oe_monitoring_reading - one point's reading in one epoch, coordinates or a value in metres.
    oe_monitoring_alert - a level crossing: the thresholds it was judged against are
        snapshotted, so a later profile edit never rewrites it. Acknowledgement lives here.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

_PROJECT_FK = "oe_projects_project.id"


class MonitoringSettings(Base):
    """The profile one project's monitoring is judged against."""

    __tablename__ = "oe_monitoring_settings"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_monitoring_settings_project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), nullable=False)
    # "demo" | "pack:<..>" | "project:<uuid>" | "" (no profile)
    profile_key: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")


class MonitoringProfile(Base):
    """A threshold profile a project defined for itself."""

    __tablename__ = "oe_monitoring_profile"
    __table_args__ = (Index("ix_oe_monitoring_profile_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    alert_mm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    action_mm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    alarm_mm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    rate_alert: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    rate_action: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    rate_alarm: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    reference: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class MonitoringPoint(Base):
    """A monitoring point of the project."""

    __tablename__ = "oe_monitoring_point"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_monitoring_point_project_code"),
        Index("ix_oe_monitoring_point_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # prism | settlement_pin | convergence_chord | inclinometer
    point_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="settlement_pin", server_default="settlement_pin"
    )
    # How displacement is read: z | horizontal | 3d | value
    axis: Mapped[str] = mapped_column(String(16), nullable=False, default="z", server_default="z")
    location: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class MonitoringEpoch(Base):
    """One round of readings."""

    __tablename__ = "oe_monitoring_epoch"
    __table_args__ = (UniqueConstraint("project_id", "observed_at", name="uq_oe_monitoring_epoch_project_at"),)

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    imported_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class MonitoringReading(Base):
    """One point's reading in one epoch. Coordinates and values are metres."""

    __tablename__ = "oe_monitoring_reading"
    __table_args__ = (
        UniqueConstraint("point_id", "epoch_id", name="uq_oe_monitoring_reading_point_epoch"),
        Index("ix_oe_monitoring_reading_point", "point_id"),
        Index("ix_oe_monitoring_reading_epoch", "epoch_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), nullable=False)
    point_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_monitoring_point.id", ondelete="CASCADE"), nullable=False
    )
    epoch_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_monitoring_epoch.id", ondelete="CASCADE"), nullable=False
    )
    e: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    n: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    z: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)


class MonitoringAlert(Base):
    """A crossed level, with who acknowledged it and why."""

    __tablename__ = "oe_monitoring_alert"
    __table_args__ = (
        Index("ix_oe_monitoring_alert_point", "point_id"),
        Index("ix_oe_monitoring_alert_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), nullable=False)
    point_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_monitoring_point.id", ondelete="CASCADE"), nullable=False
    )
    reading_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_monitoring_reading.id", ondelete="CASCADE"), nullable=False
    )
    # alert | action | alarm
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    displacement_mm: Mapped[Decimal] = mapped_column(Numeric(10, 1), nullable=False)
    rate_mm_day: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    profile_label: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    thresholds: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    risk_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    acknowledged_by_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
