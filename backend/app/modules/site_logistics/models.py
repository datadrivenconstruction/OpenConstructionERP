# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site Logistics & Delivery ORM models.

Tables:
    oe_site_logistics_gate          - site access gates with daily hours + slot capacity
    oe_site_logistics_laydown_zone  - material laydown / storage areas on site
    oe_site_logistics_delivery      - inbound delivery bookings scheduled against a gate
    oe_site_logistics_delivery_line - the bill positions a delivery carries
    oe_site_logistics_plant_position - site plant and crane positions on the site plan

Logistics plan (framework module 6, SPEC v1 2026-10-11), all project-scoped:
    oe_site_logistics_stage                   - expansion stages of the site layout
    oe_site_logistics_area                    - site areas with geometry and kind
    oe_site_logistics_area_allocation         - what an area is used for in a stage
    oe_site_logistics_media                   - utility connections (power, water ...)
    oe_site_logistics_media_demand            - demand on a connection per stage
    oe_site_logistics_concept                 - the logistics concept (one per project)
    oe_site_logistics_transport               - inbound and outbound movements
    oe_site_logistics_transport_permit        - transport permits (oversize, road occupancy ...)
    oe_site_logistics_permit_transport        - permits covering several transports
    oe_site_logistics_customs_case            - import / export customs data
    oe_site_logistics_customs_line            - goods lines with HS codes
    oe_site_logistics_customs_document        - the document checklist of a case
    oe_site_logistics_neighbourhood           - noise limits, quiet hours (one per project)
    oe_site_logistics_neighbour_issue         - complaints from the surroundings (Issue Hub source)
    oe_site_logistics_coordination            - dated coordination log

Plant and crane positions (``oe_site_logistics_plant_position``) are defined by
the plant register branch (module 5, Decision 6); a demand row links to one by
the soft ``site_plant_position_id``.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_types import MoneyType
from app.database import GUID, Base

# Canonical delivery-booking lifecycle. Kept here so schemas (validation
# pattern) and the service (transition rules) share one source of truth.
DELIVERY_STATUSES: tuple[str, ...] = (
    "requested",  # booked by requester, awaiting gate approval
    "approved",  # scheduled - holds its slot on the gate
    "rejected",  # declined (clash, wrong window, no capacity)
    "arrived",  # vehicle checked in at the gate
    "completed",  # unloaded and released
)


class Gate(Base):
    """A site access gate with daily operating hours and per-slot capacity."""

    __tablename__ = "oe_site_logistics_gate"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Daily operating window as "HH:MM" 24h strings - DB-agnostic and trivial to
    # compare against a delivery window's time-of-day (see validators.py).
    open_time: Mapped[str] = mapped_column(String(5), nullable=False, default="07:00")
    close_time: Mapped[str] = mapped_column(String(5), nullable=False, default="18:00")
    # How many vehicles the gate can handle per booking slot; drives capacity
    # planning and future slotting. Never zero - a gate with no capacity cannot
    # take deliveries.
    capacity_per_slot: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Access kind and load limits (rule 5). All nullable: a gate without limits
    # keeps working and is reported once as ``gate_limits_unknown``.
    access_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    max_axle_load_t: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    max_gross_t: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    max_height_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    max_width_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    max_length_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    turning_radius_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<Gate {self.name} ({self.open_time}-{self.close_time})>"


class LaydownZone(Base):
    """A material laydown / storage area on site."""

    __tablename__ = "oe_site_logistics_laydown_zone"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Free-text capacity (e.g. "200 m2 / 40 t") rather than a modelled number:
    # laydown capacity on site is judged, not metered.
    capacity_desc: Mapped[str | None] = mapped_column(String(255), nullable=True)
    usage_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The planned site area this zone operates in (rule 4). The area table is younger
    # than this one, and the boot heal alters existing tables before ``create_all``
    # builds new ones; the heal defers a key like this one until its target exists
    # (``heal_deferred_foreign_keys``), so an upgraded install gets it on the same boot.
    # The service also checks the area on write and unlinks the zone when the area is
    # deleted (``LogisticsPlanService.delete_area``); an unlinked zone reads as
    # ``zone_not_mapped``.
    site_area_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_site_logistics_area.id", ondelete="SET NULL", name="fk_oe_site_zone_area"),
        nullable=True,
        index=True,
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<LaydownZone {self.name}>"


