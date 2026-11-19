# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Land and parcels ORM models (LADM ISO 19152, reduced to what a project needs).

Tables:
    oe_land_parcel - one registered piece of land: the id the register uses,
        legal area, computed area, acquisition status and its cost.
    oe_land_parcel_point - the boundary points of a parcel in ring order, in
        the project CRS, with the mark on the ground and its accuracy.
    oe_land_party - a person, organisation or public body holding a right.
    oe_land_right - ownership, lease, easement, servitude, mortgage or other
        restriction on a parcel, recorded as data (no legal assessment).
    oe_land_work_zone - the outline of the works (a road corridor, a site),
        checked against parcels that are not acquired yet.
    oe_land_parcel_settings - per-project thresholds for the PAR checks.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

_PROJECT_FK = "oe_projects_project.id"


class LandParcel(Base):
    """One parcel of land on the project's schedule."""

    __tablename__ = "oe_land_parcel"
    __table_args__ = (Index("ix_oe_land_parcel_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), nullable=False)
    # The id the national register uses; its format is a pack rule, never a core one.
    parcel_ref: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    legal_area: Mapped[Decimal | None] = mapped_column(Numeric(16, 4), nullable=True)
    computed_area: Mapped[Decimal | None] = mapped_column(Numeric(16, 4), nullable=True)
    ring_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    epsg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # needed | negotiating | acquired | expropriation
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="needed", server_default="needed")
    acquisition_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    acquired_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # manual | geojson | shapefile
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", server_default="manual")
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Parcels this one was split from or merged out of (ids as strings).
    parent_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Replaced by its children after a split or merge; kept for the record, left out of the checks.
    superseded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


class LandParcelPoint(Base):
    """One boundary point of a parcel, in ring order."""

    __tablename__ = "oe_land_parcel_point"
    __table_args__ = (Index("ix_oe_land_parcel_point_parcel", "parcel_id"),)

    parcel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_land_parcel.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    e: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    n: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    # How the corner is marked on the ground: monument | pin | pipe | stone | nail | unmarked | ""
    mark: Mapped[str] = mapped_column(String(30), nullable=False, default="", server_default="")
    accuracy_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    # found | set | calculated | ""
    corner_status: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    # Key of a corner precision class from country data, "" = none.
    accuracy_class: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")


class LandParty(Base):
    """Someone who holds a right on a parcel."""

    __tablename__ = "oe_land_party"
    __table_args__ = (Index("ix_oe_land_party_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # person | organisation | public
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="person", server_default="person")
    reference: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")


class LandRight(Base):
    """A right, restriction or responsibility on one parcel."""

    __tablename__ = "oe_land_right"
    __table_args__ = (Index("ix_oe_land_right_parcel", "parcel_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), nullable=False)
    parcel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_land_parcel.id", ondelete="CASCADE"), nullable=False
    )
    party_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("oe_land_party.id", ondelete="SET NULL"), nullable=True
    )
    # ownership | lease | easement | servitude | mortgage | restriction | other
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="ownership", server_default="ownership")
    share: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    registry_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)


class LandWorkZone(Base):
    """The outline of the works, as a ring of E/N pairs in the project CRS."""

    __tablename__ = "oe_land_work_zone"
    __table_args__ = (Index("ix_oe_land_work_zone_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ring: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # type: ignore[assignment]
    epsg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")


class LandParcelSettings(Base):
    """Thresholds of the parcel checks for one project (advisory defaults, no standard)."""

    __tablename__ = "oe_land_parcel_settings"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), nullable=False, unique=True
    )
    area_tolerance_pct: Mapped[Decimal] = mapped_column(
        Numeric(6, 3), nullable=False, default=Decimal("1"), server_default="1"
    )
    gap_tolerance_m: Mapped[Decimal] = mapped_column(
        Numeric(8, 3), nullable=False, default=Decimal("0.05"), server_default="0.05"
    )
