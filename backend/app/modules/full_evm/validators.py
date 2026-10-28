# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rules for the Full EVM register (rule set ``full_evm``).

Earned value is arithmetic on top of a plan, and the arithmetic is only as
honest as the plan underneath it. A budget curve that dips, a final period that
does not add up to the budget, or an earned value larger than the whole scope
all produce a CPI that looks perfectly ordinary while describing a project that
does not exist. These rules exist to make that impossible to ship quietly.

They run on every baseline and measurement write and their findings are stored
on the row, so a list view shows whether a number can be trusted without
re-running the engine per item. They do not *block* the write: a baseline is
routinely half-entered, and refusing to save would cost the planner their work
to enforce a rule about work in progress. The blocking decision belongs to the
caller, which can read ``report.has_errors`` and refuse an *approval*.

Baseline rules
--------------
* ``full_evm.baseline_bac_positive``   - ERROR. A baseline with BAC <= 0 makes
  every ratio undefined and every forecast meaningless.
* ``full_evm.baseline_periods_ordered`` - ERROR. Period end dates must strictly
  increase with ordinal, with no duplicates: the curve is a function of time.
* ``full_evm.baseline_pv_monotonic``   - ERROR. Cumulative planned value must
  never decrease. A dip means someone entered a per-period amount into a
  cumulative column, which silently deflates every later SPI.
* ``full_evm.baseline_pv_matches_bac`` - ERROR. The last period's cumulative PV
  must equal BAC. If the curve stops short, SPI drifts towards a flattering
  number exactly as the project approaches completion.
* ``full_evm.baseline_quantity_monotonic`` - WARNING. Cumulative planned
  quantity, where supplied, must not decrease either. A warning rather than an
  error because quantity is optional supporting evidence, not the measurement
  base.

Measurement rules
-----------------
* ``full_evm.measure_non_negative``    - ERROR. PV, EV, AC and BAC are
  cumulative totals; a negative one is a data fault, not a credit.
* ``full_evm.measure_ev_within_bac``   - ERROR. You cannot earn more value than
  the entire scope is worth. EV > BAC is the classic symptom of progress
  claimed against a superseded, smaller budget.
* ``full_evm.measure_pv_follows_baseline`` - WARNING. The observed PV should
  match the baseline curve at the data date. A divergence is legitimate (a
  manual override) but must be visible.
* ``full_evm.measure_indices_defined`` - INFO. Reports which indices are
  undefined because their denominator is zero. This is INFO, never an error:
  a project with no spend and no earned value yet is the normal state at the
  start, not a defect.
* ``full_evm.measure_eac_method_declared`` - ERROR. The stored EAC method must
  be a supported name and the effective method must be recorded. A row that
  cannot say which of the disagreeing EAC formulas produced its number is not
  auditable.
* ``full_evm.measure_tcpi_achievable`` - WARNING. Flags a To Complete
  Performance Index that demands materially better cost efficiency than the
  project has ever achieved, including the undefined case where the budget is
  already spent with work outstanding.

Every rule reads the same plain dictionary the service builds, so none needs a
database session and all are unit-testable in isolation.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

# The amount format the built-in rules already use: the decimals the currency
# genuinely has, thousands separators, and the code. Taken from the core rules
# rather than rewritten here, so two findings on one screen cannot disagree
# about what an amount looks like. Importing it registers nothing.
from app.core.validation.rules import _fmt_money
from app.modules.full_evm.metrics import EAC_METHODS

logger = logging.getLogger(__name__)

#: The rule set every Full EVM rule registers under.
FULL_EVM_RULE_SET = "full_evm"

#: Standard label reported on every rule, matching the ``standard`` contract of
#: the core engine. EVM is a discipline rather than a national standard, so the
#: rules are universal and apply to every region.
_STANDARD = "universal"

#: Relative tolerance when comparing a curve endpoint against BAC, and an
#: observed PV against the curve. One part in ten thousand absorbs honest
#: rounding across a long curve without hiding a real gap.
_RELATIVE_TOLERANCE = Decimal("0.0001")

#: Absolute floor for the same comparison, so a tiny budget is not held to an
#: impossible tolerance.
_ABSOLUTE_TOLERANCE = Decimal("0.01")

#: A TCPI above this demands the remaining work run materially more
#: efficiently than planned. 1.10 is the usual practitioner alarm line.
_TCPI_ALARM = Decimal("1.10")


