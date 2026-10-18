# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost control: which number to trust for each cost line, and what to flag.

A project's cost moves through stages: a budget, an estimate, a detailed
estimate, a tender, an award, measured work, a final account. Different parts
of a project sit in different stages at the same time. Once the shell is
awarded the finishes are often still at estimate, so a single "forecast" column
typed in by hand goes stale the day it is written.

This module answers the question per cost line, from data the project already
holds: the forecast is the figure of the most mature stage that has one. A
final account beats measured work, measured work above the award beats the
award, the award (plus approved changes) beats the estimate, and the estimate
beats the budget. A person can still overrule it, but only with a reason, and
the overrule is kept with the reason so the history explains itself.

Everything here is pure: plain values in, plain values out, no session, so the
rules are tested without a database and read the same in the API, the
validation rules and the report.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal

ZERO = Decimal("0")
CENT = Decimal("0.01")

#: Where a line's forecast came from, most mature last. The string values are
#: wire values the frontend translates; never rename one without a migration of
#: the snapshots that stored it.
SOURCE_NONE = "none"
SOURCE_BUDGET = "budget"
SOURCE_ESTIMATE = "estimate"
SOURCE_PARTLY_AWARDED = "partly_awarded"
SOURCE_AWARDED = "awarded"
SOURCE_MEASURED = "measured"
SOURCE_FINAL = "final"
SOURCE_MANUAL = "manual"
# Taken by the "maximum value" method when supplier invoices are the highest figure.
SOURCE_INVOICED = "invoiced"
# Taken by the CPI based method: cost to date projected over the whole line.
SOURCE_EVM = "evm"

FORECAST_SOURCES: tuple[str, ...] = (
    SOURCE_NONE,
    SOURCE_BUDGET,
    SOURCE_ESTIMATE,
    SOURCE_PARTLY_AWARDED,
    SOURCE_AWARDED,
    SOURCE_MEASURED,
    SOURCE_FINAL,
    SOURCE_MANUAL,
    SOURCE_INVOICED,
    SOURCE_EVM,
)

#: How a line's forecast is worked out. A project picks one, a line may pick
#: another. The wire values are stored on settings, lines and snapshots.
#:
#: * ``best_available``: the figure of the most mature stage the line has
#:   (the behaviour cost control always had, and the default).
#: * ``maximum``: the highest figure the line has anywhere, the cautious view
#:   for open contracts.
#: * ``evm_cpi``: cost to date divided by the share of the work done, the earned
#:   value view (budget at completion divided by the cost performance index).
#: * ``manual``: a person's amount with a reason.
METHOD_BEST_AVAILABLE = "best_available"
METHOD_MAXIMUM = "maximum"
METHOD_EVM_CPI = "evm_cpi"
METHOD_MANUAL = "manual"

FORECAST_METHODS: tuple[str, ...] = (METHOD_BEST_AVAILABLE, METHOD_MAXIMUM, METHOD_EVM_CPI, METHOD_MANUAL)

#: Digits a ratio (progress, CPI) is kept and shown with.
RATIO = Decimal("0.0001")

#: Cost stages a snapshot can be tagged with. Neutral names on purpose: the
#: same seven steps exist under every national scheme (DIN 276 Kostenrahmen to
#: Kostenfeststellung, RIBA order of cost estimate to final account, AACE class
#: 5 to class 1), and the interface shows the local name next to the neutral one.
STAGE_BUDGET = "budget"
STAGE_ESTIMATE = "estimate"
STAGE_DETAILED_ESTIMATE = "detailed_estimate"
STAGE_PRE_TENDER = "pre_tender"
STAGE_AWARD = "award"
STAGE_FORECAST = "forecast"
STAGE_FINAL = "final"

COST_STAGES: tuple[str, ...] = (
    STAGE_BUDGET,
    STAGE_ESTIMATE,
    STAGE_DETAILED_ESTIMATE,
    STAGE_PRE_TENDER,
    STAGE_AWARD,
    STAGE_FORECAST,
    STAGE_FINAL,
)

#: Below this share of the planned amount an award reads as "part of the scope
#: is probably still to be let". The data cannot tell which part, so the
#: forecast keeps the plan until at least this share is let, and a finding asks
#: for a person's forecast. Above it the award rules, savings included.
PARTLY_AWARDED_SHARE = Decimal("0.5")

