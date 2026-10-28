# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Payroll ORM models.

Tables:
    oe_payroll_batch      - one draft/approved pay run per (project, period)
    oe_payroll_entry      - one payslip line per (worker, date):
                            hours x rate = gross, gross - deductions = net
    oe_payroll_deduction  - one withholding line on a payslip (entry):
                            a labelled tax / social / pension / other amount,
                            either a fixed sum or a percentage of a base

Money is stored Decimal-as-string (the project convention) and is always
expressed in the project base currency - the generator converts each
source row's native ``hours x cost_rate`` to base via the project fx_rates
before it lands here, so a batch never blends currencies. Deductions are
entered directly in the batch (base) currency, so net pay is a plain Decimal
subtraction with no FX.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_types import SafeDate
from app.database import GUID, Base


class PayrollBatch(Base):
    """A draft pay run aggregating field labour for a project + period.

    A batch is created in ``draft`` status by the generator. Totals
    (``total_hours`` / ``total_amount``) are denormalised sums of the
    batch's entries so the list view needs no per-row aggregation.
    """

    __tablename__ = "oe_payroll_batch"
    __table_args__ = (Index("ix_oe_payroll_batch_project_status", "project_id", "status"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Human label, e.g. "Week 2026-W23" or an explicit date range. Free-form
    # so the generator can name a batch by whatever period it covered.
    period_label: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    # ISO YYYY-MM-DD bounds of the labour aggregated into this batch.
    period_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    period_end: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # draft / submitted / approved / posted - free-form on the DB side; the
    # service FSM is authoritative. New batches always start ``draft``
    # (human-confirmed). The lifecycle is:
    #   draft     -> generated, manager reviews/edits
    #   submitted -> sent for approval (no money moved yet)
    #   approved  -> labour cost posted to the cost-spine budget line
    #   posted    -> approved AND handed to the finance GL (terminal)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
        index=True,
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    total_hours: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    # ``total_amount`` is the batch GROSS pay (sum of entry gross amounts). It
    # is what posts to the cost spine / GL: gross labour cost is the employer's
    # cost, never reduced by employee withholdings.
    total_amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    # Denormalised deduction/net rollups so the list view needs no per-entry
    # aggregation. ``total_net = total_amount - total_deductions``. On a batch
    # with no deductions both stay 0 / equal to gross (backfill-safe).
    total_deductions: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    total_net: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # ── Lifecycle audit (FSM transitions) ────────────────────────────────
    # Each transition stamps its own timestamp + actor so the batch carries a
    # full audit trail. Plain UUIDs (no FK) - the acting user may be archived
    # while the pay history survives.
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Finance ledger transaction reference written when the batch is posted to
    # the GL. NULL until the batch reaches ``posted``; the value doubles as the
    # idempotency guard so a re-post never writes a second journal.
    gl_transaction_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<PayrollBatch {self.period_label} ({self.status}) {self.total_amount}>"


class PayrollEntry(Base):
    """A single payslip line: one worker, one date, hours x rate = gross.

    ``rate``, ``amount`` (gross) and ``net_amount`` are in the batch currency
    (project base). The ``resource_id`` link is optional - free-text
    ``worker_type`` rows (e.g. "carpenter" with no resource record) still
    produce an entry using whatever rate the source row carried.

    ``net_amount = amount - sum(deductions)``. An entry with no deduction rows
    has ``net_amount == amount`` (backfill-safe): the generator stamps net to
    gross on insert, and the service recomputes it whenever a deduction line is
    added or removed.
    """

    __tablename__ = "oe_payroll_entry"
    __table_args__ = (Index("ix_oe_payroll_entry_batch_date", "batch_id", "work_date"),)

    batch_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_payroll_batch.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional link to a resource record (person/crew). Plain UUID, no FK -
    # the resource may be archived while the pay history survives.
    resource_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    worker: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    work_date: Mapped[str | None] = mapped_column(String(20), nullable=True, doc="ISO YYYY-MM-DD")
    hours: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    rate: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    # ``amount`` is the GROSS pay for this line (hours x rate, in base).
    amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    # Net pay = gross - sum(deductions). Defaults to the gross amount so a row
    # with no deductions (legacy or freshly generated) already reads net=gross.
    net_amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    source: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="fieldreport",
        server_default="fieldreport",
        doc="fieldreport | field_diary",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<PayrollEntry {self.worker} {self.work_date} {self.hours}h={self.amount}>"


class PayrollDeduction(Base):
    """A single withholding line on a payslip (one :class:`PayrollEntry`).

    Deductions are user/admin-entered, configurable line items - the platform
    does NOT ship any country's tax tables or statutory rates. Each line carries
    a free-form ``label`` (e.g. "Income tax"), a coarse ``deduction_type`` used
    only for grouping/colour (tax / social / pension / other), and a value that
    is resolved to a concrete ``amount`` in the batch (base) currency:

        * ``mode == "fixed"``       -> ``amount = value`` (value is the sum).
        * ``mode == "percentage"``  -> ``amount = round(base * value / 100)``;
          ``base`` defaults to the parent entry's gross when left blank.

    ``amount`` is the resolved, quantized figure the service computes and stores
    so reads never re-evaluate the formula. All money is Decimal-as-string.
    """

    __tablename__ = "oe_payroll_deduction"
    __table_args__ = (Index("ix_oe_payroll_deduction_entry_ordinal", "entry_id", "ordinal"),)

    entry_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_payroll_entry.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Free-form human label, e.g. "Income tax", "Pension 5%". Required.
    label: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    # Coarse bucket for grouping / display only (NOT a tax rule):
    # tax | social | pension | other. Free-form on the DB side.
    deduction_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="other",
        server_default="other",
        doc="tax | social | pension | other",
    )
    # How ``value`` is interpreted: ``fixed`` (an absolute sum) or
    # ``percentage`` (a percent of ``base_amount``).
    mode: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        default="fixed",
        server_default="fixed",
        doc="fixed | percentage",
    )
    # The user-entered figure: a fixed amount when ``mode='fixed'``, or a
    # percentage (e.g. "5" meaning 5%) when ``mode='percentage'``.
    value: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    # The base a percentage applies to (batch currency). Stored so the resolved
    # amount is reproducible/auditable even if the entry gross later changes.
    # Empty/0 for fixed deductions; defaults to the entry gross for percentages.
    base_amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    # The resolved, quantized deduction amount in the batch (base) currency.
    amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    # Display/calc order within the payslip (also the deduction sequence).
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<PayrollDeduction {self.label} ({self.deduction_type}) {self.amount}>"