class DeliveryBooking(Base):
    """An inbound delivery booked into a time window against a site gate."""

    __tablename__ = "oe_site_logistics_delivery"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable: a delivery can be logged before a gate is assigned. SET NULL on
    # gate delete so removing a gate never destroys its delivery history.
    gate_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_site_logistics_gate.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    supplier_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    vehicle_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    materials_desc: Mapped[str | None] = mapped_column(Text, nullable=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested", index=True)
    po_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The movement this gate slot belongs to (Decision 3): a transport may own
    # several bookings, a booking stays the slot.
    # Added on upgrade the way ``LaydownZone.site_area_id`` is; also checked on write
    # and unlinked by ``LogisticsPlanService.delete_transport``.
    transport_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_site_logistics_transport.id", ondelete="SET NULL", name="fk_oe_site_delivery_transport"),
        nullable=True,
        index=True,
    )
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="inbound", server_default="inbound")
    gross_weight_t: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # Soft links: the plant register item (module 5) and the takt location (JIT, rule 11).
    plant_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    takt_location_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # The material flow of the logistics concept this delivery belongs to (rule 11).
    flow_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # What the truck is carrying, expressed as bill positions. Always read with
    # the booking (the delivery board renders them on every row), hence selectin.
    lines: Mapped[list["DeliveryLine"]] = relationship(
        "app.modules.site_logistics.models.DeliveryLine",
        back_populates="delivery",
        cascade="all, delete-orphan",
        order_by="DeliveryLine.sort_order",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<DeliveryBooking {self.supplier_name} {self.window_start:%Y-%m-%d %H:%M} ({self.status})>"


class DeliveryLine(Base):
    """One bill position a delivery carries, with the quantity being delivered.

    A delivery is the arrival of work the estimate already priced, so a line
    points at the BOQ position instead of repeating its description in free
    text. That is what lets the board answer "how much of position 03.10.020 is
    still to come" without anyone re-typing the bill.

    ``boq_position_id`` is ``ON DELETE SET NULL`` on purpose, and this is the
    module's orphan discipline: a delivery is a physical event that happened, so
    deleting an estimate line must never erase the record that 200 m3 arrived on
    site. The line keeps its own ``description`` / ``position_ordinal``
    snapshot, taken when the link was made, and simply reads as detached from
    the bill afterwards. The schedule module solves the same problem for its
    JSON ``Activity.boq_position_ids`` array with a best-effort scrub
    (``BOQService._scrub_activity_position_refs``); a real foreign key does not
    need one, because the database performs it inside the delete transaction.
    """

    __tablename__ = "oe_site_logistics_delivery_line"
    __table_args__ = (
        Index("ix_site_logistics_line_delivery", "delivery_id"),
        Index("ix_site_logistics_line_position", "boq_position_id"),
    )

    delivery_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_site_logistics_delivery.id", ondelete="CASCADE"),
        nullable=False,
    )
    # NULL means the bill position was deleted after the delivery was booked -
    # the physical record survives, detached. See the class docstring.
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_position.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Snapshot of the bill line as it read when the link was made. Kept so a
    # detached line still says what arrived, and so a printed delivery note does
    # not change retroactively when the estimator rewords the position.
    position_ordinal: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # A quantity, never money: the value on site is derived from the position's
    # current unit rate so the bill stays the single source of price truth.
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    delivery: Mapped["DeliveryBooking"] = relationship(
        "app.modules.site_logistics.models.DeliveryBooking",
        back_populates="lines",
        lazy="raise_on_sql",
    )

    def __repr__(self) -> str:
        return f"<DeliveryLine {self.position_ordinal or '-'} {self.quantity} {self.unit}>"


class SitePlantPosition(Base):
    """A piece of site plant placed on the site plan: crane, hoist, site office, temporary power ...

    ``kind`` comes from the ``site_plant_kinds`` of the plant register catalogue.
    The physical unit, when it is the contractor's fleet, is a soft link to
    ``equipment`` (``equipment_id``); this row only says where and when it stands.
    The plant register reads these rows for its frame summary; logistics reads
    them for crane reach over laydown zones.
    """

    __tablename__ = "oe_site_logistics_plant_position"
    __table_args__ = (
        Index("ix_oe_site_plantpos_project", "project_id"),
        Index("ix_oe_site_plantpos_stage", "project_id", "stage_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE", name="fk_oe_site_plant_position_project"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # A point in the local frame of the site plan: metres, x to the right, y up.
    x: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    y: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    reach_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    max_load_t: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    from_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    to_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    laydown_zone_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Soft links, checked on write: the plant register item this is the place of, and the
    # expansion stage of the site layout the position belongs to (None = every stage).
    plant_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    stage_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Connected load of the plant standing here; the utilities plan reads it as a demand.
    power_demand_kva: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    def __repr__(self) -> str:
        return f"<SitePlantPosition {self.kind} {self.name}>"


# ── Logistics plan (framework module 6) ────────────────────────────────────

_PROJECT_FK = "oe_projects_project.id"


def _project_fk(name: str) -> Mapped[uuid.UUID]:
    return mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name=name), nullable=False)


