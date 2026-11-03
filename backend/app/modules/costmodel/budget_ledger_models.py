# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Budget ledger tables: transfers between cost lines, owner-approved budget modifications, audit trail.

Amounts are in the project base currency. Only ``approved`` rows change the revised budget.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


def _project_fk() -> Mapped[uuid.UUID]:
    return mapped_column(GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True)


class BudgetTransfer(Base):
    """Money moved between cost lines. The signed legs add up to zero."""

    __tablename__ = "oe_costmodel_budget_transfer"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_costmodel_budget_transfer_code"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft", server_default="draft")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    requested_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")


class BudgetTransferLeg(Base):
    """One side of a transfer: negative takes budget off the line, positive adds it."""

    __tablename__ = "oe_costmodel_budget_transfer_leg"

    transfer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_costmodel_budget_transfer.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cost_line_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_costmodel_cost_line.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)


class BudgetModification(Base):
    """An owner-approved change of the budget, apart from contract change orders."""

    __tablename__ = "oe_costmodel_budget_modification"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_costmodel_budget_modification_code"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft", server_default="draft")
    cost_line_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_costmodel_cost_line.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    approval_ref: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    requested_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")


class BudgetLedgerAudit(Base):
    """Append-only history of every step on a transfer or a modification."""

    __tablename__ = "oe_costmodel_budget_ledger_audit"
    __table_args__ = (Index("ix_costmodel_budget_audit_entity", "entity_kind", "entity_id"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    entity_kind: Mapped[str] = mapped_column(String(12), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    from_status: Mapped[str] = mapped_column(String(12), nullable=False, default="", server_default="")
    to_status: Mapped[str] = mapped_column(String(12), nullable=False, default="", server_default="")
    actor: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
