# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site sensors​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ ORM models.

Tables:
    oe_site_sensors_device          - A sensor on a project (concrete, noise, dust, vibration, weather, water)
    oe_site_sensors_mix             - Strength-maturity curve of a concrete mix (ASTM C1074)
    oe_site_sensors_calibration     - A mix's calibration cubes: maturity index against measured strength
    oe_site_sensors_reading         - Raw readings, compact: (device, time) -> value, no surrogate key
    oe_site_sensors_reading_hourly  - Hourly min / max / mean that raw readings are folded into
    oe_site_sensors_reading_audit   - Who added, changed or deleted a reading entered by hand or imported
    oe_site_sensors_alert           - Exceedances, offline devices, strength reached; acknowledgement and links
    oe_site_sensors_strip           - Planned formwork strike on a pour, gated by the estimated strength

Raw readings older than the retention window are folded into the hourly table
and deleted (``SiteSensorsService.downsample``), so the time series on a small
server grows by about 24 rows per device and day once it settles.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

SENSOR_KINDS = ("concrete_maturity", "noise", "dust_pm10", "vibration", "weather", "water_level", "custom")
READING_SOURCES = ("device", "manual", "import")
ALERT_KINDS = ("exceedance", "offline", "strength_reached")
ALERT_STATUSES = ("open", "acknowledged", "closed")


class SensorDevice(Base):
    """One sensor on one project, authenticated for ingest by its own token."""

    __tablename__ = "oe_site_sensors_device"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_oe_site_sensors_device_code"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    # Overrides the country limit; required where the law sets none (water level, wind).
    limit_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    # A reading below this is an exceedance too (pump flow, humidity); any kind may set one.
    lower_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    # Where the device limits come from, or why the country default was overridden; shown next to the limit.
    limit_note: Mapped[str] = mapped_column(String(300), nullable=False, default="", server_default="")
    # Compare the mean over this many hours instead of each reading; blank keeps the kind's own rule.
    rolling_mean_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Readings are kept without any limit check (a custom sensor with nothing to enforce).
    record_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    # Empty means the project's country.
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="", server_default="")
    offline_after_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    token_prefix: Mapped[str] = mapped_column(String(12), nullable=False, default="", server_default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Concrete sensors: the mix, the pour and when it was cast.
    mix_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("oe_site_sensors_mix.id", ondelete="SET NULL"), nullable=True
    )
    pour_ref: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    cast_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    schedule_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Noise: the zone the country grades limits by (DE AVV Baulaerm 3.1.1 a-f); blank is the country default.
    noise_zone: Mapped[str] = mapped_column(String(4), nullable=False, default="", server_default="")
    # Vibration: building class (DIN 4150-3 line 1-3) and the band used when a reading has no frequency.
    building_class: Mapped[str] = mapped_column(String(4), nullable=False, default="", server_default="")
    frequency_band: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    # Soft references to the BIM element the device sits on or measures; the model is kept with the element.
    bim_model_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    bim_element_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<SensorDevice {self.code} ({self.kind})>"


class ConcreteMix(Base):
    """A mix's strength-maturity relationship: ``S = a + b * log10(index)``.

    ``method`` picks the index: ``nurse_saul`` (degC-hours above ``datum_temp_c``,
    0 degC by default per ASTM C1074) or ``equivalent_age`` (hours at
    ``reference_temp_c``, Arrhenius with ``activation_energy_kj_mol``). The
    curve is fitted to the mix's own calibration cubes; ``fit_r2`` and the
    calibrated index range come with the fit. The platform ships no default curve.
    """

    __tablename__ = "oe_site_sensors_mix"

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    datum_temp_c: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=Decimal("0"))
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="nurse_saul", server_default="nurse_saul")
    activation_energy_kj_mol: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, default=Decimal("40"), server_default="40"
    )
    reference_temp_c: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("20"), server_default="20"
    )
    fit_r2: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibrated_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibrated_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    curve_a: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    curve_b: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    strip_strength_mpa: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<ConcreteMix {self.code}>"


class CalibrationPoint(Base):
    """One calibration cube result of a mix: the maturity index at test and the measured strength."""

    __tablename__ = "oe_site_sensors_calibration"

    mix_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_site_sensors_mix.id", ondelete="CASCADE"), nullable=False, index=True
    )
    maturity_index: Mapped[float] = mapped_column(Float, nullable=False)
    strength_mpa: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    age_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")


sensor_reading = Table(
    "oe_site_sensors_reading",
    Base.metadata,
    Column("device_id", GUID(), ForeignKey("oe_site_sensors_device.id", ondelete="CASCADE"), primary_key=True),
    Column("recorded_at", DateTime(timezone=True), primary_key=True),
    Column("value", Float, nullable=False),
    # Vibration: dominant frequency of the reading in Hz, when the sensor reports it.
    Column("frequency_hz", Float, nullable=True),
    # device (token ingest), manual (typed in) or import (pasted CSV); only the last two can be edited.
    Column("source", String(10), nullable=False, default="device", server_default="device"),
    Column("entered_by", GUID(), nullable=True),
    Column("note", String(500), nullable=False, default="", server_default=""),
)

sensor_reading_hourly = Table(
    "oe_site_sensors_reading_hourly",
    Base.metadata,
    Column("device_id", GUID(), ForeignKey("oe_site_sensors_device.id", ondelete="CASCADE"), primary_key=True),
    Column("hour", DateTime(timezone=True), primary_key=True),
    Column("n", Integer, nullable=False),
    Column("v_min", Float, nullable=False),
    Column("v_max", Float, nullable=False),
    Column("v_avg", Float, nullable=False),
)


class ReadingAudit(Base):
    """One change to a reading entered by a person: created, updated or deleted, with the values before and after."""

    __tablename__ = "oe_site_sensors_reading_audit"
    __table_args__ = (Index("ix_oe_site_sensors_reading_audit_device", "device_id", "recorded_at"),)

    device_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_site_sensors_device.id", ondelete="CASCADE"), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    value_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class SensorAlert(Base):
    """An event a person has to see: a limit exceeded, a sensor silent, a strength reached."""

    __tablename__ = "oe_site_sensors_alert"
    __table_args__ = (
        Index("ix_oe_site_sensors_alert_project_status", "project_id", "status"),
        Index("ix_oe_site_sensors_alert_device_kind", "device_id", "kind"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_site_sensors_device.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", server_default="open")
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    limit_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    limit_source: Mapped[str] = mapped_column(String(300), nullable=False, default="", server_default="")
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Where the follow-up lives: a daily diary, an inspection, a punch list item.
    diary_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    inspection_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    punch_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:
        return f"<SensorAlert {self.kind} {self.status}>"


class FormworkStrip(Base):
    """A planned formwork strike on a pour, linked to its schedule activity."""

    __tablename__ = "oe_site_sensors_strip"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_site_sensors_device.id", ondelete="CASCADE"), nullable=False, index=True
    )
    element: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    schedule_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    target_strength_mpa: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    struck_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    strength_at_strike_mpa: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    # Required when struck below target: the cube result or back-propping that justified it.
    strike_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    struck_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned", server_default="planned")
    bim_model_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    bim_element_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:
        return f"<FormworkStrip {self.element} {self.status}>"
