# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Full EVM ORM models.

Tables:
    oe_evm_forecast             - forecast rows derived from a finance EVM snapshot
    oe_full_evm_baseline        - the approved performance measurement baseline
    oe_full_evm_baseline_period - the cumulative planned-value curve of a baseline
    oe_full_evm_measure         - one measurement date with the full EVM metric set

Two generations live here on purpose.

``oe_evm_forecast`` is the original surface. It stores every amount as a
``String`` because the finance ``EVMSnapshot`` it reads from does, and its rows
carry a ``tcpi='inf'`` text sentinel. It is still written by the alerting batch
job, so its shape is preserved exactly rather than migrated under running code.

The baseline / period / measure tables are the register proper. They store
money as ``Numeric(18, 4)`` and dimensionless indices as nullable
``Numeric(12, 6)`` where **NULL means the index is undefined** - a zero
denominator, which is the normal state of a project that has not spent
anything yet. No infinity sentinel exists on this generation: an undefined
index is NULL, and the API renders it as ``null``.

Money as ``Numeric`` (never float, never a lossy text round-trip) follows the
newer convention in this codebase, e.g. ``oe_cost_match_result.suggested_rate``.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base

# ── Enum value constants ────────────────────────────────────────────────────
#
# Persisted as plain strings so the schema stays portable and a new value never
# needs an ALTER TYPE. The Pydantic schemas and the validation rules enforce the
# closed set; the column itself is deliberately permissive.

#: Lifecycle of a performance measurement baseline.
BASELINE_STATUSES: tuple[str, ...] = ("draft", "approved", "superseded", "archived")

#: Where a measurement's observations came from.
MEASURE_SOURCES: tuple[str, ...] = ("manual", "finance_snapshot", "import")

#: Outcome of the last validation run stored on a row.
#:
#: Every member except ``pending`` is a value of
#: ``app.core.validation.engine.ValidationStatus``, because the write is
#: ``row.validation_status = report.status.value`` and the engine decides that
#: word, not this module. ``pending`` is the column default, meaning the row has
#: never been validated, which is a state the engine has no name for.
#: ``unsupported`` is the engine's answer when the ``full_evm`` rule set
#: resolves to no rules at all, so it is exactly what lands here if the
#: ``on_startup`` registration is ever lost, and it was missing from this tuple.
#: Nothing reads the tuple today, which is why the omission went unnoticed: no
#: write was refused, the module simply described its own column wrongly. The
#: three sibling vocabularies here are each pinned to a ``Literal`` by
#: ``schemas._check_vocabulary``; this one is not, so
#: ``test_full_evm_vocabulary.py`` pins it to the engine's enum instead.
VALIDATION_STATUSES: tuple[str, ...] = (
    "pending",
    "passed",
    "warnings",
    "errors",
    "info",
    "skipped",
    "unsupported",
)

#: Precision of every money column in this module: 18 digits, 4 decimals. Four
#: decimals covers every ISO 4217 minor-unit count with room to spare, so a
#: three-decimal currency is exact rather than pre-rounded by the column.
_MONEY = Numeric(18, 4)

#: Precision of every dimensionless index column (CPI, SPI, TCPI, percentages).
_RATIO = Numeric(12, 6)


