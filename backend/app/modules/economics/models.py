# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Economics ORM models: business case, cost frame and financing plan of a project.

Tables (all prefixed ``oe_economics_``):
    plan            -- one per project: status, currency, classification standard, discount rate, horizon
    flow_line       -- a line of the business case (investment, revenue, operating cost, residual value)
    frame_line      -- a cost frame line: a budget for one classification code
    funding_source  -- a source of finance (equity, loan, grant, ...)
    tranche         -- a dated drawdown of one source
    approval        -- a proposed or approved version of the whole, frozen with a hash
    security, insurance, tax, process -- the registers that back the plan (never frozen)

Nothing the platform already knows is stored again: the estimate of a frame
line is read from the bill, what is committed from the commitment counting
rule, and an investment line may point at the cost frame instead of holding a
number. Money is exact decimal (``MoneyType(18, 4)``), calendar days are ISO
strings in ``String(40)`` as elsewhere on the platform, instants are
timezone-aware. Constraint and index names are written out (``*_oe_eco_*``) and
the migration uses the same strings. No ``relationship()``: rows reference each
other by id and the repository loads explicitly. Soft references into other
modules (the bill, a funding application) carry no foreign key.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_types import MoneyType
from app.database import GUID, Base

_PROJECT_FK = "oe_projects_project.id"


def _money() -> MoneyType:
    return MoneyType(18, 4)


def _rate() -> MoneyType:
    return MoneyType(9, 4)


def _project_fk(name: str) -> Any:
    return mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name=name), nullable=False)


class EconomicsPlan(Base):
    """The project's economics: status, currency, classification standard and the discounting basis."""

    __tablename__ = "oe_economics_plan"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_eco_plan_project"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_eco_plan_project")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    classification_standard: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")
    # Percent per year; None until the owner sets it, which a rule reports instead of discounting at zero.
    discount_rate_pct: Mapped[Decimal | None] = mapped_column(_rate(), nullable=True)
    horizon_years: Mapped[int] = mapped_column(Integer, nullable=False, default=20, server_default="20")
    # The bill the estimate is read from; None means the project's only (or latest) bill.
    boq_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Budget for markups, taxes and reserves the bill's cascade adds above its direct cost.
    markup_allowance: Mapped[Decimal] = mapped_column(_money(), nullable=False, default=Decimal("0"))
    current_approval_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    change_request_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}


class FlowLine(Base):
    """One line of the business case.

    ``mode`` ``total`` spreads ``amount`` over ``year_from..year_to``; ``per_year`` repeats it each
    year with ``escalation_pct`` compounding. ``source`` ``cost_frame`` means the amount is the cost
    frame total, read when needed, and ``amount`` is ignored.
    """

    __tablename__ = "oe_economics_flow_line"
    __table_args__ = (Index("ix_oe_eco_flow_project", "project_id", "sort_order"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_eco_flow_project")
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="total", server_default="total")
    source: Mapped[str] = mapped_column(String(12), nullable=False, default="manual", server_default="manual")
    amount: Mapped[Decimal] = mapped_column(_money(), nullable=False, default=Decimal("0"))
    year_from: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    year_to: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    escalation_pct: Mapped[Decimal] = mapped_column(_rate(), nullable=False, default=Decimal("0"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")


class FrameLine(Base):
    """A budget for one classification code of the project's standard."""

    __tablename__ = "oe_economics_frame_line"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_eco_frame_project_code"),
        Index("ix_oe_eco_frame_project", "project_id", "sort_order"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_eco_frame_project")
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    amount: Mapped[Decimal] = mapped_column(_money(), nullable=False, default=Decimal("0"))
    basis: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class FundingSource(Base):
    """A source of finance for the investment."""

    __tablename__ = "oe_economics_funding_source"
    __table_args__ = (Index("ix_oe_eco_source_project", "project_id", "sort_order"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_eco_source_project")
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    amount: Mapped[Decimal] = mapped_column(_money(), nullable=False, default=Decimal("0"))
    interest_rate_pct: Mapped[Decimal | None] = mapped_column(_rate(), nullable=True)
    # Soft link to a funding application of the project (grants and subsidies).
    funding_application_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")


class Tranche(Base):
    """A dated drawdown of one source."""

    __tablename__ = "oe_economics_tranche"
    __table_args__ = (Index("ix_oe_eco_tranche_source", "source_id", "due_on"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_eco_tranche_project")
    source_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_economics_funding_source.id", ondelete="CASCADE", name="fk_oe_eco_tranche_source"),
        nullable=False,
    )
    due_on: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    amount: Mapped[Decimal] = mapped_column(_money(), nullable=False, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="planned", server_default="planned")
    condition: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    drawn_on: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Approval(Base):
    """A version of the economics put forward for approval, frozen with the figures it was judged on."""

    __tablename__ = "oe_economics_approval"
    __table_args__ = (
        UniqueConstraint("project_id", "number", name="uq_oe_eco_approval_number"),
        Index("ix_oe_eco_approval_project", "project_id", "number"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_eco_approval_project")
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="proposed", server_default="proposed")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    proposed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    governance_ref_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    governance_document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_governance_document.id", ondelete="SET NULL", name="fk_oe_eco_approval_gov_document"),
        nullable=True,
    )
    four_eyes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    approval_blocked_reason: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")


class Security(Base):
    """A guarantee or bond that backs the project: performance, warranty, advance payment, bid."""

    __tablename__ = "oe_economics_security"
    __table_args__ = (Index("ix_oe_eco_security_project", "project_id", "sort_order"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_eco_security_project")
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    amount: Mapped[Decimal] = mapped_column(_money(), nullable=False, default=Decimal("0"))
    issuer: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    beneficiary: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    reference: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    valid_from: Mapped[str | None] = mapped_column(String(40), nullable=True)
    valid_until: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="requested", server_default="requested")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")


class Insurance(Base):
    """An insurance policy of the project: builders all risk, liability, professional indemnity."""

    __tablename__ = "oe_economics_insurance"
    __table_args__ = (Index("ix_oe_eco_insurance_project", "project_id", "sort_order"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_eco_insurance_project")
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    insurer: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    policy_number: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    sum_insured: Mapped[Decimal] = mapped_column(_money(), nullable=False, default=Decimal("0"))
    deductible: Mapped[Decimal] = mapped_column(_money(), nullable=False, default=Decimal("0"))
    period_from: Mapped[str | None] = mapped_column(String(40), nullable=True)
    period_to: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="requested", server_default="requested")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")


class TaxTreatment(Base):
    """How the project is treated for value added tax: one row per project."""

    __tablename__ = "oe_economics_tax"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_eco_tax_project"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_eco_tax_project")
    vat_treatment: Mapped[str] = mapped_column(
        String(20), nullable=False, default="standard", server_default="standard"
    )
    # None = not yet clarified.
    input_tax_deduction: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProcessSetup(Base):
    """Whether one administrative process (receivables, payables, administration) is set up."""

    __tablename__ = "oe_economics_process"
    __table_args__ = (UniqueConstraint("project_id", "area", name="uq_oe_eco_process_area"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_eco_process_project")
    area: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    owner: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="open", server_default="open")
    set_up_on: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