class ExpansionStage(Base):
    """An expansion stage of the site layout (earthworks, structure, fit-out ...).

    Dates are READ from the schedule through the soft activity ids (Decision 7);
    ``from_date`` / ``to_date`` are the declared fallback when no activity is linked.
    """

    __tablename__ = "oe_site_logistics_stage"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_site_stage_code"),
        Index("ix_oe_site_stage_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_site_stage_project")
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    from_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    to_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    from_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    to_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    # The site plan drawing of this stage: a document of the project (checked on write)
    # and how its pixels map to the local metre frame the areas are drawn in. Deleting
    # the document takes the drawing off the stage; the areas keep their geometry.
    plan_document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_documents_document.id", ondelete="SET NULL", name="fk_oe_site_stage_plan_document"),
        nullable=True,
    )
    plan_metres_per_pixel: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    plan_origin_px: Mapped[list | None] = mapped_column(JSON, nullable=True)


class SiteArea(Base):
    """A planned area of the site: its kind, its polygon and its size.

    ``geometry`` is a GeoJSON Polygon in the ``frame`` named (``local`` site plan
    metres or ``wgs84``). ``area_m2`` is computed from it on write; without a
    polygon the declared ``area_m2_declared`` is used.
    """

    __tablename__ = "oe_site_logistics_area"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_site_area_code"),
        Index("ix_oe_site_area_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_site_area_project")
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    area_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    geometry: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    frame: Mapped[str] = mapped_column(String(10), nullable=False, default="local")
    area_m2: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    area_m2_declared: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    geo_overlay_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    takt_location_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    owner_party: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    @property
    def effective_m2(self) -> Decimal | None:
        """The computed area when a polygon is drawn, else the declared one."""
        return self.area_m2 if self.area_m2 is not None else self.area_m2_declared


class AreaAllocation(Base):
    """What one area is used for in one stage, and how much of it (rule 1, 2).

    The area balance is computed from these rows and never stored (Decision 2).
    """

    __tablename__ = "oe_site_logistics_area_allocation"
    __table_args__ = (
        UniqueConstraint("site_area_id", "stage_id", name="uq_oe_site_alloc_area_stage"),
        Index("ix_oe_site_alloc_project_stage", "project_id", "stage_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_site_alloc_project")
    site_area_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_site_logistics_area.id", ondelete="CASCADE", name="fk_oe_site_alloc_area"),
        nullable=False,
    )
    stage_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_site_logistics_stage.id", ondelete="CASCADE", name="fk_oe_site_alloc_stage"),
        nullable=False,
    )
    area_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    allocated_m2: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"))
    use_note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class MediaConnection(Base):
    """A utility connection: power, water, sewage, telecom, heat or gas."""

    __tablename__ = "oe_site_logistics_media"
    __table_args__ = (Index("ix_oe_site_media_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_site_media_project")
    media_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    phase: Mapped[str] = mapped_column(String(20), nullable=False, default="construction")
    provider_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    provider_vendor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    connection_point: Mapped[str] = mapped_column(Text, nullable=False, default="")
    connection_point_geometry: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    capacity_unit: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    available_capacity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    contracted_capacity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    application_ref: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    applied_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    promised_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    connected_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    document_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="identified")