#: A forecast older than this many days is worth refreshing; monthly is the
#: rhythm cost reports are kept at on most projects.
SNAPSHOT_STALE_DAYS = 35


@dataclass(frozen=True, slots=True)
class LineFigures:
    """Every number one cost line has, already in the project currency.

    ``awarded`` is what the contracts and orders were let for, ``changes`` what
    approved change orders and variations added on top. ``certified`` is the
    cumulative value of work certified on claims, ``paid`` the part of it paid.
    ``all_final`` says every contract on the line is completed, so certified
    work is the final cost. ``override`` is a person's forecast, ``None`` when
    nobody overruled the line. ``measured`` (quantity times contract rate) and
    ``invoiced`` (supplier invoices, net) are shown next to certified and do not
    move the forecast.
    """

    budget: Decimal = ZERO
    estimate: Decimal = ZERO
    awarded: Decimal = ZERO
    changes: Decimal = ZERO
    certified: Decimal = ZERO
    paid: Decimal = ZERO
    all_final: bool = False
    override: Decimal | None = None
    measured: Decimal = ZERO
    invoiced: Decimal = ZERO
    #: The forecast method this line is read with (see :data:`FORECAST_METHODS`).
    method: str = METHOD_BEST_AVAILABLE
    #: Change orders on this line still waiting for a decision.
    pending: Decimal = ZERO

    @property
    def owed(self) -> Decimal:
        """What the line is bound to pay or is asked to: the commitment plus undecided changes."""
        return self.committed + self.pending

    @property
    def committed(self) -> Decimal:
        """Awarded plus approved changes: what the project is bound to pay."""
        return self.awarded + self.changes

    @property
    def planned(self) -> Decimal:
        """The yardstick a forecast is judged against: budget, else estimate."""
        return self.budget if self.budget != ZERO else self.estimate


@dataclass(frozen=True, slots=True)
class Forecast:
    """A forecast amount and the stage it was taken from."""

    amount: Decimal
    source: str


def automatic_forecast(figures: LineFigures) -> Forecast:
    """The forecast the data supports, ignoring any manual override.

    Once the line is let, the commitment rules: the final account when every
    contract is completed, measured work when it already runs above the
    commitment, otherwise the commitment. While less than half of the plan is
    let, the rest is most likely still to come, so the plan stands (never less
    than what is already committed). Before any award the estimate, and before
    that the budget.
    """
    committed = figures.committed
    if committed != ZERO or figures.certified != ZERO:
        if figures.all_final:
            return Forecast(figures.certified, SOURCE_FINAL)
        if figures.certified > committed:
            return Forecast(figures.certified, SOURCE_MEASURED)
        planned = figures.planned
        if planned > ZERO and committed < planned * PARTLY_AWARDED_SHARE:
            plan = figures.estimate if figures.estimate != ZERO else figures.budget
            return Forecast(max(plan, committed), SOURCE_PARTLY_AWARDED)
        return Forecast(committed, SOURCE_AWARDED)
    if figures.estimate != ZERO:
        return Forecast(figures.estimate, SOURCE_ESTIMATE)
    if figures.budget != ZERO:
        return Forecast(figures.budget, SOURCE_BUDGET)
    return Forecast(ZERO, SOURCE_NONE)


@dataclass(frozen=True, slots=True)
class MethodOutcome:
    """What one forecast method makes of a line, with the figures it used.

    ``method`` is the method asked for. ``applied`` is False when the method
    had nothing to work with (CPI based with no measured work or no cost yet,
    manual with no amount) and the best available figure stands in. ``progress``,
    ``cpi``, ``earned`` and ``actual`` are filled by the CPI based method only.
    """

    amount: Decimal
    source: str
    method: str
    applied: bool = True
    progress: Decimal | None = None
    cpi: Decimal | None = None
    earned: Decimal | None = None
    actual: Decimal | None = None


#: Sources the "maximum value" method can land on, least mature first: a tie
#: goes to the later one.
_MAXIMUM_ORDER: tuple[str, ...] = (SOURCE_BUDGET, SOURCE_ESTIMATE, SOURCE_AWARDED, SOURCE_MEASURED, SOURCE_INVOICED)