# ── Shared helpers ───────────────────────────────────────────────────────────


def _dec(value: Any) -> Decimal | None:
    """Parse a money or index value, returning ``None`` when it is not usable.

    ``None`` covers both "absent" and "unparseable" on purpose: a rule reports
    an unusable field through its own message, and no rule should crash the
    engine over a malformed input.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def _as_date(value: Any) -> date | None:
    """Parse an ISO date string or pass a ``date`` through; ``None`` if invalid."""
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _tolerance(reference: Decimal) -> Decimal:
    """Comparison tolerance for an amount: relative, with an absolute floor."""
    return max(abs(reference) * _RELATIVE_TOLERANCE, _ABSOLUTE_TOLERANCE)


def _periods(data: Any) -> list[dict[str, Any]]:
    """Extract the period list from the validation payload."""
    if not isinstance(data, dict):
        return []
    periods = data.get("periods")
    if not isinstance(periods, list):
        return []
    return [p for p in periods if isinstance(p, dict)]


def _payload(data: Any) -> dict[str, Any]:
    """Return the payload as a dict, tolerating a non-dict input."""
    return data if isinstance(data, dict) else {}


def _currency(payload: dict[str, Any]) -> str:
    """The currency this payload states, or empty when it states none.

    A baseline payload carries the currency its budget is denominated in. A
    measurement payload does not, and none is invented for it: an amount here
    is then grouped and written without a code, which is honest, where a
    guessed code would read as authoritative and be wrong whenever the project
    is not in it.
    """
    return str(payload.get("currency") or "").strip()


def _result(
    rule: ValidationRule,
    *,
    passed: bool,
    message: str,
    element_ref: str | None = None,
    details: dict[str, Any] | None = None,
    suggestion: str | None = None,
    severity: Severity | None = None,
) -> RuleResult:
    """Build a :class:`RuleResult` carrying the rule's own identity."""
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=severity or rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=element_ref,
        details=details or {},
        suggestion=suggestion,
    )


# ── Baseline rules ───────────────────────────────────────────────────────────


class BaselineBacPositive(ValidationRule):
    """BAC must be a positive amount."""

    rule_id = "full_evm.baseline_bac_positive"
    name = "Baseline budget is positive"
    standard = _STANDARD
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "A performance measurement baseline needs a Budget At Completion greater than zero."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Check that the baseline carries a usable, strictly positive BAC."""
        payload = _payload(context.data)
        if payload.get("kind") != "baseline":
            return []
        bac = _dec(payload.get("bac"))
        currency = _currency(payload)
        if bac is None:
            return [
                _result(
                    self,
                    passed=False,
                    message="Budget At Completion is missing or not a number.",
                    suggestion="Enter the total approved budget for the scope this baseline measures.",
                )
            ]
        if bac <= 0:
            return [
                _result(
                    self,
                    passed=False,
                    message=f"Budget At Completion is {_fmt_money(bac, currency)}; it must be greater than zero.",
                    details={"bac": str(bac)},
                    suggestion=(
                        "With a zero budget every index (CPI, SPI, percent complete) is undefined "
                        "and no forecast can be produced."
                    ),
                )
            ]
        return [_result(self, passed=True, message=f"Budget At Completion is {_fmt_money(bac, currency)}.")]


class BaselinePeriodsOrdered(ValidationRule):
    """Period end dates must strictly increase with ordinal."""

    rule_id = "full_evm.baseline_periods_ordered"
    name = "Baseline periods are ordered in time"
    standard = _STANDARD
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "Each baseline period must end strictly later than the one before it."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Check the curve is a function of time: no repeats, no going back."""
        payload = _payload(context.data)
        if payload.get("kind") != "baseline":
            return []
        periods = _periods(payload)
        if not periods:
            return [
                _result(
                    self,
                    passed=False,
                    message="The baseline has no periods, so it defines no planned-value curve.",
                    suggestion="Add at least one period ending with the cumulative budget.",
                )
            ]

        results: list[RuleResult] = []
        previous: date | None = None
        for index, period in enumerate(periods):
            ref = str(period.get("label") or period.get("ordinal") or index)
            current = _as_date(period.get("period_end"))
            if current is None:
                results.append(
                    _result(
                        self,
                        passed=False,
                        message=f"Period {ref} has no readable end date.",
                        element_ref=ref,
                        suggestion="Give every period an ISO 8601 end date such as 2026-04-30.",
                    )
                )
                continue
            if previous is not None and current <= previous:
                results.append(
                    _result(
                        self,
                        passed=False,
                        message=(
                            f"Period {ref} ends {current.isoformat()}, which is not after the preceding period "
                            f"end {previous.isoformat()}."
                        ),
                        element_ref=ref,
                        details={"period_end": current.isoformat(), "previous_end": previous.isoformat()},
                        suggestion="Sort the curve by end date and remove duplicate periods.",
                    )
                )
            previous = current

        if not results:
            results.append(
                _result(self, passed=True, message=f"All {len(periods)} periods run forward in time."),
            )
        return results


