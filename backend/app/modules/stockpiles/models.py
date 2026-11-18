# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Stockpile ORM models.

Tables:
    oe_stockpile - a pile on site: material, base surface, book stock, optional
        site inventory item.
    oe_stockpile_survey - one measurement: volume above the base, density with
        its source, tonnes, and the book stock and variance as they stood then.
    oe_stockpile_adjustment - the proposal to correct the inventory after a
        survey; booked only when a person confirms it.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Stockpile(Base):
    """A pile of material with a base surface and a book stock."""

    __tablename__ = "oe_stockpile"
    __table_args__ = (Index("ix_oe_stockpile_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    material: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    location_note: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    base_surface_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("oe_survey_surface.id", ondelete="SET NULL"), nullable=True
    )
    base_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # Plain id, no foreign key: site_inventory is an optional module.
    site_inventory_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    book_tonnes: Mapped[Decimal | None] = mapped_column(Numeric(16, 3), nullable=True)
    variance_tolerance_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class StockpileSurvey(Base):
    """One survey of a stockpile."""

    __tablename__ = "oe_stockpile_survey"
    __table_args__ = (Index("ix_oe_stockpile_survey_stockpile", "stockpile_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    stockpile_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_stockpile.id", ondelete="CASCADE"), nullable=False
    )
    surveyed_on: Mapped[date] = mapped_column(Date, nullable=False)
    # surface (a surveyed or scanned surface) | typed (volume from field software)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="surface", server_default="surface")
    pile_surface_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("oe_survey_surface.id", ondelete="SET NULL"), nullable=True
    )
    pile_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    volume_m3: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=0, server_default="0")
    cell_size_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    coverage_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    crs_epsg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    density_t_m3: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    # measured | supplier | assumed
    density_source: Mapped[str] = mapped_column(String(20), nullable=False, default="assumed", server_default="assumed")
    tonnes: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, default=0, server_default="0")
    book_tonnes: Mapped[Decimal | None] = mapped_column(Numeric(16, 3), nullable=True)
    variance_t: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    variance_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    # open | booked: a booked survey is locked, its adjustment is in the inventory
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", server_default="open")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # type: ignore[assignment]
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class StockpileAdjustment(Base):
    """A proposed (then confirmed or cancelled) correction of the book stock."""

    __tablename__ = "oe_stockpile_adjustment"
    __table_args__ = (Index("ix_oe_stockpile_adjustment_survey", "survey_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    stockpile_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_stockpile.id", ondelete="CASCADE"), nullable=False
    )
    survey_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_stockpile_survey.id", ondelete="CASCADE"), nullable=False
    )
    delta_t: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    # proposed | confirmed | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed", server_default="proposed")
    item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    movement_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    confirmed_by_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