def maximum_forecast(figures: LineFigures) -> Forecast:
    """The highest figure the line has: plan, commitment, measured or certified work, invoices."""
    candidates = (
        (figures.budget, SOURCE_BUDGET),
        (figures.estimate, SOURCE_ESTIMATE),
        (figures.committed, SOURCE_AWARDED),
        (figures.certified, SOURCE_MEASURED),
        (figures.measured, SOURCE_MEASURED),
        (figures.invoiced, SOURCE_INVOICED),
    )
    best = Forecast(ZERO, SOURCE_NONE)
    for amount, source in candidates:
        if amount == ZERO:
            continue
        if (
            best.source == SOURCE_NONE
            or amount > best.amount
            or (amount == best.amount and _MAXIMUM_ORDER.index(source) > _MAXIMUM_ORDER.index(best.source))
        ):
            best = Forecast(amount, source)
    return best


def evm_outcome(figures: LineFigures) -> MethodOutcome | None:
    """The CPI based forecast, or ``None`` when the line has no measured work or no cost yet.

    Earned value is the measured work at contract rates, actual cost the
    supplier invoices (certified work where nothing is invoiced yet). The
    budget at completion is the commitment, or the measured value once the
    work runs past it. CPI = earned / actual, and the forecast is the budget
    at completion divided by CPI, which is the same as actual cost divided by
    the share of the work done.
    """
    earned = figures.measured
    actual = figures.invoiced if figures.invoiced != ZERO else figures.certified
    if earned <= ZERO or actual <= ZERO:
        return None
    at_completion = max(figures.committed, earned)
    amount = (at_completion * actual / earned).quantize(CENT)
    return MethodOutcome(
        amount=amount,
        source=SOURCE_EVM,
        method=METHOD_EVM_CPI,
        progress=(earned / at_completion).quantize(RATIO),
        cpi=(earned / actual).quantize(RATIO),
        earned=earned,
        actual=actual,
    )


def method_outcome(figures: LineFigures, method: str | None = None) -> MethodOutcome:
    """The forecast of a line under ``method`` (the line's own method when ``None``).

    A person's amount wins under every method, and a line whose contracts are
    all completed reads its final figure under every other one.
    """
    if figures.override is not None:
        return MethodOutcome(figures.override, SOURCE_MANUAL, METHOD_MANUAL)
    chosen = method or figures.method
    best = automatic_forecast(figures)
    if best.source == SOURCE_FINAL:
        return MethodOutcome(best.amount, best.source, chosen)
    if chosen == METHOD_MAXIMUM:
        top = maximum_forecast(figures)
        return MethodOutcome(top.amount, top.source, chosen)
    if chosen == METHOD_EVM_CPI:
        evm = evm_outcome(figures)
        if evm is not None:
            return evm
        return MethodOutcome(best.amount, best.source, chosen, applied=False)
    if chosen == METHOD_MANUAL:
        return MethodOutcome(best.amount, best.source, chosen, applied=False)
    return MethodOutcome(best.amount, best.source, METHOD_BEST_AVAILABLE)


def all_method_outcomes(figures: LineFigures) -> dict[str, MethodOutcome]:
    """Every method on one line side by side, for the line's documentation.

    The manual entry is the person's amount when there is one; the other three
    are worked out from the data as if no amount had been entered.
    """
    plain = replace(figures, override=None)
    out = {m: method_outcome(plain, m) for m in FORECAST_METHODS if m != METHOD_MANUAL}
    if figures.override is not None:
        out[METHOD_MANUAL] = MethodOutcome(figures.override, SOURCE_MANUAL, METHOD_MANUAL)
    else:
        out[METHOD_MANUAL] = method_outcome(plain, METHOD_MANUAL)
    return out


def forecast_for(figures: LineFigures) -> Forecast:
    """The forecast to report: a person's override when there is one, else the line's method."""
    out = method_outcome(figures)
    return Forecast(out.amount, out.source)


def variance(forecast: Decimal, planned: Decimal) -> Decimal:
    """Forecast minus plan. Positive means the line will cost more than planned."""
    return forecast - planned


def variance_pct(forecast: Decimal, planned: Decimal) -> Decimal | None:
    """Variance as a percentage of the plan, ``None`` when there is no plan."""
    if planned == ZERO:
        return None
    return ((forecast - planned) / planned * Decimal("100")).quantize(Decimal("0.1"))


