# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mine survey ORM models.

Tables:
    oe_mine_unit - a pit, bench, block, stope or drive.
    oe_mine_period - one reporting month with its demo or company profile.
    oe_mine_period_entry - one unit in one period: plan, the linked Volumes
        calculation (the actual), trucks and the claim trail.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class MineUnit(Base):
    """A mining unit that is planned and surveyed."""

    __tablename__ = "oe_mine_unit"
    __table_args__ = (Index("ix_oe_mine_unit_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # pit | bench | block | stope | drive
    unit_type: Mapped[str] = mapped_column(String(20), nullable=False, default="bench", server_default="bench")
    density_t_m3: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class MinePeriod(Base):
    """A reporting period (a month) with the checks that apply to it."""

    __tablename__ = "oe_mine_period"
    __table_args__ = (Index("ix_oe_mine_period_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(20), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    # Empty band or tolerance: the rule stays silent and the page says "No profile, set one".
    band_lo_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    band_hi_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    truck_tolerance_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    profile_label: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class MinePeriodEntry(Base):
    """One unit in one period."""

    __tablename__ = "oe_mine_period_entry"
    __table_args__ = (
        UniqueConstraint("period_id", "unit_id", name="uq_oe_mine_entry_period_unit"),
        Index("ix_oe_mine_entry_period", "period_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_mine_period.id", ondelete="CASCADE"), nullable=False
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_mine_unit.id", ondelete="CASCADE"), nullable=False
    )
    plan_m3: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=0, server_default="0")
    plan_t: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    plan_advance_m: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    actual_advance_m: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    density_t_m3: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    # The actual is this Volumes calculation (cut); it is never typed.
    actual_volume_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("oe_survey_volume.id", ondelete="SET NULL"), nullable=True
    )
    truck_loads: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    truck_t: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    truck_source: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    claim_entry_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    claimed_m3: Mapped[Decimal | None] = mapped_column(Numeric(16, 3), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # type: ignore[assignment]
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
