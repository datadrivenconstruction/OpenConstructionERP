# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Guarantees​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ register ORM models.

Tables:
    oe_guarantees_guarantee - one bank guarantee or bond on a project, given by the
                              company to a client or received from a subcontractor.
    oe_guarantees_event     - the audit history of a guarantee: every create, edit,
                              status move, reduction and document link, with the
                              before and after values.
    oe_guarantees_document  - a guarantee PDF (or amendment, release letter) held in
                              the documents module, linked by id.
    oe_guarantees_facility  - a bank credit line that guarantees draw on, so the
                              exposure dashboard can say how much of each line is used.

Soft links (``contract_id``, ``subcontractor_id``, ``tender_id``, ``bid_id``,
``document_id``, ``facility_id``) carry no foreign key, so the register never blocks
or cascades another module's deletes. Vocabulary columns are plain strings checked
at the API edge against :mod:`app.modules.guarantees.logic`.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_types import SafeDate
from app.database import GUID, Base


class Guarantee(Base):
    """One bank guarantee or bond.

    ``amount`` is the current face value; ``original_amount`` is what the bank first
    issued, so a reduced advance guarantee still shows where it started.
    ``advance_amount`` and ``advance_recovered`` only mean something on an advance
    payment guarantee: the register reduces ``amount`` to the advance still
    outstanding as interim payments recover it.
    """

    __tablename__ = "oe_guarantees_guarantee"
    __table_args__ = (
        Index("ix_guarantees_project_status", "project_id", "status"),
        Index("ix_guarantees_contract", "contract_id"),
        Index("ix_guarantees_expiry", "expiry_date"),
        UniqueConstraint("project_id", "reference", name="uq_guarantees_project_reference"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(60), nullable=False)
    guarantee_type: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="given", server_default="given")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    issuer_bank: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    bank_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    beneficiary: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    applicant: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    original_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    percent_of_contract: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    contract_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    issue_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    auto_extend: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    extension_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claim_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    defects_period_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    advance_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    advance_recovered: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    # Share of each certified gross amount that recovers the advance (FIDIC 14.2 amortisation).
    advance_recovery_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    replaces_cash_retention: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    commission_rate_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    form_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    contract_security_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    subcontractor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    tender_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    bid_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    facility_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    last_alert_band: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    events: Mapped[list["GuaranteeEvent"]] = relationship(
        back_populates="guarantee", cascade="all, delete-orphan", lazy="raise_on_sql"
    )
    documents: Mapped[list["GuaranteeDocument"]] = relationship(
        back_populates="guarantee", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Guarantee {self.reference} {self.guarantee_type} {self.status}>"


class GuaranteeEvent(Base):
    """One audit entry: who changed what on a guarantee, with the values before and after."""

    __tablename__ = "oe_guarantees_event"
    __table_args__ = (Index("ix_guarantees_event_guarantee", "guarantee_id", "created_at"),)

    guarantee_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_guarantees_guarantee.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amount_before: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    amount_after: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    changes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    source: Mapped[str | None] = mapped_column(String(60), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    guarantee: Mapped[Guarantee] = relationship(back_populates="events", lazy="raise_on_sql")


class GuaranteeDocument(Base):
    """A guarantee PDF, amendment or release letter kept in the documents module."""

    __tablename__ = "oe_guarantees_document"
    __table_args__ = (UniqueConstraint("guarantee_id", "document_id", name="uq_guarantees_document"),)

    guarantee_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_guarantees_guarantee.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="original", server_default="original")
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")

    guarantee: Mapped[Guarantee] = relationship(back_populates="documents", lazy="raise_on_sql")


class GuaranteeFacility(Base):
    """A bank credit line for guarantees, at company level."""

    __tablename__ = "oe_guarantees_facility"
    __table_args__ = (UniqueConstraint("bank_name", "currency", "name", name="uq_guarantees_facility"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(255), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    expiry_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
