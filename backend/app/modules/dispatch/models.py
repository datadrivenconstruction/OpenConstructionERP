# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dispatch board ORM models.

Tables:
    oe_dispatch_location        - a board column: a project site, the yard, the shop, rental returned
    oe_dispatch_crew            - a named gang of resources people with a foreman and a minimum size
    oe_dispatch_placement       - one card on one column on one day
    oe_dispatch_scheduled_move  - a move booked ahead, applied on its date
    oe_dispatch_view_pref       - per-user card density

Cards point softly at other modules by ``card_ref``: a resources person, an equipment unit,
an equipment rental or a dispatch crew. The board therefore never copies people or machines.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_types import SafeDate
from app.database import GUID, Base

__all__ = ["DispatchCrew", "DispatchLocation", "DispatchPlacement", "DispatchScheduledMove", "DispatchViewPref"]


class DispatchLocation(Base):
    """One column of the board."""

    __tablename__ = "oe_dispatch_location"
    __table_args__ = (Index("ix_dispatch_location_kind_active", "kind", "is_active"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="project", server_default="project")
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")


class DispatchCrew(Base):
    """A gang of people who are dispatched together."""

    __tablename__ = "oe_dispatch_crew"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    foreman_resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # The platform user who receives the daily plan for this crew.
    foreman_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    member_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    min_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    trade: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    # Optional link to a labour rates crew build-up, so costing and dispatch share one crew.
    labor_crew_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")


class DispatchPlacement(Base):
    """One card on one column on one day."""

    __tablename__ = "oe_dispatch_placement"
    __table_args__ = (
        UniqueConstraint("day", "card_kind", "card_ref", "location_id", name="uq_dispatch_placement_card_day_loc"),
        Index("ix_dispatch_placement_day_loc", "day", "location_id"),
        Index("ix_dispatch_placement_card_day", "card_kind", "card_ref", "day"),
    )

    day: Mapped[date] = mapped_column(SafeDate(), nullable=False)
    card_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    card_ref: Mapped[str] = mapped_column(String(36), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_dispatch_location.id", ondelete="CASCADE"), nullable=False
    )
    operator_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False, default="07:00", server_default="07:00")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", server_default="manual")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class DispatchScheduledMove(Base):
    """A move booked for a future date; applied on that date and then kept as history."""

    __tablename__ = "oe_dispatch_scheduled_move"
    __table_args__ = (Index("ix_dispatch_move_status_date", "status", "effective_date"),)

    card_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    card_ref: Mapped[str] = mapped_column(String(36), nullable=False)
    to_location_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_dispatch_location.id", ondelete="CASCADE"), nullable=False
    )
    effective_date: Mapped[date] = mapped_column(SafeDate(), nullable=False)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False, default="07:00", server_default="07:00")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class DispatchViewPref(Base):
    """How one user likes the board drawn."""

    __tablename__ = "oe_dispatch_view_pref"

    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, unique=True)
    card_density: Mapped[str] = mapped_column(String(10), nullable=False, default="detailed", server_default="detailed")
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
