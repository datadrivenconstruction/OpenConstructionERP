# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Haul​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ tickets ORM models.

Tables:
    oe_haul_tickets_ticket   - one truck load: route, material, weights, truck,
                               rate, cost allocation, receiver and status.
    oe_haul_tickets_invoice  - a haulier invoice with its lines and the result
                               of the last reconciliation against the tickets.
    oe_haul_tickets_rate     - agreed haulier rates per material and basis.
    oe_haul_tickets_material - project materials beyond the built-in list.
    oe_haul_tickets_settings - per-project limits and mandatory fields.

Links into other modules (equipment, purchase order, BOQ position, transport,
delivery booking, party) are soft (no foreign key), so each module can be
disabled or its rows deleted without cascading into the ticket register.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


def _project_fk() -> Mapped[uuid.UUID]:
    return mapped_column(GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True)


class HaulTicket(Base):
    """One truck load to or from site."""

    __tablename__ = "oe_haul_tickets_ticket"
    __table_args__ = (
        Index("ix_haul_ticket_project_date", "project_id", "ticket_date"),
        Index("ix_haul_ticket_haulier_number", "project_id", "haulier_name", "ticket_number"),
        Index("ix_haul_ticket_position", "boq_position_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk()
    ticket_number: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    haul_type: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="inbound")
    ticket_date: Mapped[date] = mapped_column(Date, nullable=False)
    time_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    time_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    origin: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    origin_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    destination: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    destination_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="site")
    material_code: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    material_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(10), nullable=False, default="t")
    gross_t: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    tare_t: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    net_t: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    volume_m3: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    loads: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=Decimal("0"))
    truck_source: Mapped[str] = mapped_column(String(10), nullable=False, default="hired")
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    haulier_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    haulier_party_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    plate: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    driver_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    vehicle_max_gross_t: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    vehicle_capacity: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    po_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    rate_basis: Mapped[str] = mapped_column(String(10), nullable=False, default="t")
    rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    hours: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    cost_code: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="issued", index=True)
    reject_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    receiver_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    photos: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    waste_code: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    waste_catalogue: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    hazardous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    receiving_facility: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    facility_permit_ref: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    transport_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    delivery_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    qr_token: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="manual")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)

    def __repr__(self) -> str:
        return f"<HaulTicket {self.haulier_name}/{self.ticket_number} ({self.status})>"


class HaulInvoice(Base):
    """A haulier invoice reconciled line by line against the tickets."""

    __tablename__ = "oe_haul_tickets_invoice"

    project_id: Mapped[uuid.UUID] = _project_fk()
    haulier_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    invoice_number: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    lines: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class HaulRate(Base):
    """An agreed haulier rate; an empty material code applies to any material."""

    __tablename__ = "oe_haul_tickets_rate"

    project_id: Mapped[uuid.UUID] = _project_fk()
    haulier_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    material_code: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    rate_basis: Mapped[str] = mapped_column(String(10), nullable=False, default="t")
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    po_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class HaulMaterial(Base):
    """A project material added to the built-in list."""

    __tablename__ = "oe_haul_tickets_material"

    project_id: Mapped[uuid.UUID] = _project_fk()
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(10), nullable=False, default="t")
    haul_type: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    density_t_m3: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    waste_code: Mapped[str] = mapped_column(String(40), nullable=False, default="")


class HaulSettings(Base):
    """Per-project limits and the fields a ticket must carry."""

    __tablename__ = "oe_haul_tickets_settings"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    mandatory_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    max_gross_t: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    capacity_tolerance_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    price_tolerance_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    waste_catalogue: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