class BaselinePvMonotonic(ValidationRule):
    """Cumulative planned value must never decrease."""

    rule_id = "full_evm.baseline_pv_monotonic"
    name = "Cumulative planned value never decreases"
    standard = _STANDARD
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Planned value on a baseline period is cumulative, so it can only rise or stay flat."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Walk the curve and report every point where the total drops."""
        payload = _payload(context.data)
        if payload.get("kind") != "baseline":
            return []
        periods = _periods(payload)
        if not periods:
            return []

        currency = _currency(payload)
        results: list[RuleResult] = []
        previous: Decimal | None = None
        for index, period in enumerate(periods):
            ref = str(period.get("label") or period.get("ordinal") or index)
            value = _dec(period.get("planned_value"))
            if value is None:
                results.append(
                    _result(
                        self,
                        passed=False,
                        message=f"Period {ref} has no readable cumulative planned value.",
                        element_ref=ref,
                    )
                )
                continue
            if previous is not None and value < previous:
                results.append(
                    _result(
                        self,
                        passed=False,
                        message=(
                            f"Cumulative planned value drops from {_fmt_money(previous, currency)} to "
                            f"{_fmt_money(value, currency)} at period {ref}. "
                            "A cumulative total cannot go down."
                        ),
                        element_ref=ref,
                        details={"planned_value": str(value), "previous_planned_value": str(previous)},
                        suggestion=(
                            "This column holds the running total to the period end, not the amount planned "
                            "within the period. Convert per-period amounts to a running total."
                        ),
                    )
                )
            previous = value

        if not results:
            results.append(_result(self, passed=True, message="The planned-value curve rises monotonically."))
        return results


class BaselinePvMatchesBac(ValidationRule):
    """The curve must finish at the budget."""

    rule_id = "full_evm.baseline_pv_matches_bac"
    name = "Planned-value curve finishes at the budget"
    standard = _STANDARD
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "The last period's cumulative planned value must equal the Budget At Completion."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Compare the final cumulative planned value against BAC."""
        payload = _payload(context.data)
        if payload.get("kind") != "baseline":
            return []
        periods = _periods(payload)
        bac = _dec(payload.get("bac"))
        if not periods or bac is None:
            return []

        currency = _currency(payload)
        final = _dec(periods[-1].get("planned_value"))
        if final is None:
            return [
                _result(
                    self,
                    passed=False,
                    message="The final period has no readable cumulative planned value.",
                )
            ]
        gap = final - bac
        if abs(gap) > _tolerance(bac):
            return [
                _result(
                    self,
                    passed=False,
                    message=(
                        f"The curve ends at {_fmt_money(final, currency)} but the budget is "
                        f"{_fmt_money(bac, currency)}, a gap of {_fmt_money(gap, currency)}. "
                        "Every schedule performance index is measured against this curve."
                    ),
                    details={"final_planned_value": str(final), "bac": str(bac), "gap": str(gap)},
                    suggestion=(
                        "Extend or rescale the curve so its last cumulative value equals the budget, "
                        "or correct the budget."
                    ),
                )
            ]
        return [
            _result(self, passed=True, message=f"The curve ends at {_fmt_money(final, currency)}, matching the budget.")
        ]


class BaselineQuantityMonotonic(ValidationRule):
    """Cumulative planned quantity, where present, must not decrease."""

    rule_id = "full_evm.baseline_quantity_monotonic"
    name = "Cumulative planned quantity never decreases"
    standard = _STANDARD
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Planned physical quantity on a baseline period is cumulative, so it can only rise or stay flat."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Walk the optional quantity curve the same way as the money curve."""
        payload = _payload(context.data)
        if payload.get("kind") != "baseline":
            return []
        periods = _periods(payload)
        supplied = [(i, p) for i, p in enumerate(periods) if p.get("planned_quantity") is not None]
        if not supplied:
            return []

        results: list[RuleResult] = []
        previous: Decimal | None = None
        for index, period in supplied:
            ref = str(period.get("label") or period.get("ordinal") or index)
            value = _dec(period.get("planned_quantity"))
            if value is None:
                results.append(
                    _result(
                        self,
                        passed=False,
                        message=f"Period {ref} has a planned quantity that is not a number.",
                        element_ref=ref,
                    )
                )
                continue
            if previous is not None and value < previous:
                results.append(
                    _result(
                        self,
                        passed=False,
                        message=(f"Cumulative planned quantity drops from {previous} to {value} at period {ref}."),
                        element_ref=ref,
                        details={"planned_quantity": str(value), "previous_planned_quantity": str(previous)},
                        suggestion="Enter the running total of installed quantity, not the quantity per period.",
                    )
                )
            previous = value

        if not results:
            results.append(_result(self, passed=True, message="The planned-quantity curve rises monotonically."))
        return results


