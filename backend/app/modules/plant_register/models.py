# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Plant register ORM models.

Tables (all prefixed ``oe_plant_``):
    settings            -- the catalogue (source, id, version) one project pins
    item                -- one main component, user or operating equipment item
    lead_time_quote     -- append-only lead time history, enquiry date mandatory
    slot_reservation    -- factory capacity held for an item, with fee terms
    decision_paper      -- the option paper a critical item needs (approval route)
    delivery_limit      -- who does which step (supply .. document) for an item
    spare_part          -- the spares concept of an item
    it_service          -- construction-phase IT services of the project

Long-lead is not a column: it is derived from the basis quote and the
catalogue threshold on every read (Decision 2), so it cannot drift from the
lead time. Need date, latest order date and float are derived the same way.

No ``relationship()``: rows reference each other by id and the service loads
what a request needs, so no lazy load fires from async code. Soft references
into other modules (vendor, schedule activity, contract package, owner-furnished
item, purchase order, submittal, commissioning system, CDE container) carry no
foreign key. Constraint names are written out and match revision
``v71_plant_register``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy import UniqueConstraint as UQ
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

_PROJECT_FK = "oe_projects_project.id"
_ITEM_FK = "oe_plant_item.id"


def _project(name: str) -> Mapped[uuid.UUID]:
    return mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name=name), nullable=False)


def _item(name: str) -> Mapped[uuid.UUID]:
    return mapped_column(GUID(), ForeignKey(_ITEM_FK, ondelete="CASCADE", name=name), nullable=False)