# ── Findings ────────────────────────────────────────────────────────────────

FINDING_UNASSIGNED = "cost_control.unassigned_money"
FINDING_CERTIFIED_OVER_COMMITTED = "cost_control.certified_over_committed"
FINDING_OVER_PLAN = "cost_control.forecast_over_plan"
FINDING_PARTLY_AWARDED = "cost_control.partly_awarded"
FINDING_STALE_SNAPSHOT = "cost_control.snapshot_stale"
FINDING_PENDING_CHANGES = "cost_control.pending_changes"

FINDING_RULE_IDS: tuple[str, ...] = (
    FINDING_UNASSIGNED,
    FINDING_CERTIFIED_OVER_COMMITTED,
    FINDING_OVER_PLAN,
    FINDING_PARTLY_AWARDED,
    FINDING_STALE_SNAPSHOT,
    FINDING_PENDING_CHANGES,
)


@dataclass(frozen=True, slots=True)
class LineInput:
    """One row handed to the finding rules: its key, label and figures."""

    key: str
    code: str
    figures: LineFigures


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing a cost controller should look at.

    ``severity`` is ``warning`` (money is at risk or unaccounted for) or
    ``info`` (worth a look). ``amount`` is the money the finding is about, so
    the list can be sorted by what matters most.
    """

    rule_id: str
    severity: str
    line_key: str | None
    code: str
    amount: Decimal
    details: dict[str, str] = field(default_factory=dict)


def line_findings(rows: Iterable[LineInput]) -> list[Finding]:
    """Findings that belong to single cost lines."""
    out: list[Finding] = []
    for row in rows:
        f = row.figures
        committed = f.committed
        if f.certified - committed > CENT and committed != ZERO:
            out.append(
                Finding(
                    FINDING_CERTIFIED_OVER_COMMITTED,
                    "warning",
                    row.key,
                    row.code,
                    f.certified - committed,
                    {"certified": str(f.certified), "committed": str(committed)},
                )
            )
        forecast = forecast_for(f)
        planned = f.planned
        if planned > ZERO and forecast.amount - planned > CENT:
            out.append(
                Finding(
                    FINDING_OVER_PLAN,
                    "warning",
                    row.key,
                    row.code,
                    forecast.amount - planned,
                    {
                        "forecast": str(forecast.amount),
                        "planned": str(planned),
                        "source": forecast.source,
                        "pct": str(variance_pct(forecast.amount, planned)),
                    },
                )
            )
        if (
            f.override is None
            and not f.all_final
            and committed > ZERO
            and planned > ZERO
            and committed < planned * PARTLY_AWARDED_SHARE
        ):
            share = (committed / planned * Decimal("100")).quantize(Decimal("1"))
            out.append(
                Finding(
                    FINDING_PARTLY_AWARDED,
                    "info",
                    row.key,
                    row.code,
                    planned - committed,
                    {"committed": str(committed), "planned": str(planned), "pct": str(share)},
                )
            )
    return out


def project_findings(
    *,
    unassigned_committed: Decimal,
    pending_changes: Decimal,
    pending_count: int,
    days_since_snapshot: int | None,
    has_money: bool,
) -> list[Finding]:
    """Findings about the project as a whole."""
    out: list[Finding] = []
    if abs(unassigned_committed) > CENT:
        out.append(
            Finding(
                FINDING_UNASSIGNED,
                "warning",
                None,
                "",
                unassigned_committed,
                {"amount": str(unassigned_committed)},
            )
        )
    if pending_count > 0:
        out.append(
            Finding(
                FINDING_PENDING_CHANGES,
                "info",
                None,
                "",
                pending_changes,
                {"amount": str(pending_changes), "count": str(pending_count)},
            )
        )
    if has_money and (days_since_snapshot is None or days_since_snapshot > SNAPSHOT_STALE_DAYS):
        out.append(
            Finding(
                FINDING_STALE_SNAPSHOT,
                "info",
                None,
                "",
                ZERO,
                {"days": "" if days_since_snapshot is None else str(days_since_snapshot)},
            )
        )
    return out


def sort_findings(findings: Sequence[Finding]) -> list[Finding]:
    """Warnings first, then the largest amounts."""
    return sorted(findings, key=lambda f: (f.severity != "warning", -abs(f.amount), f.code))