# ── Measurement rules ────────────────────────────────────────────────────────


class MeasureNonNegative(ValidationRule):
    """Cumulative money totals must not be negative."""

    rule_id = "full_evm.measure_non_negative"
    name = "Measured amounts are not negative"
    standard = _STANDARD
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "BAC, PV, EV and AC are cumulative totals and cannot be negative."

    _FIELDS: tuple[tuple[str, str], ...] = (
        ("bac", "Budget At Completion"),
        ("pv", "Planned Value"),
        ("ev", "Earned Value"),
        ("ac", "Actual Cost"),
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Check each cumulative amount is present, numeric and non-negative."""
        payload = _payload(context.data)
        if payload.get("kind") != "measure":
            return []

        currency = _currency(payload)
        results: list[RuleResult] = []
        for key, label in self._FIELDS:
            value = _dec(payload.get(key))
            if value is None:
                results.append(
                    _result(
                        self,
                        passed=False,
                        message=f"{label} ({key.upper()}) is missing or not a number.",
                        element_ref=key,
                    )
                )
            elif value < 0:
                results.append(
                    _result(
                        self,
                        passed=False,
                        message=(
                            f"{label} ({key.upper()}) is {_fmt_money(value, currency)}; "
                            "a cumulative total cannot be negative."
                        ),
                        element_ref=key,
                        details={key: str(value)},
                        suggestion="Post a correcting entry upstream rather than a negative cumulative total.",
                    )
                )
        if not results:
            results.append(_result(self, passed=True, message="All cumulative amounts are non-negative."))
        return results


class MeasureEvWithinBac(ValidationRule):
    """Earned value cannot exceed the whole budget."""

    rule_id = "full_evm.measure_ev_within_bac"
    name = "Earned value stays within the budget"
    standard = _STANDARD
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Earned Value is budgeted cost of work done, so it can never exceed the Budget At Completion."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Compare EV against BAC."""
        payload = _payload(context.data)
        if payload.get("kind") != "measure":
            return []
        ev = _dec(payload.get("ev"))
        bac = _dec(payload.get("bac"))
        currency = _currency(payload)
        if ev is None or bac is None or bac <= 0:
            return []
        if ev > bac + _tolerance(bac):
            return [
                _result(
                    self,
                    passed=False,
                    message=(
                        f"Earned Value {_fmt_money(ev, currency)} exceeds the Budget At Completion "
                        f"{_fmt_money(bac, currency)}. "
                        "More value cannot be earned than the scope is worth."
                    ),
                    details={"ev": str(ev), "bac": str(bac)},
                    suggestion=(
                        "Usually progress was claimed against a superseded, smaller budget. "
                        "Re-baseline first, then re-measure."
                    ),
                )
            ]
        return [
            _result(
                self,
                passed=True,
                message=f"Earned Value {_fmt_money(ev, currency)} is within the budget {_fmt_money(bac, currency)}.",
            )
        ]


class MeasurePvFollowsBaseline(ValidationRule):
    """The observed planned value should match the baseline curve."""

    rule_id = "full_evm.measure_pv_follows_baseline"
    name = "Planned value matches the baseline curve"
    standard = _STANDARD
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "The measured Planned Value should equal the baseline's cumulative curve at the data date."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Compare the recorded PV against the value the curve implies."""
        payload = _payload(context.data)
        if payload.get("kind") != "measure":
            return []
        pv = _dec(payload.get("pv"))
        curve_pv = _dec(payload.get("baseline_pv"))
        currency = _currency(payload)
        if pv is None or curve_pv is None:
            return []
        gap = pv - curve_pv
        if abs(gap) > _tolerance(curve_pv if curve_pv != 0 else pv):
            return [
                _result(
                    self,
                    passed=False,
                    message=(
                        f"Planned Value {_fmt_money(pv, currency)} differs from the baseline curve value "
                        f"{_fmt_money(curve_pv, currency)} at this data date by {_fmt_money(gap, currency)}."
                    ),
                    details={"pv": str(pv), "baseline_pv": str(curve_pv), "gap": str(gap)},
                    suggestion=(
                        "An override is allowed but changes every schedule variance on this row. "
                        "Clear the override to take the value straight from the curve."
                    ),
                )
            ]
        return [_result(self, passed=True, message="Planned Value matches the baseline curve.")]


class MeasureIndicesDefined(ValidationRule):
    """Report which indices are undefined, without calling that a defect."""

    rule_id = "full_evm.measure_indices_defined"
    name = "Performance indices are defined"
    standard = _STANDARD
    severity = Severity.INFO
    category = RuleCategory.COMPLETENESS
    description = "Reports indices whose denominator is zero, which is normal before a project has spend or progress."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Name each undefined index and why, at INFO severity."""
        payload = _payload(context.data)
        if payload.get("kind") != "measure":
            return []

        pv = _dec(payload.get("pv"))
        ac = _dec(payload.get("ac"))
        bac = _dec(payload.get("bac"))
        undefined: list[str] = []
        if ac is not None and ac == 0:
            undefined.append("CPI (no actual cost recorded yet)")
        if pv is not None and pv == 0:
            undefined.append("SPI (nothing was scheduled to be done yet)")
        if bac is not None and ac is not None and bac == ac:
            undefined.append("TCPI to budget (the budget is exactly consumed)")

        if not undefined:
            return [_result(self, passed=True, message="Every performance index is defined for this data date.")]
        return [
            _result(
                self,
                passed=False,
                message=("Not yet measurable: " + "; ".join(undefined) + "."),
                details={"undefined": undefined},
                suggestion=(
                    "This is expected early in a project. The affected indices are stored as null, "
                    "never as zero, so they are not mistaken for poor performance."
                ),
            )
        ]


class MeasureEacMethodDeclared(ValidationRule):
    """The EAC formula in use must be recorded and supported."""

    rule_id = "full_evm.measure_eac_method_declared"
    name = "The EAC formula in use is declared"
    standard = _STANDARD
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "The standard EAC formulas disagree, so each row must name the one that produced its forecast."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Check both the requested and the effective method are supported names."""
        payload = _payload(context.data)
        if payload.get("kind") != "measure":
            return []

        requested = payload.get("eac_method")
        effective = payload.get("eac_method_effective")
        problems: list[str] = []
        if requested not in EAC_METHODS:
            problems.append(f"requested method {requested!r} is not one of: {', '.join(EAC_METHODS)}")
        # "auto" is a selection strategy, not a formula, so it can be requested
        # but can never be the formula that actually ran.
        if effective not in EAC_METHODS or effective == "auto":
            allowed = ", ".join(m for m in EAC_METHODS if m != "auto")
            problems.append(f"effective method {effective!r} is not one of: {allowed}")

        if problems:
            return [
                _result(
                    self,
                    passed=False,
                    message="The EAC forecast does not declare a usable formula: " + "; ".join(problems) + ".",
                    details={"eac_method": str(requested), "eac_method_effective": str(effective)},
                    suggestion=(
                        "Recompute the measurement so the register records which formula produced the forecast."
                    ),
                )
            ]
        note = ""
        if requested != effective and requested != "auto":
            note = (
                f" The requested formula '{requested}' was not computable for this data, "
                f"so '{effective}' was used instead."
            )
        return [
            _result(
                self,
                passed=True,
                message=f"Forecast produced by the '{effective}' EAC formula.{note}",
                details={"eac_method": str(requested), "eac_method_effective": str(effective)},
            )
        ]


class MeasureTcpiAchievable(ValidationRule):
    """Flag a to-complete efficiency the project has never demonstrated."""

    rule_id = "full_evm.measure_tcpi_achievable"
    name = "To-complete performance is achievable"
    standard = _STANDARD
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "Warns when the remaining work must run materially more efficiently than planned to hit the budget."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Compare TCPI to the alarm line, and cover the undefined case."""
        payload = _payload(context.data)
        if payload.get("kind") != "measure":
            return []

        bac = _dec(payload.get("bac"))
        ev = _dec(payload.get("ev"))
        ac = _dec(payload.get("ac"))
        tcpi = _dec(payload.get("tcpi_bac"))
        cpi = _dec(payload.get("cpi"))

        if tcpi is None:
            # Undefined TCPI has two very different meanings. With work still
            # outstanding it is the worst case there is: the budget is gone and
            # the remaining scope has nothing left to fund it.
            if bac is not None and ev is not None and ac is not None and bac == ac and ev < bac:
                return [
                    _result(
                        self,
                        passed=False,
                        message=(
                            f"The budget {_fmt_money(bac, _currency(payload))} is fully consumed while "
                            f"{_fmt_money(bac - ev, _currency(payload))} of value remains to be earned. "
                            "No cost efficiency can recover the original budget."
                        ),
                        details={"bac": str(bac), "ev": str(ev), "ac": str(ac)},
                        suggestion="Re-baseline or fund the overrun; the budget target is no longer reachable.",
                    )
                ]
            if bac is not None and ev is not None and bac == ev:
                return [
                    _result(
                        self,
                        passed=True,
                        message="All budgeted value has been earned; no to-complete efficiency is required.",
                    )
                ]
            return []

        if tcpi > _TCPI_ALARM:
            demand = f"{tcpi}"
            achieved = f"{cpi}" if cpi is not None else "not yet measurable"
            return [
                _result(
                    self,
                    passed=False,
                    message=(
                        f"Remaining work must run at a cost efficiency of {demand} to finish on budget, "
                        f"against an efficiency to date of {achieved}."
                    ),
                    details={"tcpi_bac": str(tcpi), "cpi": None if cpi is None else str(cpi)},
                    suggestion=(
                        "Recovery above 1.10 is rarely achieved without a scope or method change. "
                        "Review the forecast and consider a re-baseline."
                    ),
                )
            ]
        return [_result(self, passed=True, message=f"To-complete performance index is {tcpi}, within reach.")]


# ── Registration ─────────────────────────────────────────────────────────────

_FULL_EVM_RULES: tuple[ValidationRule, ...] = (
    BaselineBacPositive(),
    BaselinePeriodsOrdered(),
    BaselinePvMonotonic(),
    BaselinePvMatchesBac(),
    BaselineQuantityMonotonic(),
    MeasureNonNegative(),
    MeasureEvWithinBac(),
    MeasurePvFollowsBaseline(),
    MeasureIndicesDefined(),
    MeasureEacMethodDeclared(),
    MeasureTcpiAchievable(),
)


def register_full_evm_rules() -> None:
    """Register the Full EVM rules with the core rule registry.

    Idempotent - the registry overwrites a rule by id, so a re-import or hot
    reload re-registers cleanly. Called from the module ``on_startup`` hook,
    which is what makes ``full_evm`` a reachable rule set rather than a name
    nothing answers to.
    """
    for rule in _FULL_EVM_RULES:
        rule_registry.register(rule, [FULL_EVM_RULE_SET])
    logger.debug("Registered %d full_evm validation rules", len(_FULL_EVM_RULES))


__all__ = [
    "FULL_EVM_RULE_SET",
    "BaselineBacPositive",
    "BaselinePeriodsOrdered",
    "BaselinePvMatchesBac",
    "BaselinePvMonotonic",
    "BaselineQuantityMonotonic",
    "MeasureEacMethodDeclared",
    "MeasureEvWithinBac",
    "MeasureIndicesDefined",
    "MeasureNonNegative",
    "MeasurePvFollowsBaseline",
    "MeasureTcpiAchievable",
    "register_full_evm_rules",
]