class PayrollPeriod(Base):
    """A payroll export period over approved field timesheets of one project.

    ``open`` -> ``locked`` (timesheet edits in the date range are blocked) ->
    ``exported``. A locked or exported period can be reopened with a reason; every
    move is a :class:`PayrollPeriodEvent`. ``rule_profile`` names the overtime and
    allowance profile in ``country_data/payroll_rules.json``.
    """

    __tablename__ = "oe_payroll_period"
    __table_args__ = (Index("ix_oe_payroll_period_project_dates", "project_id", "period_start", "period_end"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    period_start: Mapped[date] = mapped_column(SafeDate(), nullable=False)
    period_end: Mapped[date] = mapped_column(SafeDate(), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="", server_default="")
    rule_profile: Mapped[str] = mapped_column(String(60), nullable=False, default="neutral", server_default="neutral")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", server_default="open", index=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    total_hours: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    total_gross: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    total_burden: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class PayrollPeriodLine(Base):
    """One export line: employee x day x cost code x pay type, hours x rate x multiplier."""

    __tablename__ = "oe_payroll_period_line"
    __table_args__ = (Index("ix_oe_payroll_period_line_period_emp", "period_id", "employee_id"),)

    period_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_payroll_period.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    employee_number: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")
    employee_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    work_date: Mapped[date] = mapped_column(SafeDate(), nullable=False)
    cost_code: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    pay_type: Mapped[str] = mapped_column(String(30), nullable=False, default="regular", server_default="regular")
    hours: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"), server_default="0")
    rate: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"), server_default="0")
    multiplier: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("1"), server_default="1")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    overtime_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    source_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")  # type: ignore[assignment]


class PayrollPeriodEvent(Base):
    """Audit of a period: build, lock, reopen (with the reason), export, post."""

    __tablename__ = "oe_payroll_period_event"

    period_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_payroll_period.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    actor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")  # type: ignore[assignment]
