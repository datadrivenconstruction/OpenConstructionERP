# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service charges ORM models.

Tables:
    oe_service_charges_association     - an owners association of one project (property)
    oe_service_charges_key             - an apportionment key (area, permille, equal, custom)
    oe_service_charges_key_line        - one unit's share under a key
    oe_service_charges_budget          - the yearly charge budget, one per association and year
    oe_service_charges_budget_line     - one cost category of a budget and the key that splits it
    oe_service_charges_demand          - one unit's demand for one period; ``invoice_id`` is the finance receivable
    oe_service_charges_reconciliation  - the year-end balance per unit against actual costs

Units are soft references (``unit_ref``): a property development plot, an asset
register entry or any label the association uses. Money is Numeric, never float.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_types import SafeDate
from app.database import GUID, Base

__all__ = [
    "ApportionmentKey",
    "ApportionmentKeyLine",
    "BudgetLine",
    "ChargeBudget",
    "ChargeDemand",
    "OwnersAssociation",
    "YearEndReconciliation",
]


class OwnersAssociation(Base):
    """An owners association (or the landlord's service charge account) of one property."""

    __tablename__ = "oe_service_charges_association"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_svcchg_association_project_name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    registration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")  # type: ignore[assignment]
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fiscal_year_start_month: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class ApportionmentKey(Base):
    """How a cost is split over the units: by area, permille, equally or by custom percent."""

    __tablename__ = "oe_service_charges_key"
    __table_args__ = (UniqueConstraint("association_id", "name", name="uq_svcchg_key_association_name"),)

    association_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_service_charges_association.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="permille", server_default="permille")

    lines: Mapped[list[ApportionmentKeyLine]] = relationship(
        "ApportionmentKeyLine", cascade="all, delete-orphan", lazy="selectin", order_by="ApportionmentKeyLine.unit_ref"
    )


class ApportionmentKeyLine(Base):
    """One unit's share under a key, and who pays for that unit."""

    __tablename__ = "oe_service_charges_key_line"
    __table_args__ = (UniqueConstraint("key_id", "unit_ref", name="uq_svcchg_key_line_unit"),)

    key_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_service_charges_key.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    unit_label: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    share: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    payer_contact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class ChargeBudget(Base):
    """The yearly service charge budget of an association."""

    __tablename__ = "oe_service_charges_budget"
    __table_args__ = (UniqueConstraint("association_id", "year", name="uq_svcchg_budget_association_year"),)

    association_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_service_charges_association.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft", server_default="draft")
    demand_frequency: Mapped[str] = mapped_column(
        String(12), nullable=False, default="quarterly", server_default="quarterly"
    )
    default_key_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    lines: Mapped[list[BudgetLine]] = relationship(
        "BudgetLine", cascade="all, delete-orphan", lazy="selectin", order_by="BudgetLine.category"
    )


class BudgetLine(Base):
    """One cost category of a budget, split over the units by one key."""

    __tablename__ = "oe_service_charges_budget_line"
    __table_args__ = (UniqueConstraint("budget_id", "category", name="uq_svcchg_budget_line_category"),)

    budget_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_service_charges_budget.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    key_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_service_charges_key.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class ChargeDemand(Base):
    """One unit's demand for one period; unique per (budget, unit, period), so a rerun is idempotent."""

    __tablename__ = "oe_service_charges_demand"
    __table_args__ = (UniqueConstraint("budget_id", "unit_ref", "period", name="uq_svcchg_demand_unit_period"),)

    budget_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_service_charges_budget.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    unit_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    period: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_date: Mapped[date] = mapped_column(SafeDate(), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    payer_contact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)


class YearEndReconciliation(Base):
    """Year-end balance of a budget: actual costs by category and the balance of every unit."""

    __tablename__ = "oe_service_charges_reconciliation"
    __table_args__ = (UniqueConstraint("budget_id", name="uq_svcchg_reconciliation_budget"),)

    budget_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_service_charges_budget.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft", server_default="draft")
    actual_by_category: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")  # type: ignore[assignment]
    unit_balances: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")  # type: ignore[assignment]
    unallocated: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")  # type: ignore[assignment]
    sources: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")  # type: ignore[assignment]
    total_actual: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    total_demanded: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    posted_invoice_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")  # type: ignore[assignment]
    posted_credit_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")  # type: ignore[assignment]
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