class EVMForecast(Base):
    """Advanced EVM forecast with ETC, EAC, VAC, and TCPI metrics.

    Legacy text-amount surface, written by the alerting batch job from a
    finance ``EVMSnapshot``. New work belongs on :class:`EVMMeasure`; this
    model is kept byte-compatible so running installations and the predictive
    alert flow are not disturbed.
    """

    __tablename__ = "oe_evm_forecast"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    forecast_date: Mapped[str] = mapped_column(String(40), nullable=False)
    etc_: Mapped[str] = mapped_column(
        "etc",
        String(50),
        nullable=False,
        default="0",
    )
    eac: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    vac: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    tcpi: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    forecast_method: Mapped[str] = mapped_column(String(50), nullable=False, default="cpi")
    confidence_range_low: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence_range_high: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ── Predictive alert tracking (TOP-30 #19) ──────────────────────────────
    # When a forecast breaches a project AlertRule the batch job stamps
    # ``alert_status='triggered'`` + ``triggered_at`` and emits
    # ``forecast.alert_triggered``. Users then move it to ``acknowledged`` or
    # ``snoozed`` from the Forecasts tab. NULL means "no alert on this row".
    alert_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<EVMForecast project={self.project_id} date={self.forecast_date}>"


class EVMBaseline(Base):
    """Performance measurement baseline: the budget the project is measured against.

    A baseline pins three things that every EVM number depends on: the total
    approved budget (``bac``), the currency the amounts are expressed in, and
    the cumulative planned-value curve (:attr:`periods`). Without a curve there
    is no Planned Value, and without Planned Value there is no schedule
    performance - which is why the periods are eager-loaded: a baseline read
    that omits them is never what a caller wanted.

    A project may hold several baselines (the original plus re-baselines after
    approved change), but only one is ``approved`` at a time. Approving a new
    one moves the previous ``approved`` row to ``superseded``; that invariant is
    enforced by the service, not by a partial unique index, so history stays
    readable and re-baselining never needs a destructive write.
    """

    __tablename__ = "oe_full_evm_baseline"
    __table_args__ = (
        Index("ix_full_evm_baseline_project_status", "project_id", "status"),
        UniqueConstraint("project_id", "name", name="uq_full_evm_baseline_project_name"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="draft",
        server_default="draft",
        doc="One of: draft, approved, superseded, archived",
    )
    bac: Mapped[Decimal] = mapped_column(
        _MONEY,
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        doc="Budget At Completion - the total approved budget for the scope",
    )
    currency: Mapped[str | None] = mapped_column(
        String(3),
        nullable=True,
        doc="ISO 4217 code used purely as a label; no currency is ever assumed",
    )
    minor_units: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=2,
        server_default="2",
        doc="Decimal places the currency uses; the money rounding step is 10**-minor_units",
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    finish_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Outcome of the last ``full_evm`` rule-set run over this baseline. Stored
    # on the row so a list view shows whether a plan is sound without re-running
    # the engine per item.
    validation_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
        doc="One of VALIDATION_STATUSES",
    )
    validation_findings: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
        doc="Failing rule results from the last validation run",
    )
    validation_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        default=None,
        doc=(
            "Severity-weighted quality score from the last validation. Nullable on "
            "purpose: the engine returns None when nothing was checked, and storing "
            "1.0 there would report an unchecked baseline as perfect."
        ),
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # The curve IS the baseline - a read without it cannot produce a PV.
    periods: Mapped[list["EVMBaselinePeriod"]] = relationship(
        back_populates="baseline",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="EVMBaselinePeriod.ordinal",
    )
    # Measurements grow without bound over a project's life, and the common
    # read is "the latest one" or a paginated page. Forcing the caller to ask
    # explicitly beats loading years of history to render a header.
    measures: Mapped[list["EVMMeasure"]] = relationship(
        back_populates="baseline",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
        order_by="EVMMeasure.data_date",
    )

    def __repr__(self) -> str:
        return f"<EVMBaseline {self.name} project={self.project_id} status={self.status}>"


class EVMBaselinePeriod(Base):
    """One point on a baseline's cumulative planned-value curve.

    ``planned_value`` is **cumulative to** ``period_end``, not the amount
    planned within the period. Cumulative is what an S-curve plots, what the
    Planned Value at a data date is read from, and what makes the monotonicity
    rule (``full_evm.baseline_pv_monotonic``) meaningful: a cumulative total
    that goes down is always a data fault.

    ``planned_quantity`` carries the physical measure alongside the money so
    progress can be cross-checked against installed quantity rather than spend
    alone. Comparison in this module is limited to cost and quantity.
    """

    __tablename__ = "oe_full_evm_baseline_period"
    __table_args__ = (
        UniqueConstraint("baseline_id", "ordinal", name="uq_full_evm_period_baseline_ordinal"),
        UniqueConstraint("baseline_id", "period_end", name="uq_full_evm_period_baseline_end"),
        Index("ix_full_evm_period_baseline_end", "baseline_id", "period_end"),
    )

    baseline_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_full_evm_baseline.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        doc="Position in the curve, renumbered 0..n-1 on every whole-curve write",
    )
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    label: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        server_default="",
        doc="Free-form period name, e.g. '2026-M04' or 'Q2'",
    )
    planned_value: Mapped[Decimal] = mapped_column(
        _MONEY,
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        doc="Cumulative Planned Value at period_end",
    )
    planned_quantity: Mapped[Decimal | None] = mapped_column(
        _MONEY,
        nullable=True,
        doc="Cumulative planned physical quantity at period_end, in the baseline's unit",
    )

    # The foreign key is already in the column; an implicit walk upwards from a
    # child row is exactly what fires MissingGreenlet in an async session.
    baseline: Mapped[EVMBaseline] = relationship(back_populates="periods", lazy="raise_on_sql")

    def __repr__(self) -> str:
        return f"<EVMBaselinePeriod baseline={self.baseline_id} end={self.period_end} pv={self.planned_value}>"


