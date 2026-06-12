"""‌⁠‍5D Cost Model ORM models.

Tables:
    oe_costmodel_snapshot - monthly EVM snapshots (planned, earned, actual)
    oe_costmodel_budget_line - budget tracking per BOQ position or category
    oe_costmodel_cash_flow - monthly cash flow entries
    oe_costmodel_control_account - Cost Spine control accounts (CBS tree)
    oe_costmodel_cost_line - Cost Spine cost lines (one row per scope item)
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
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


class CostSnapshot(Base):
    """‌⁠‍Monthly cost snapshot for earned value analysis (EVM).

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
    period: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        doc=(
            "YYYY-MM for regular monthly snapshots. What-if scenarios use a "
            "prefixed key like 'wif:<short-id>:YYYY-MM' so they cannot "
            "collide with the (project_id, period) unique index that pins "
            "real monthly snapshots (R5 audit, May 2026)."
        ),
    )
    planned_cost: Mapped[str] = mapped_column(
        String(50), nullable=False, default="0", doc="BCWS - Budgeted Cost of Work Scheduled"
    )
    earned_value: Mapped[str] = mapped_column(
        String(50), nullable=False, default="0", doc="BCWP - Budgeted Cost of Work Performed"
    )
    actual_cost: Mapped[str] = mapped_column(
        String(50), nullable=False, default="0", doc="ACWP - Actual Cost of Work Performed"
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
    """‌⁠‍Budget tracking per BOQ position or cost category.

    Links planned budgets to committed contracts, actual invoices,
    and forecast amounts. Optionally tied to a BOQ position or 4D activity.
    """

    __tablename__ = "oe_costmodel_budget_line"
    __table_args__ = (
        # Partial index for the overrun-alert sweep (Gap D): only rows with a
        # threshold actually armed (> '0') are interesting, so the index stays
        # tiny on projects that never opt in. PostgreSQL string-compares the
        # VARCHAR threshold; '0' is the disabled sentinel.
        Index(
            "ix_costmodel_budget_line_overrun_alert",
            "project_id",
            "overrun_alerted_at",
            postgresql_where="overrun_alert_threshold_pct > '0'",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, doc="Link to 4D schedule activity")
    # ── Cost Spine linkage (v6.4) ────────────────────────────────────────
    # Additive nullable links to the cost spine. ``cost_line_id`` ties this
    # budget row to its CostLine; ``control_account_id`` mirrors the cost
    # line's account so account-level rollups can group budget without a
    # second join. Both stay NULL on legacy rows written before the spine.
    cost_line_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    control_account_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
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
    # EVM earned value (BCWP) for the line: position total x latest progress
    # percent. Maintained by the progress module on every recorded entry
    # (latest reading wins, never accumulated). NULL means no progress has
    # been recorded for the linked BOQ position yet. Numeric (not VARCHAR)
    # because it is a derived figure that EVM rollups aggregate in SQL;
    # Decimal end-to-end so money is never a float.
    earned_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4),
        nullable=True,
        default=None,
        doc="BCWP - position total x latest percent_complete / 100 (NULL = no progress yet)",
    )
    period_start: Mapped[str | None] = mapped_column(String(20), nullable=True, doc="ISO date start")
    period_end: Mapped[str | None] = mapped_column(String(20), nullable=True, doc="ISO date end")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", doc="From project settings")
    # ── Cost-overrun alerts (Gap D) ──────────────────────────────────────
    # ``overrun_alert_threshold_pct`` is the percentage above ``planned_amount``
    # at which an in-app alert fires; ``'0'`` (the default) disables alerting on
    # the line. Stored as a string for the same reason money is: the column
    # vocabulary stays uniform and PostgreSQL string-comparison ('> 0') powers
    # the partial index above. ``overrun_alerted_at`` records the last time an
    # alert was sent so the subscriber can enforce a 24h cooldown (idempotent
    # re-notification). NULL means "never alerted".
    overrun_alert_threshold_pct: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="0",
        server_default="0",
        doc="% above planned that triggers an alert; '0' disables (Gap D)",
    )
    overrun_alerted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        doc="Timestamp of the last overrun alert sent for this line (24h cooldown anchor)",
    )
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
    period: Mapped[str] = mapped_column(String(20), nullable=False, doc="YYYY-MM format or sentinel bucket")
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


# ── Cost Spine (v6.4) ─────────────────────────────────────────────────────────


class ControlAccount(Base):
    """‌⁠‍A control account in the project Cost Breakdown Structure (CBS).

    Control accounts form a tree (``parent_id`` self-reference) that mirrors
    the chosen classification standard (DIN 276 cost groups, NRM elements,
    MasterFormat divisions, ...). Cost lines hang off the leaves. The account
    code is unique within a project so the spine generator can upsert
    accounts idempotently while building the tree from BOQ classifications.
    """

    __tablename__ = "oe_costmodel_control_account"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_costmodel_ctrl_acct_project_code"),
        Index("ix_costmodel_ctrl_acct_project_parent", "project_id", "parent_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_costmodel_control_account.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    classification_standard: Mapped[str] = mapped_column(String(40), nullable=False, server_default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="open", index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ControlAccount {self.code} ({self.name})>"


class CostLine(Base):
    """‌⁠‍A single cost line in the Cost Spine - the canonical scope item.

    Each cost line is the single source of truth a BOQ position, budget line,
    purchase-order item, contract line, and RFQ all point at, so estimate,
    budget, committed, actual and claimed money roll up against one row. A
    cost line may originate from the BOQ (``source='boq'`` with
    ``boq_position_id`` / ``boq_id`` set) or be entered manually. ``code`` is
    unique within a project so generation can upsert deterministically.
    """

    __tablename__ = "oe_costmodel_cost_line"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_costmodel_cost_line_project_code"),
        Index("ix_costmodel_cost_line_proj_acct", "project_id", "control_account_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    control_account_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_costmodel_control_account.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, server_default="manual", index=True)
    # Plain UUID (no FK) - the originating BOQ position may be deleted while
    # the cost line and its committed/actual history survive.
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    boq_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    estimate_quantity: Mapped[str] = mapped_column(String(50), nullable=False, server_default="0")
    estimate_unit_rate: Mapped[str] = mapped_column(String(50), nullable=False, server_default="0")
    estimate_amount: Mapped[str] = mapped_column(String(50), nullable=False, server_default="0")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, server_default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="active", index=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CostLine {self.code} ({self.source})>"