class PlantSettings(Base):
    """The plant catalogue version a project pins (created on first use with the neutral one)."""

    __tablename__ = "oe_plant_settings"
    __table_args__ = (UQ("project_id", name="uq_oe_plant_settings_project"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_plant_settings_project")
    catalogue_source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="shipped", server_default="shipped"
    )
    catalogue_id: Mapped[str] = mapped_column(String(64), nullable=False, default="neutral", server_default="neutral")
    catalogue_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class PlantItem(Base):
    """One item of the register; the platform's only long-lead list for owner-specified plant."""

    __tablename__ = "oe_plant_item"
    __table_args__ = (
        UQ("project_id", "code", name="uq_oe_plant_item_code"),
        Index("ix_oe_plr_item_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_plant_item_project")
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    component_class_code: Mapped[str] = mapped_column(String(64), nullable=False)
    # main_component | user_equipment | operating_equipment
    item_class: Mapped[str] = mapped_column(String(40), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=Decimal(1), server_default="1")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="pcs", server_default="pcs")
    tag: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    wbs_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    bim_element_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    cx_system_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    space_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # Requirements: [{key, value, unit}], {access, mttr_target_hours, replacement_path}.
    performance: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    redundancy_scheme: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")
    maintainability: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # neutral | bound; bound needs a reason (standardisation, existing_estate, warranty, sole_source).
    vendor_policy: Mapped[str] = mapped_column(String(20), nullable=False, default="neutral", server_default="neutral")
    vendor_bound_reason: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # None = the class default decides; True/False = owner override, with reason.
    critical_override: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    critical_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    need_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    need_date_fixed: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Per-item override of the catalogue order buffers (transport_days, ...).
    order_buffers: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    procurement_route: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contract_package_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    owner_furnished_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # The order that supplies a contractor-furnished item; its status drives ordered/delivered.
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # The submittal whose review period counts when the lead runs from approved drawings.
    submittal_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    maintenance_strategy: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    no_strategic_spare_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    long_lead_override: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    long_lead_override_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="identified", server_default="identified")
    service_asset_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class LeadTimeQuote(Base):
    """One lead time answer, with the date it was asked (append-only)."""

    __tablename__ = "oe_plant_lead_time_quote"
    __table_args__ = (
        Index("ix_oe_plr_quote_item", "plant_item_id"),
        Index("ix_oe_plr_quote_project", "project_id"),
        # Rule 4: one basis per item, enforced by the database too.
        Index(
            "uq_oe_plant_quote_basis",
            "plant_item_id",
            unique=True,
            postgresql_where=text("is_basis"),
            sqlite_where=text("is_basis"),
        ),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_plant_quote_project")
    plant_item_id: Mapped[uuid.UUID] = _item("fk_oe_plant_quote_item")
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    enquiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    response_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    lead_weeks_min: Mapped[int] = mapped_column(Integer, nullable=False)
    lead_weeks_max: Mapped[int] = mapped_column(Integer, nullable=False)
    lead_basis: Mapped[str] = mapped_column(
        String(40), nullable=False, default="from_order", server_default="from_order"
    )
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    document_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    catalogue_entry_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    is_basis: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class SlotReservation(Base):
    """Factory capacity held for one item until the binding order is signed."""

    __tablename__ = "oe_plant_slot_reservation"
    __table_args__ = (
        Index("ix_oe_plr_slot_item", "plant_item_id"),
        Index("ix_oe_plr_slot_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_plant_slot_project")
    plant_item_id: Mapped[uuid.UUID] = _item("fk_oe_plant_slot_item")
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    vendor_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    slot_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    slot_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    reservation_fee: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    # none | partial | full
    fee_refundable: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    fee_credited_to_order: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    convert_by_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    terms: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # Money binds only through the commitment release (rule 13): soft link to that item.
    commitment_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    document_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="requested", server_default="requested")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class DecisionPaper(Base):
    """The option paper behind a critical item, approved through an approval route."""

    __tablename__ = "oe_plant_decision_paper"
    __table_args__ = (
        Index("ix_oe_plr_paper_item", "plant_item_id"),
        Index("ix_oe_plr_paper_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_plant_paper_project")
    plant_item_id: Mapped[uuid.UUID] = _item("fk_oe_plant_paper_item")
    question: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # [{code, title, vendor_id?, quote_id?, cost?, currency?, risk_ref?, scores: {criterion: "n"}}]
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    # [{code, title, weight: "n"}]
    criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    recommendation: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    approval_instance_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    # Frozen on approval: the paper exactly as it was approved, with computed scores.
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class DeliveryLimit(Base):
    """Who does one delivery step for one item: a neutral party code and/or a package."""

    __tablename__ = "oe_plant_delivery_limit"
    __table_args__ = (
        UQ("plant_item_id", "step", name="uq_oe_plant_limit_step"),
        Index("ix_oe_plr_limit_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_plant_limit_project")
    plant_item_id: Mapped[uuid.UUID] = _item("fk_oe_plant_limit_item")
    step: Mapped[str] = mapped_column(String(40), nullable=False)
    party: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    contract_package_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")


class SparePartRequirement(Base):
    """One line of an item's spares concept."""

    __tablename__ = "oe_plant_spare_part"
    __table_args__ = (
        Index("ix_oe_plr_spare_item", "plant_item_id"),
        Index("ix_oe_plr_spare_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_plant_spare_project")
    plant_item_id: Mapped[uuid.UUID] = _item("fk_oe_plant_spare_item")
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=Decimal(1), server_default="1")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="pcs", server_default="pcs")
    supply_by: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    supply_package_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Soft: a closeout slot or a service asset the spare is handed over against.
    handover_target: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    waiver_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="required", server_default="required")


class ItService(Base):
    """A construction-phase IT service: CDE access, site network, telecom ..."""

    __tablename__ = "oe_plant_it_service"
    __table_args__ = (Index("ix_oe_plr_it_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_plant_it_project")
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    responsible_party: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    needed_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    needed_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    needed_from_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    access_roles: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    cde_container_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned", server_default="planned")


ALL_MODELS: tuple[type[Base], ...] = (
    PlantSettings,
    PlantItem,
    LeadTimeQuote,
    SlotReservation,
    DecisionPaper,
    DeliveryLimit,
    SparePartRequirement,
    ItService,
)
