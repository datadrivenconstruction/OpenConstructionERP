# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Leasing ORM models.

Tables:
    oe_leasing_lease          - one lease of one unit to one tenant
    oe_leasing_schedule_line  - one rent period; ``invoice_id`` names the finance invoice raised for it
    oe_leasing_lease_document - project document attached to a lease (FK to the document)
    oe_leasing_event          - lifecycle record: created, activated, notice, renewed, terminated, reviewed

Parties and units are referenced softly: ``tenant_contact_id`` is a contacts row,
``landlord_legal_entity_id`` a legal entity, ``unit_ref`` a property development
plot or an asset register entry named by ``unit_kind``. The module therefore
installs without property development or the asset register. Money is Numeric,
never float.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_types import SafeDate
from app.database import GUID, Base

__all__ = ["Lease", "LeaseDocument", "LeaseEvent", "RentScheduleLine"]


class Lease(Base):
    """A lease of one unit to one tenant for a period."""

    __tablename__ = "oe_leasing_lease"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_leasing_lease_project_code"),
        Index("ix_leasing_lease_unit", "unit_kind", "unit_ref"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    unit_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="plot", server_default="plot")
    unit_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    unit_label: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    tenant_contact_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    landlord_legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    start_date: Mapped[date] = mapped_column(SafeDate(), nullable=False)
    end_date: Mapped[date] = mapped_column(SafeDate(), nullable=False)
    term_months: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rent_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="monthly", server_default="monthly")
    deposit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    escalation_kind: Mapped[str] = mapped_column(String(10), nullable=False, default="none", server_default="none")
    escalation_rate: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    escalation_index: Mapped[str | None] = mapped_column(String(100), nullable=True)
    escalation_every_months: Mapped[int] = mapped_column(Integer, nullable=False, default=12, server_default="12")
    tax_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False, default=Decimal("0"), server_default="0")
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft", server_default="draft", index=True)
    break_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    notice_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    ended_on: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    renewed_from_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    ext_refs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")  # type: ignore[assignment]
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    document_links: Mapped[list[LeaseDocument]] = relationship(
        "LeaseDocument", cascade="all, delete-orphan", lazy="selectin", order_by="LeaseDocument.created_at"
    )

    @property
    def document_ids(self) -> list[str]:
        """Ids of the linked documents, oldest link first."""
        return [str(x.document_id) for x in self.document_links]

    def __repr__(self) -> str:
        return f"<Lease {self.code} {self.status}>"


class LeaseDocument(Base):
    """A project document attached to a lease. The foreign key drops the link when the document is deleted."""

    __tablename__ = "oe_leasing_lease_document"
    __table_args__ = (UniqueConstraint("lease_id", "document_id", name="uq_leasing_lease_document"),)

    lease_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_leasing_lease.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_documents_document.id", ondelete="CASCADE"), nullable=False, index=True
    )


class RentScheduleLine(Base):
    """One rent period of a lease. Unique per (lease, period start), so regenerating is idempotent."""

    __tablename__ = "oe_leasing_schedule_line"
    __table_args__ = (UniqueConstraint("lease_id", "period_start", name="uq_leasing_line_lease_period"),)

    lease_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_leasing_lease.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    period_start: Mapped[date] = mapped_column(SafeDate(), nullable=False)
    period_end: Mapped[date] = mapped_column(SafeDate(), nullable=False)
    due_date: Mapped[date] = mapped_column(SafeDate(), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    tax_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    review_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)


class LeaseEvent(Base):
    """A lifecycle record of a lease, newest last."""

    __tablename__ = "oe_leasing_event"

    lease_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_leasing_lease.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    event_date: Mapped[date] = mapped_column(SafeDate(), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")  # type: ignore[assignment]
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