class MediaDemand(Base):
    """The peak demand of one consumer on one connection in one stage (rule 8, 9).

    A row with ``site_plant_position_id`` is written by the service from the plant
    position's power demand and is never typed by hand: one number per consumer.
    """

    __tablename__ = "oe_site_logistics_media_demand"
    __table_args__ = (
        Index("ix_oe_site_demand_media", "media_connection_id"),
        Index("ix_oe_site_demand_project_stage", "project_id", "stage_id"),
        # Rule 9: one demand row per plant position. Partial, so hand-typed demands
        # (no position) are not constrained.
        Index(
            "uq_oe_site_demand_plant_position",
            "project_id",
            "site_plant_position_id",
            unique=True,
            postgresql_where=text("site_plant_position_id IS NOT NULL"),
            sqlite_where=text("site_plant_position_id IS NOT NULL"),
        ),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_site_demand_project")
    media_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_site_logistics_media.id", ondelete="SET NULL", name="fk_oe_site_demand_media"),
        nullable=True,
    )
    # Kept on the demand so a demand without a connection still says what it
    # needs (``media_unsourced``).
    media_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    stage_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_site_logistics_stage.id", ondelete="CASCADE", name="fk_oe_site_demand_stage"),
        nullable=False,
    )
    consumer: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    site_plant_position_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    plant_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    peak_demand: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=Decimal("0"))
    simultaneity_factor: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, default=Decimal("1"))


class LogisticsConcept(Base):
    """The logistics concept of a project (one row): material flows and delivery rules.

    Its approved state is the governance frame document tagged for logistics; this
    row is the working content, versioned through that document's CDE revisions.
    It also pins the ``site_logistics`` catalogue the project plans with.
    """

    __tablename__ = "oe_site_logistics_concept"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_site_concept_project"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_site_concept_project")
    catalogue_source: Mapped[str] = mapped_column(String(20), nullable=False, default="shipped")
    catalogue_id: Mapped[str] = mapped_column(String(64), nullable=False, default="neutral")
    catalogue_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    strategy: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    delivery_open: Mapped[str | None] = mapped_column(String(5), nullable=True)
    delivery_close: Mapped[str | None] = mapped_column(String(5), nullable=True)
    max_deliveries_per_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rules_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    document_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # The IANA time zone of the site (``Europe/Berlin``). Every time-of-day, weekday
    # and date rule converts to it first; unset, those rules report
    # ``site_timezone_missing`` instead of guessing.
    site_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    saved_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class Transport(Base):
    """One inbound or outbound movement: origin, route, dimensions, permits, customs.

    ``is_heavy`` is derived on read from the dimensions against the catalogue load
    classes and the gate limits; it is never stored (rule 6).
    """

    __tablename__ = "oe_site_logistics_transport"
    __table_args__ = (Index("ix_oe_site_transport_window", "project_id", "planned_window_start"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_site_transport_project")
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="inbound")
    transport_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    carrier_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    origin: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    destination: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    gate_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_site_logistics_gate.id", ondelete="SET NULL", name="fk_oe_site_transport_gate"),
        nullable=True,
    )
    planned_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planned_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    po_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    plant_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    waste_record_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    customs_case_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    axle_load_t: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    gross_weight_t: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    height_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    width_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    length_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    turning_radius_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    route_geojson: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    route_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    escort_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The catalogue load class this vehicle is measured against (rule 6). Unset, a
    # transport is heavy only when no class of the catalogue admits it.
    load_class: Mapped[str | None] = mapped_column(String(40), nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    # The site date the transport left for the site; only goods receipts dated on
    # or after it can be its arrival (rule 19).
    in_transit_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    arrived_on: Mapped[date | None] = mapped_column(Date, nullable=True)


class TransportPermit(Base):
    """A transport-specific permit: oversize, road occupancy, traffic order, night work ...

    ``transport_id`` is the main transport; a permit covering several transports
    lists the others in :class:`PermitTransportLink`. A generic authority permit
    register (module 4) links by the soft ``authority_permit_id`` (Decision 4).
    """

    __tablename__ = "oe_site_logistics_transport_permit"
    __table_args__ = (Index("ix_oe_site_tpermit_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_site_tpermit_project")
    transport_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_site_logistics_transport.id", ondelete="SET NULL", name="fk_oe_site_tpermit_transport"),
        nullable=True,
    )
    permit_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    authority: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    reference: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    applied_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    allowed_windows: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    conditions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    route_geojson: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    document_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    authority_permit_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    expiry_notified_on: Mapped[date | None] = mapped_column(Date, nullable=True)


class PermitTransportLink(Base):
    """One more transport covered by a permit."""

    __tablename__ = "oe_site_logistics_permit_transport"
    __table_args__ = (
        UniqueConstraint("permit_id", "transport_id", name="uq_oe_site_permit_transport"),
        Index("ix_oe_site_ptlink_transport", "transport_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_site_ptlink_project")
    permit_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_site_logistics_transport_permit.id", ondelete="CASCADE", name="fk_oe_site_ptlink_permit"),
        nullable=False,
    )
    transport_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_site_logistics_transport.id", ondelete="CASCADE", name="fk_oe_site_ptlink_transport"),
        nullable=False,
    )


