# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""WIP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ report ORM models.

Tables:
    oe_wip_report_period   - one month-end close of a project's WIP row: the inputs as
                             the source modules held them at the close date and the
                             figures worked out from them. The only stored WIP figures;
                             the live view is computed on request and never stored.
    oe_wip_report_forecast - the project manager's current estimate at completion, when it
                             differs from the cost report's forecast (one row per project).

Contract value, change orders, cost, forecast and billings stay in their own modules;
a snapshot copies them once, at the close, so a later edit there does not rewrite a
period already reported to a surety or a lender.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_types import SafeDate
from app.database import GUID, Base

_MONEY = Numeric(18, 4)
_PCT = Numeric(9, 4)


class WipPeriod(Base):
    """A closed WIP period (month-end snapshot) of one project."""

    __tablename__ = "oe_wip_report_period"
    __table_args__ = (
        UniqueConstraint("project_id", "period", name="uq_wip_report_project_period"),
        Index("ix_wip_report_period_period", "period"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    as_of: Mapped[date] = mapped_column(SafeDate(), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    original_contract_value: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0"))
    approved_changes: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0"))
    contract_value: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0"))
    estimated_cost: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0"))
    cost_to_date: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0"))
    percent_complete: Mapped[Decimal] = mapped_column(_PCT, nullable=False, default=Decimal("0"))
    earned_revenue: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0"))
    billed_to_date: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0"))
    over_billing: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0"))
    under_billing: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0"))
    projected_gross_profit: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0"))
    previous_gross_profit: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    fade: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    backlog: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0"))
    loss_job: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Where each input came from (cvr report id, forecast override, contract ids), for the audit trail.
    sources: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")  # type: ignore[assignment]
    flags: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")  # type: ignore[assignment]
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class WipForecast(Base):
    """The project manager's estimate at completion, overriding the cost report forecast."""

    __tablename__ = "oe_wip_report_forecast"
    __table_args__ = (UniqueConstraint("project_id", name="uq_wip_report_forecast_project"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    estimated_cost: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
