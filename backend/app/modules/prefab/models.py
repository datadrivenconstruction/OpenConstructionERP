# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Off-site / Prefab / DfMA ORM models.

Tables:
    oe_prefab_unit             - an off-site manufactured unit (pod/panel/module/...)
    oe_prefab_production_event - immutable audit trail of every stage change
"""

import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class PrefabUnit(Base):
    """An off-site / prefabricated unit tracked from design to installation."""

    __tablename__ = "oe_prefab_unit"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Human reference / mark for the unit, e.g. "POD-L03-14" or "SIP-A-002".
    ref: Mapped[str] = mapped_column(String(120), nullable=False)
    unit_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="module",
        server_default="module",
    )
    # Current production stage. Only ever changed through the stage machine
    # (see PrefabService.advance_stage) - never via a plain field update.
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="design",
        server_default="design",
        index=True,
    )
    target_install_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    drawing_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Links back to canonical BIM elements this unit was fabricated from.
    # Nullable JSON list of element ids; follows the codebase JSON-list idiom.
    bim_element_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # ── Spine 4: optional cost links (additive, nullable) ────────────────
    # A unit may reflect the cost of a specific BOQ position and/or an
    # assembly recipe, so off-site production maps onto real cost and earned
    # value. Both are plain indexed GUIDs with NO ForeignKey - the same
    # cross-module-reference convention used elsewhere (e.g.
    # Position.cost_line_id, carbon element links) so the prefab module stays
    # decoupled from the BOQ / assemblies ORM. The linked rate is read at
    # serialisation time; nothing is cached on the unit.
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    assembly_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Supply-chain tracking: the token printed as a QR label on the unit, the
    # delivery note it arrived with, and the element it is installed into
    # (e.g. a pile mark) when no BIM element id exists.
    qr_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    delivery_note_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    element_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)

    def __repr__(self) -> str:
        return f"<PrefabUnit {self.ref} ({self.status})>"


class ProductionEvent(Base):
    """Immutable audit row written on every production-stage advance.

    One row is written inline inside ``PrefabService.advance_stage`` for every
    valid stage crossing, so a rolled-back transaction never leaves an orphan
    audit row (event-bus consumers can't guarantee that).
    """

    __tablename__ = "oe_prefab_production_event"

    unit_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_prefab_unit.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    from_stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<ProductionEvent unit={self.unit_id} stage={self.stage}>"