class EVMMeasure(Base):
    """The full EVM metric set for one project at one data date.

    Holds both the observations (PV / EV / AC, plus the BAC in force at the
    time) and everything derived from them. The derived values are persisted
    rather than recomputed on read for two reasons: a measurement is a
    historical fact that must not change when a baseline is later re-approved,
    and reporting reads these columns in aggregate.

    Every index column is nullable, and NULL means **undefined** rather than
    zero. ``CPI`` is undefined until money has been spent, ``SPI`` until work
    has been scheduled, ``TCPI`` once the budget is exactly consumed. Storing 0
    for those would report a project that has not started as maximally
    inefficient.

    ``eac_method`` records what the caller asked for and ``eac_method_effective``
    what the maths could actually deliver. They differ whenever a named formula
    is undefined for the data - most often on an early project where nothing has
    been earned yet - and keeping both is what stops the register from claiming
    a cost-trend forecast it never computed.
    """

    __tablename__ = "oe_full_evm_measure"
    __table_args__ = (
        UniqueConstraint("baseline_id", "data_date", name="uq_full_evm_measure_baseline_date"),
        Index("ix_full_evm_measure_project_date", "project_id", "data_date"),
    )

    baseline_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_full_evm_baseline.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
        doc="Denormalised from the baseline so project scoping never needs a join",
    )
    data_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        doc="The cutoff the observations describe - EVM's 'as of' date",
    )
    source: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="manual",
        server_default="manual",
        doc="One of: manual, finance_snapshot, import",
    )
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)

    # ── Observations ────────────────────────────────────────────────────────
    bac: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0"), server_default="0")
    pv: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0"), server_default="0")
    ev: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0"), server_default="0")
    ac: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0"), server_default="0")
    planned_quantity: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    actual_quantity: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)

    # ── Performance to date ─────────────────────────────────────────────────
    sv: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0"), server_default="0")
    cv: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0"), server_default="0")
    spi: Mapped[Decimal | None] = mapped_column(_RATIO, nullable=True, doc="EV/PV; NULL when PV is zero")
    cpi: Mapped[Decimal | None] = mapped_column(_RATIO, nullable=True, doc="EV/AC; NULL when AC is zero")
    percent_complete: Mapped[Decimal | None] = mapped_column(
        _RATIO,
        nullable=True,
        doc="EV/BAC as a fraction; NULL when BAC is zero",
    )
    percent_spent: Mapped[Decimal | None] = mapped_column(
        _RATIO,
        nullable=True,
        doc="AC/BAC as a fraction; NULL when BAC is zero",
    )

    # ── Forecast ────────────────────────────────────────────────────────────
    eac_method: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="auto",
        server_default="auto",
        doc="EAC formula requested by the caller: auto, remaining, cpi or combined",
    )
    eac_method_effective: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="remaining",
        server_default="remaining",
        doc="EAC formula that actually produced the stored value",
    )
    eac: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    etc_: Mapped[Decimal | None] = mapped_column("etc", _MONEY, nullable=True)
    vac: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    tcpi_bac: Mapped[Decimal | None] = mapped_column(
        _RATIO,
        nullable=True,
        doc="(BAC-EV)/(BAC-AC); NULL when the budget is exactly consumed",
    )
    tcpi_eac: Mapped[Decimal | None] = mapped_column(
        _RATIO,
        nullable=True,
        doc="(BAC-EV)/(EAC-AC); NULL when no further spend is forecast",
    )
    eac_variants: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
        doc="Every EAC formula side by side as strings, so the chosen one is auditable",
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    validation_findings: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    validation_score: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    baseline: Mapped[EVMBaseline] = relationship(back_populates="measures", lazy="raise_on_sql")

    def __repr__(self) -> str:
        return f"<EVMMeasure project={self.project_id} date={self.data_date} cpi={self.cpi}>"


__all__ = [
    "BASELINE_STATUSES",
    "MEASURE_SOURCES",
    "VALIDATION_STATUSES",
    "EVMBaseline",
    "EVMBaselinePeriod",
    "EVMForecast",
    "EVMMeasure",
]
