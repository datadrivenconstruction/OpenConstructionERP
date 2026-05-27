"""Accommodation ORM models.

Tables (all prefixed ``oe_accommodation_``):

    accommodation — top-level housing asset (worker camp / rental / hotel)
    room          — individual occupiable unit inside an accommodation
    booking       — occupant stay (reservation through check-out)
    charge        — billable line-item attached to a booking

Money columns are :class:`~decimal.Decimal` via ``sa.Numeric`` — never
``Float``. Every NOT NULL column carries a ``server_default`` so a fresh
SQLite ``create_all`` install can't trip an ``IntegrityError`` (see
post-v4.4.1 server-default discipline note).

The ``kind`` field on Accommodation discriminates use-cases:

    * ``worker_camp`` — free, employer-owned
    * ``rental``      — paid, third-party tenants
    * ``hotel``       — short-stay, daily-rate

Differences are configuration on the parent asset, not different tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime  # noqa: F401 — used in Mapped[datetime]
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

# ── Accommodation ─────────────────────────────────────────────────────────


class Accommodation(Base):
    """A housing asset belonging to a project.

    The ``kind`` discriminator selects the operating mode; rooms /
    bookings / charges share their shape across all three.
    """

    __tablename__ = "oe_accommodation_accommodation"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # Free-form at the DB layer; enforced as enum in the Pydantic schemas.
    kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="worker_camp",
        server_default="worker_camp",
        index=True,
    )
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    # WGS84. Stored as Numeric so we don't lose precision via SQLite REAL.
    geo_lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    geo_lon: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    # Optional integrations: never FK-constrained because the BIM Hub /
    # PropDev modules can be disabled per-tenant. We carry an opaque
    # GUID and look the row up at query time only when the module is
    # available.
    bim_model_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    property_dev_block_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    capacity_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Soft-delete tombstone — set by DELETE handler instead of dropping
    # the row. List queries filter on ``deleted_at IS NULL``.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<Accommodation {self.name!r} ({self.kind})>"


# ── Room ──────────────────────────────────────────────────────────────────


class Room(Base):
    """A single occupiable unit inside an :class:`Accommodation`.

    ``label`` is the human-facing room identifier (``"B-203"``,
    ``"Camp-12-bunk-04"``, ``"Suite 7"``) and must be unique per parent
    accommodation.
    """

    __tablename__ = "oe_accommodation_room"
    __table_args__ = (
        UniqueConstraint(
            "accommodation_id",
            "label",
            name="uq_oe_accommodation_room_accom_label",
        ),
        Index(
            "ix_oe_accommodation_room_status",
            "accommodation_id",
            "status",
        ),
    )

    accommodation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey(
            "oe_accommodation_accommodation.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # Canonical-format element id (string — DDC cad2data emits opaque
    # IDs that aren't necessarily UUIDs). Optional, only populated when
    # the room maps to a CAD/BIM element.
    bim_element_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    base_rate: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    # Empty default — service layer fills in from accommodation/project at
    # write time rather than hard-coding EUR (v3 DB-level EUR-default kill).
    base_rate_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    # NOTE: no ``index=True`` here — the composite index declared in
    # ``__table_args__`` above covers ``(accommodation_id, status)``
    # which is the only access pattern. A separate single-column
    # ``status`` index would collide on name with the composite under
    # SQLAlchemy's naming convention (``ix_oe_accommodation_room_status``).
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="available",
        server_default="available",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<Room {self.label!r} ({self.status})>"


# ── Booking ───────────────────────────────────────────────────────────────


class Booking(Base):
    """An occupant stay — reservation through check-out.

    ``occupant_contact_id`` is the canonical link when the occupant has a
    row in the Contacts directory. ``occupant_name`` is the free-text
    fallback for stays that aren't attached to a contact (e.g. crew
    bunks filled by HR roster pulls that haven't been promoted to
    proper contacts yet).
    """

    __tablename__ = "oe_accommodation_booking"
    __table_args__ = (
        Index(
            "ix_oe_accommodation_booking_occupant_contact_id",
            "occupant_contact_id",
        ),
    )

    room_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_accommodation_room.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    occupant_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_contacts_contact.id", ondelete="SET NULL"),
        nullable=True,
    )
    occupant_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    check_in: Mapped[datetime] = mapped_column(Date, nullable=False)
    # Open-ended bookings (worker-camp residency) carry NULL check_out.
    check_out: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="reserved",
        server_default="reserved",
        index=True,
    )
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="manual",
        server_default="manual",
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<Booking room={self.room_id} {self.status}>"


# ── Charge ────────────────────────────────────────────────────────────────


class Charge(Base):
    """A billable line-item attached to a booking.

    ``kind`` discriminates ``base_rent`` / ``extra`` / ``deposit`` /
    ``refund``. Money is Decimal — Float would lose cents on the very
    first rollup.
    """

    __tablename__ = "oe_accommodation_charge"

    booking_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_accommodation_booking.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="extra",
        server_default="extra",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    # Service layer fills in from parent room/accommodation if blank.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    period_start: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<Charge booking={self.booking_id} {self.kind} {self.amount}>"
