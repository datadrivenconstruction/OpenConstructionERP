"""5D Cost Model ORM models.

Tables:
    oe_costmodel_snapshot — monthly EVM snapshots (planned, earned, actual)
    oe_costmodel_budget_line — budget tracking per BOQ position or category
    oe_costmodel_cash_flow — monthly cash flow entries
"""

import uuid

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class CostSnapshot(Base):
    """Monthly cost snapshot for earned value analysis (EVM).

    Stores BCWS (planned), BCWP (earned), and ACWP (actual) per period,
    along with derived performance indices (SPI, CPI) and forecast EAC.
    """

    __tablename__ = "oe_costmodel_snapshot"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period: Mapped[str] = mapped_column(String(10), nullable=False, doc="YYYY-MM format, e.g. '2026-04'")
    planned_cost: Mapped[str] = mapped_column(
        String(50), nullable=False, default="0", doc="BCWS — Budgeted Cost of Work Scheduled"
    )
    earned_value: Mapped[str] = mapped_column(
        String(50), nullable=False, default="0", doc="BCWP — Budgeted Cost of Work Performed"
    )
    actual_cost: Mapped[str] = mapped_column(
        String(50), nullable=False, default="0", doc="ACWP — Actual Cost of Work Performed"
    )
    forecast_eac: Mapped[str] = mapped_column(String(50), nullable=False, default="0", doc="Estimate At Completion")
    spi: Mapped[str] = mapped_column(String(10), nullable=False, default="0", doc="Schedule Performance Index")
    cpi: Mapped[str] = mapped_column(String(10), nullable=False, default="0", doc="Cost Performance Index")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CostSnapshot project={self.project_id} period={self.period}>"


class BudgetLine(Base):
    """Budget tracking per BOQ position or cost category.

    Links planned budgets to committed contracts, actual invoices,
    and forecast amounts. Optionally tied to a BOQ position or 4D activity.
    """

    __tablename__ = "oe_costmodel_budget_line"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, doc="Link to 4D schedule activity")
    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        doc="material, labor, equipment, subcontractor, overhead, contingency",
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    planned_amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    committed_amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0", doc="Contracts signed")
    actual_amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0", doc="Invoices paid")
    forecast_amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    period_start: Mapped[str | None] = mapped_column(String(20), nullable=True, doc="ISO date start")
    period_end: Mapped[str | None] = mapped_column(String(20), nullable=True, doc="ISO date end")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", doc="From project settings")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<BudgetLine {self.category} planned={self.planned_amount}>"


class CashFlow(Base):
    """Monthly cash flow entry.

    Tracks planned and actual inflows/outflows per period,
    with running cumulative totals for S-curve visualisation.
    """

    __tablename__ = "oe_costmodel_cash_flow"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period: Mapped[str] = mapped_column(String(10), nullable=False, doc="YYYY-MM format")
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="total")
    planned_inflow: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    planned_outflow: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    actual_inflow: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    actual_outflow: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    cumulative_planned: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    cumulative_actual: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CashFlow project={self.project_id} period={self.period}>"
