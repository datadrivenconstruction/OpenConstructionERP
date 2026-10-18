# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""5D Cost Model ORM models.

Tables:
    oe_costmodel_snapshot - monthly EVM snapshots (planned, earned, actual)
    oe_costmodel_budget_line - budget tracking per BOQ position or category
    oe_costmodel_cash_flow - monthly cash flow entries
    oe_costmodel_control_account - Cost Spine control accounts (CBS tree)
    oe_costmodel_cost_line - Cost Spine cost lines (one row per scope item)
    oe_costmodel_labour_worker_day - one worker-day, claimed by the source that
        costed it first, so a day recorded on a phone and again on the desktop
        timesheet reaches the budget once
    oe_costmodel_forecast_snapshot - a frozen cost control report, optionally
        tagged with the cost stage it records (estimate, award, final, ...)
    oe_costmodel_forecast_override - a person's forecast for one cost line,
        with the reason; append-only, the newest open row is the one in force
    oe_costmodel_code_list - a code list a user imported for one project, the
        dictionary a custom cost structure is built from
    oe_costmodel_position_allocation - one share of a bill position on a cost
        line, when the position is split over more than one
    oe_costmodel_line_allocation - one share of a downstream line (bid line,
        contract line, order item, invoice line) on a cost line, inherited from
        the split position it came from
    oe_costmodel_cost_control_settings - a project's forecast method and the
        threshold above which a forecast move needs evidence
    oe_costmodel_forecast_method - the forecast method one cost line is read
        with when it differs from the project's, and why
    oe_costmodel_forecast_snapshot_note - the comment and evidence behind one
        line of a snapshot; written while the snapshot is a draft, frozen with it
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_types import MoneyType
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
    """Budget tracking per BOQ position or cost category.

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
    """A control account in the project Cost Breakdown Structure (CBS).

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
    # The label shown next to the code. Kept for every reader written before
    # ``title`` existed; it carries the title when there is one, else the code.
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # The account's own title, separate from its code. Empty when the code list
    # the account came from has no title for it (a code deeper than the list).
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # Depth in the tree, 1 at the top. Maintained on every write; readers that
    # need certainty recompute it from ``parent_id``.
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # Money planned on the account itself and not broken down into its
    # children or cost lines yet. ``total = own + posted + sum(children)``.
    own_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"), server_default="0")
    # Whether cost lines may be posted onto this account. A pure grouping node
    # is switched off, and money posted on it anyway is held in suspense.
    is_leaf_postable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
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
    """A single cost line in the Cost Spine - the canonical scope item.

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


class LabourWorkerDay(Base):
    """One worker's day, claimed by whichever source costed it first.

    The same day's work reaches this module from two places. A foreman punches
    the crew in and out on a phone, and that diary entry publishes its hours on
    approval. Somebody in the office fills in the desktop timesheet for the same
    site and the same day, and that publishes too. Both are honest records of
    the same eight hours, and without a row like this both land on the budget
    line and the project reads as having paid twice.

    The claim is per project, per calendar day, per worker, because that is the
    grain a person can actually check: "was Marta costed twice on the 4th" is
    answerable, "was report X costed twice" is not - the two reports have
    different ids by construction.

    A row with no ``resource_id`` cannot be claimed and is not represented here.
    Those hours are costed as they arrive and reconciled by hand, which is why
    the phone now asks the foreman to pick a person rather than type a name.
    """

    __tablename__ = "oe_costmodel_labour_worker_day"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "work_date",
            "resource_id",
            name="uq_oe_costmodel_labour_worker_day",
        ),
        Index("ix_oe_costmodel_labour_worker_day_project_date", "project_id", "work_date"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    # ISO YYYY-MM-DD, the same string the diary entry and the timesheet carry.
    work_date: Mapped[str] = mapped_column(String(10), nullable=False)
    # Stored as text, not a FK: the labour event carries whatever key its source
    # had, and a claim must survive the resource row being deleted - otherwise
    # deleting a leaver would silently reopen every day they ever worked.
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Which module got here first, and the document it came from, so an approver
    # reading a skipped-hours warning can go and look at the other record.
    source_module: Mapped[str] = mapped_column(String(40), nullable=False, server_default="")
    source_ref: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    hours: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0")

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<LabourWorkerDay {self.work_date} r={self.resource_id} from {self.source_module}>"


class CostForecastSnapshot(Base):
    """A cost control report kept at a date.

    Taken by hand ("save this month's forecast") or tagged with the cost stage
    it records, so the same table holds the estimate, the award and every
    monthly forecast in between, and the history of a line is read straight
    from it. ``rows`` keeps one entry per cost line with the figures and the
    forecast source as they stood; money is stored as decimal strings.

    A snapshot starts as a ``draft``: its figures can be refreshed and each
    line documented (:class:`CostForecastSnapshotNote`). Freezing it is final:
    a ``frozen`` snapshot is never changed or deleted again, which the service
    refuses and the mapper events at the end of this module refuse as well.
    Snapshots written before drafts existed are frozen.
    ``previous_snapshot_id`` names the frozen snapshot its moves are measured
    from; ``meta`` keeps the forecast method and evidence threshold in force.
    """

    __tablename__ = "oe_costmodel_forecast_snapshot"
    __table_args__ = (Index("ix_costmodel_forecast_snapshot_proj_date", "project_id", "taken_on"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    taken_on: Mapped[str] = mapped_column(String(10), nullable=False, doc="ISO date the figures stood on")
    stage: Mapped[str] = mapped_column(String(30), nullable=False, server_default="forecast")
    label: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, server_default="")
    totals: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    rows: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="frozen", server_default="frozen")
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frozen_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # The frozen snapshot this one's moves are measured from; no foreign key, a frozen row is never deleted.
    previous_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    meta: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CostForecastSnapshot {self.taken_on} {self.stage} {self.status}>"


class CostForecastOverride(Base):
    """A person's forecast for one cost line, and why.

    Append-only. Setting a new forecast closes the open row (``closed_at``)
    and adds a new one; clearing closes the open row and adds nothing, so the
    line goes back to the automatic forecast and the history still shows who
    said what, when and on which document.
    """

    __tablename__ = "oe_costmodel_forecast_override"
    __table_args__ = (
        Index("ix_costmodel_forecast_override_line_open", "cost_line_id", "closed_at"),
        # One open manual forecast per line: two concurrent saves cannot both stay open.
        Index(
            "uq_costmodel_forecast_override_open",
            "cost_line_id",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
            sqlite_where=text("closed_at IS NULL"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cost_line_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_costmodel_cost_line.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    # Deleting the document clears the link; the reason and the typed reference stay.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_documents_document.id", ondelete="SET NULL", name="fk_costmodel_forecast_override_document"),
        nullable=True,
    )
    document_ref: Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<CostForecastOverride {self.cost_line_id} {self.amount}>"


class CostCodeList(Base):
    """A code list a user imported for one project.

    The shipped lists and those of the active pack are read from files by
    :mod:`app.core.code_lists`; a list a company keeps for itself is uploaded
    as CSV or Excel and stored here, validated, in tree order. ``key`` is what
    an account's ``classification_standard`` and a position's classification
    name it by, unique within the project.
    """

    __tablename__ = "oe_costmodel_code_list"
    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_costmodel_code_list_project_key"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # ``[{"code", "title", "parent", "level"}]`` in tree order.
    entries: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")  # type: ignore[assignment]
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<CostCodeList {self.key} ({len(self.entries or [])} codes)>"


class PositionAllocation(Base):
    """One share of a bill position on a cost line: the position's vector, split.

    A position on a single cost line needs no row here: ``Position.cost_line_id``
    is that link, and every reader written before splits existed keeps reading
    it. A position split over several cost lines has one row per line, and its
    ``cost_line_id`` names the line with the largest share, so those readers
    still find the main line. Shares are percentages adding up to 100 or partial
    quantities adding up to the position's quantity (``mode``), never a mix.

    Rows go with their position and with their cost line; deleting a cost line
    that still carries a share is refused by the service before it gets here.
    """

    __tablename__ = "oe_costmodel_position_allocation"
    __table_args__ = (
        UniqueConstraint("position_id", "cost_line_id", name="uq_costmodel_alloc_position_line"),
        Index("ix_costmodel_alloc_boq", "boq_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    boq_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    position_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_position.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cost_line_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_costmodel_cost_line.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mode: Mapped[str] = mapped_column(String(10), nullable=False, server_default="percent")
    share: Mapped[Decimal] = mapped_column(MoneyType(20, 6), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    def __repr__(self) -> str:
        return f"<PositionAllocation {self.position_id} -> {self.cost_line_id} {self.share} {self.mode}>"


class LineAllocation(Base):
    """One share of a downstream line on a cost line: the inherited, split vector.

    A bill position split over several cost lines (:class:`PositionAllocation`)
    passes that split down the chain: to the bid line made from it, the contract
    line the award writes, the order item, the invoice line. Each of those rows
    keeps its own ``cost_line_id`` pointing at the line with the largest share,
    so every reader written before splits existed still finds the main line, and
    this table holds the whole split once the row has more than one share.

    ``source_type`` names the table the row belongs to (see
    :mod:`app.modules.costmodel.inheritance`), ``source_id`` its id. ``share`` is
    a percentage; the shares of one row add up to 100. A row with one cost line
    has no rows here at all.
    """

    __tablename__ = "oe_costmodel_line_allocation"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "cost_line_id", name="uq_costmodel_line_alloc_source_line"),
        Index("ix_costmodel_line_alloc_source", "source_type", "source_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    cost_line_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_costmodel_cost_line.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    share: Mapped[Decimal] = mapped_column(MoneyType(20, 6), nullable=False)

    def __repr__(self) -> str:
        return f"<LineAllocation {self.source_type}:{self.source_id} -> {self.cost_line_id} {self.share}%>"


class CostControlSettings(Base):
    """How a project's forecast is worked out and documented. One row per project.

    A project without a row reads the defaults: the best available source, and
    evidence for a move above 10 % of the previous forecast.
    """

    __tablename__ = "oe_costmodel_cost_control_settings"
    __table_args__ = (UniqueConstraint("project_id", name="uq_costmodel_cc_settings_project"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE", name="fk_costmodel_cc_settings_project"),
        nullable=False,
        index=True,
    )
    forecast_method: Mapped[str] = mapped_column(String(20), nullable=False, server_default="best_available")
    # A move must exceed the amount (when above zero) and the percentage (when set) to need evidence.
    evidence_threshold_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, server_default="0")
    evidence_threshold_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True, server_default="10")
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<CostControlSettings {self.project_id} {self.forecast_method}>"


class CostForecastMethodChoice(Base):
    """The forecast method one cost line is read with, when someone picked one for it.

    A line without a row follows the project's method. A manual amount is not
    stored here: it is a :class:`CostForecastOverride`, and setting one removes
    the line's choice (and choosing a method closes the open manual amount).
    """

    __tablename__ = "oe_costmodel_forecast_method"
    __table_args__ = (UniqueConstraint("cost_line_id", name="uq_costmodel_forecast_method_line"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE", name="fk_costmodel_forecast_method_project"),
        nullable=False,
        index=True,
    )
    cost_line_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_costmodel_cost_line.id", ondelete="CASCADE", name="fk_costmodel_forecast_method_line"),
        nullable=False,
    )
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<CostForecastMethodChoice {self.cost_line_id} {self.method}>"


class CostForecastSnapshotNote(Base):
    """Why one line of a snapshot moved: a comment and the evidence behind it.

    ``row_key`` is the key the snapshot row carries (a cost line id, or a
    special row such as ``unassigned``). ``evidence`` is a list of
    ``{"kind": "document" | "minutes" | "other", "ref": str, "document_id": str | None}``.
    Written while the snapshot is a draft; frozen with it.
    """

    __tablename__ = "oe_costmodel_forecast_snapshot_note"
    __table_args__ = (UniqueConstraint("snapshot_id", "row_key", name="uq_costmodel_snapshot_note_row"),)

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_costmodel_forecast_snapshot.id", ondelete="CASCADE", name="fk_costmodel_snapshot_note_snapshot"),
        nullable=False,
        index=True,
    )
    row_key: Mapped[str] = mapped_column(String(80), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    evidence: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<CostForecastSnapshotNote {self.snapshot_id} {self.row_key}>"


# ── A frozen snapshot stays as it was ─────────────────────────────────────


class FrozenSnapshotError(RuntimeError):
    """Raised when a write would change a frozen snapshot or its notes."""


def _stored_status(connection: object, snapshot_id: object) -> str | None:
    """The status the database holds for a snapshot, before the write under way."""
    from sqlalchemy import select

    return connection.execute(  # type: ignore[attr-defined]
        select(CostForecastSnapshot.status).where(CostForecastSnapshot.id == snapshot_id)
    ).scalar()


def _refuse_frozen_snapshot_write(_mapper: object, connection: object, target: CostForecastSnapshot) -> None:
    """A frozen snapshot is never updated; freezing a draft is the one write that ends in ``frozen``."""
    if _stored_status(connection, target.id) == "frozen":
        raise FrozenSnapshotError(f"Snapshot {target.id} is frozen and cannot be changed")


def _refuse_frozen_snapshot_delete(_mapper: object, connection: object, target: CostForecastSnapshot) -> None:
    if _stored_status(connection, target.id) == "frozen":
        raise FrozenSnapshotError(f"Snapshot {target.id} is frozen and cannot be deleted")


def _refuse_note_on_frozen(_mapper: object, connection: object, target: CostForecastSnapshotNote) -> None:
    """A note is written, changed or removed only while its snapshot is a draft."""
    if _stored_status(connection, target.snapshot_id) == "frozen":
        raise FrozenSnapshotError(f"Snapshot {target.snapshot_id} is frozen; its notes cannot be changed")


def _install_frozen_guards() -> None:
    from sqlalchemy import event

    event.listen(CostForecastSnapshot, "before_update", _refuse_frozen_snapshot_write)
    event.listen(CostForecastSnapshot, "before_delete", _refuse_frozen_snapshot_delete)
    for name in ("before_insert", "before_update", "before_delete"):
        event.listen(CostForecastSnapshotNote, name, _refuse_note_on_frozen)


_install_frozen_guards()