class CustomsCase(Base):
    """Customs data of one import or export: incoterm, origin, value, declaration (Decision 5)."""

    __tablename__ = "oe_site_logistics_customs_case"
    __table_args__ = (Index("ix_oe_site_customs_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_site_customs_project")
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="import")
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    incoterm: Mapped[str] = mapped_column(String(3), nullable=False)
    incoterm_version: Mapped[str] = mapped_column(String(10), nullable=False, default="2020")
    named_place: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    transport_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country_of_origin: Mapped[str | None] = mapped_column(String(2), nullable=True)
    country_of_destination: Mapped[str | None] = mapped_column(String(2), nullable=True)
    declarant_party: Mapped[str | None] = mapped_column(String(10), nullable=True)
    broker_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    customs_value: Mapped[Decimal | None] = mapped_column(MoneyType(18, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    declaration_ref: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    cleared_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    po_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="open")


class CustomsLine(Base):
    """One goods line of a customs case, classified by HS code."""

    __tablename__ = "oe_site_logistics_customs_line"
    __table_args__ = (Index("ix_oe_site_cline_case", "customs_case_id"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_site_cline_project")
    customs_case_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_site_logistics_customs_case.id", ondelete="CASCADE", name="fk_oe_site_cline_case"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    hs_code: Mapped[str] = mapped_column(String(10), nullable=False)
    # UNSPSC / CPV cross-reference only; never mapped to an HS code automatically.
    commodity_code_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    net_mass_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    value: Mapped[Decimal | None] = mapped_column(MoneyType(18, 2), nullable=True)
    # Required with ``value``; an amount never travels without its currency.
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    origin_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    preferential_origin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CustomsDocument(Base):
    """One document of a customs case's checklist (rule 15)."""

    __tablename__ = "oe_site_logistics_customs_document"
    __table_args__ = (
        UniqueConstraint("customs_case_id", "kind", name="uq_oe_site_cdoc_case_kind"),
        Index("ix_oe_site_cdoc_case", "customs_case_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_site_cdoc_project")
    customs_case_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_site_logistics_customs_case.id", ondelete="CASCADE", name="fk_oe_site_cdoc_case"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    document_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="missing")


class NeighbourhoodPlan(Base):
    """Noise limits, quiet hours and site traffic for the surroundings (one per project)."""

    __tablename__ = "oe_site_logistics_neighbourhood"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_site_neighbourhood_project"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_site_neighbourhood_project")
    zone_type: Mapped[str] = mapped_column(String(20), nullable=False, default="mixed")
    # A catalogue noise-limit code, or ``project`` for a consented project value.
    noise_limit_source: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    day_dba: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)
    night_dba: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)
    quiet_hours: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    site_traffic_routes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parking_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    municipality_contact: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    correspondence_thread_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class NeighbourIssue(Base):
    """A complaint from the surroundings (noise, dust, traffic ...) and our response.

    Stores no personal data by default (Decision 10): ``reporter`` is optional
    free text. It has an owner, a response date and a lifecycle, so the Unified
    Issue Hub lists open ones beside punch items and NCRs (source ``neighbour``).
    """

    __tablename__ = "oe_site_logistics_neighbour_issue"
    __table_args__ = (Index("ix_oe_site_nissue_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_site_nissue_project")
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    reported_on: Mapped[date] = mapped_column(Date, nullable=False)
    reporter: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    location: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    transport_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    delivery_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    response: Mapped[str] = mapped_column(Text, nullable=False, default="")
    response_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Who answers it; defaults to the owner of governance area m06 and is the
    # assignee the Issue Hub shows.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    overdue_notified_on: Mapped[date | None] = mapped_column(Date, nullable=True)


class CoordinationEntry(Base):
    """A dated coordination log row: municipality, utility, police, neighbours."""

    __tablename__ = "oe_site_logistics_coordination"
    __table_args__ = (Index("ix_oe_site_coord_project", "project_id", "entry_date"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_site_coord_project")
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    body: Mapped[str] = mapped_column(String(30), nullable=False, default="municipality")
    topic: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    outcome: Mapped[str] = mapped_column(Text, nullable=False, default="")
    next_action_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    correspondence_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
