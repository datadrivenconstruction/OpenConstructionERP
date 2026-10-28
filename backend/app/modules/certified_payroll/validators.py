# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Certified payroll validation rules.

A certified payroll is a statement somebody signs and an awarding body relies
on. These rules are what reads it before the signature goes on, and they are
deliberately the questions a compliance officer asks first:

* ``certified_payroll.worker_without_classification`` - ERROR. Somebody worked
  and the payroll does not say as what. Nothing about their rate can be checked
  until it does.
* ``certified_payroll.hours_without_determination``   - ERROR. Hours are claimed
  against a classification that cites no wage determination, so no rate was ever
  established for the work.
* ``certified_payroll.rate_below_determination``      - ERROR. The package paid
  is below the package the cited determination requires.
* ``certified_payroll.overtime_base_includes_fringe`` - ERROR. The overtime
  multiplier was applied to a base larger than the basic rate, which pays the
  premium on the fringe benefit amount as well as on the wage.
* ``certified_payroll.statement_of_compliance_missing`` - ERROR. The week has no
  signature, so there is no statement of compliance and nothing was certified.
* ``certified_payroll.fringe_election_unstated``      - WARNING. Fringe money is
  recorded but the payroll does not say whether it went to a plan or was paid in
  cash, which the statement of compliance has to elect between.
* ``certified_payroll.determination_out_of_window``   - WARNING. The week worked
  falls outside the effective window of the determination it cites.

The rules take a plain dict rather than ORM instances, so they are unit-testable
without a session and run identically over a draft week derived live from
payroll entries and over a certified week read back from its frozen lines::

    {
        "week": {...},            # the CertifiedPayrollWeek as a dict
        "lines": [{...}, ...],    # one derived or frozen line per worker
    }

Registration follows the module convention:
:func:`register_certified_payroll_rules` is idempotent and is called from the
module's startup hook and from the test fixtures, because no test process runs
application startup.

Nothing here knows a rate. Every figure a rule compares against is read off the
determination the contractor put on file; the platform ships no wage schedule
and these rules would report the same findings in any jurisdiction.
"""

from __future__ import annotations

import logging
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
# rather than rewritten here, because a second spelling of the same idea is how
# two findings on one screen end up disagreeing about what an amount looks
# like. Importing it registers nothing; the built-in rules go into the registry
# through an explicit call, not on import.
from app.core.validation.rules import _fmt_money
from app.modules.certified_payroll.certpay_math import total_package, underpaid_by, week_days

logger = logging.getLogger(__name__)

# The rule set every certified payroll rule registers under.
CERTIFIED_PAYROLL_RULE_SET = "certified_payroll"

# Tolerance on a money comparison, in currency units per hour. A determination
# is published to the cent and a paid rate is stored to the cent, so anything at
# or below half a cent is rounding rather than underpayment. Without this a
# rate stored as 42.8700 and one stored as 42.87 would read as a shortfall.
_RATE_TOLERANCE = Decimal("0.005")


def _lines(context: ValidationContext) -> list[dict[str, Any]]:
    """Pull the week's lines out of the context, whatever shape the caller sent."""
    data = context.data
    if isinstance(data, dict):
        lines = data.get("lines")
        if isinstance(lines, list):
            return [line for line in lines if isinstance(line, dict)]
    if isinstance(data, list):
        return [line for line in data if isinstance(line, dict)]
    return []


def _week(context: ValidationContext) -> dict[str, Any]:
    """Pull the week header out of the context, or an empty dict."""
    data = context.data
    if isinstance(data, dict):
        week = data.get("week")
        if isinstance(week, dict):
            return week
    return {}


def _decimal(value: Any) -> Decimal | None:
    """Parse a money/hours figure, returning None when it is absent or unusable.

    Returns None rather than raising so one malformed row cannot stop a rule
    from reporting on the other twenty. A rule that cannot read a figure says so
    in its own message instead of failing the whole run.
    """
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def _worker_of(line: dict[str, Any]) -> str:
    """Name the worker a finding is about, never returning an empty string."""
    name = str(line.get("worker_name") or "").strip()
    return name or "an unnamed worker"


def _hours_worked(line: dict[str, Any]) -> Decimal:
    """Total hours on a line: straight plus overtime, missing figures as zero."""
    straight = _decimal(line.get("straight_hours")) or Decimal("0")
    overtime = _decimal(line.get("overtime_hours")) or Decimal("0")
    return straight + overtime


def _ok(rule: ValidationRule, message: str) -> RuleResult:
    """A single passing result standing for the whole check."""
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=True,
        message=message,
    )


def _fail(rule: ValidationRule, message: str, ref: str | None, suggestion: str, **details: Any) -> RuleResult:
    """A failing result naming the specific mistake, not the word 'invalid'."""
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=False,
        message=message,
        element_ref=ref,
        suggestion=suggestion,
        details=details,
    )


class WorkerWithoutClassificationRule(ValidationRule):
    """Somebody is on the payroll with no trade classification at all."""

    rule_id = "certified_payroll.worker_without_classification"
    name = "Worker carries no trade classification"
    standard = "certified_payroll"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = (
        "Every worker on a certified payroll must be shown under the trade classification they worked in, "
        "because the classification is what fixes the rate they were owed."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for line in _lines(context):
            title = str(line.get("classification_title") or "").strip()
            code = str(line.get("classification_code") or "").strip()
            if title or code:
                continue
            results.append(
                _fail(
                    self,
                    f"{_worker_of(line)} is on this payroll with {_hours_worked(line)} hours and no trade "
                    "classification, so there is nothing to check the rate paid against.",
                    str(line.get("resource_id") or line.get("worker_name") or ""),
                    "Assign the worker the classification they worked in, from a wage determination on file "
                    "for this project.",
                    hours=str(_hours_worked(line)),
                    worker=_worker_of(line),
                )
            )
        return results or [_ok(self, "Every worker on this payroll is shown under a trade classification.")]


class HoursWithoutDeterminationRule(ValidationRule):
    """Hours are claimed against a classification citing no determination."""

    rule_id = "certified_payroll.hours_without_determination"
    name = "Hours claimed with no wage determination on file"
    standard = "certified_payroll"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = (
        "A classification on a certified payroll must cite the wage determination that fixed its rate. "
        "Hours worked under a classification with no determination on file rest on no established rate."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for line in _lines(context):
            hours = _hours_worked(line)
            if hours <= 0:
                continue
            identifier = str(line.get("determination_identifier") or "").strip()
            determination_id = str(line.get("determination_id") or "").strip()
            if identifier or determination_id:
                continue
            classification = str(line.get("classification_title") or line.get("classification_code") or "").strip()
            named = f"as {classification}" if classification else "with no classification"
            results.append(
                _fail(
                    self,
                    f"{_worker_of(line)} worked {hours} hours {named} and the payroll cites no wage "
                    "determination for that classification, so no prevailing rate was ever established for "
                    "the work.",
                    str(line.get("resource_id") or line.get("worker_name") or ""),
                    "Record the wage determination the awarding body issued for this contract, add the "
                    "classification to it with its basic and fringe rates, and point the worker at it.",
                    hours=str(hours),
                    classification=classification,
                    worker=_worker_of(line),
                )
            )
        return results or [_ok(self, "Every classification worked on this payroll cites a wage determination.")]


class RateBelowDeterminationRule(ValidationRule):
    """The package paid is below the package the cited determination requires."""

    rule_id = "certified_payroll.rate_below_determination"
    name = "Rate paid is below the determination it cites"
    standard = "certified_payroll"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = (
        "The total package paid, basic wage plus hourly fringe, must be at least the total package the "
        "cited wage determination requires for that classification."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for line in _lines(context):
            required_basic = _decimal(line.get("required_basic_rate"))
            required_fringe = _decimal(line.get("required_fringe_rate"))
            paid_basic = _decimal(line.get("paid_basic_rate"))
            paid_fringe = _decimal(line.get("paid_fringe_rate"))
            if required_basic is None or required_fringe is None or paid_basic is None or paid_fringe is None:
                # A missing figure is the business of the two rules above; this
                # rule only reports a comparison it could actually make.
                continue
            if min(required_basic, required_fringe, paid_basic, paid_fringe) < 0:
                continue
            shortfall = underpaid_by(paid_basic, paid_fringe, required_basic, required_fringe)
            # The currency this line states, never a default. A blank one stays
            # blank: the renderer then groups the digits and writes no code,
            # which is honest, where a guessed code would read as authoritative.
            currency = str(line.get("currency") or "").strip()
            if shortfall > _RATE_TOLERANCE:
                paid = total_package(paid_basic, paid_fringe)
                required = total_package(required_basic, required_fringe)
                identifier = str(line.get("determination_identifier") or "on file").strip()
                results.append(
                    _fail(
                        self,
                        f"{_worker_of(line)} was paid a total package of {_fmt_money(paid, currency)} an hour "
                        f"({_fmt_money(paid_basic, currency)} basic plus {_fmt_money(paid_fringe, currency)} "
                        f"fringe) against the {_fmt_money(required, currency)} required "
                        f"by determination {identifier}, a shortfall of {_fmt_money(shortfall, currency)} "
                        f"for every one of {_hours_worked(line)} hours.",
                        str(line.get("resource_id") or line.get("worker_name") or ""),
                        "Pay the difference and restate the payroll, or correct the rates recorded here if "
                        "they do not match what was actually paid.",
                        shortfall=str(shortfall),
                        paid_package=str(paid),
                        required_package=str(required),
                        worker=_worker_of(line),
                    )
                )
                continue
            # A whole package can still hide a basic wage below the determination,
            # and the overtime premium is computed on the basic wage alone, so the
            # shortfall reappears on every overtime hour. Worth its own finding.
            overtime = _decimal(line.get("overtime_hours")) or Decimal("0")
            basic_short = required_basic - paid_basic
            if overtime > 0 and basic_short > _RATE_TOLERANCE:
                results.append(
                    _fail(
                        self,
                        f"{_worker_of(line)} met the total package but was paid a basic wage of "
                        f"{_fmt_money(paid_basic, currency)} against the {_fmt_money(required_basic, currency)} "
                        f"the determination sets. The overtime premium is computed on the basic wage, "
                        f"so {overtime} overtime hours are underpaid by {_fmt_money(basic_short, currency)} "
                        f"of base each.",
                        str(line.get("resource_id") or line.get("worker_name") or ""),
                        "Raise the basic wage to the determination's basic rate, or move the excess out of "
                        "the fringe amount, then recompute the overtime.",
                        basic_shortfall=str(basic_short),
                        overtime_hours=str(overtime),
                        worker=_worker_of(line),
                    )
                )
        return results or [_ok(self, "Every rate paid on this payroll meets the determination it cites.")]


class OvertimeBaseIncludesFringeRule(ValidationRule):
    """The overtime multiplier was applied to more than the basic rate."""

    rule_id = "certified_payroll.overtime_base_includes_fringe"
    name = "Overtime computed on a base that includes fringe"
    standard = "certified_payroll"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = (
        "The overtime premium is computed on the basic hourly wage alone. An overtime base larger than the "
        "basic rate pays the premium on the fringe benefit amount too, which overstates the payroll."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for line in _lines(context):
            overtime = _decimal(line.get("overtime_hours")) or Decimal("0")
            if overtime <= 0:
                continue
            base = _decimal(line.get("overtime_base_rate"))
            paid_basic = _decimal(line.get("paid_basic_rate"))
            paid_fringe = _decimal(line.get("paid_fringe_rate"))
            if base is None or paid_basic is None:
                continue
            excess = base - paid_basic
            if excess <= _RATE_TOLERANCE:
                continue
            currency = str(line.get("currency") or "").strip()
            fringe_text = (
                f" and the fringe rate is {_fmt_money(paid_fringe, currency)}" if paid_fringe is not None else ""
            )
            results.append(
                _fail(
                    self,
                    f"{_worker_of(line)} has {overtime} overtime hours computed on a base of "
                    f"{_fmt_money(base, currency)} while the basic wage is "
                    f"{_fmt_money(paid_basic, currency)}{fringe_text}. The overtime multiplier has "
                    f"been applied to {_fmt_money(excess, currency)} an hour of fringe benefit money, "
                    "which is not part of the overtime base.",
                    str(line.get("resource_id") or line.get("worker_name") or ""),
                    "Set the overtime base to the basic hourly wage. The fringe amount is paid at face value "
                    "on overtime hours, never multiplied.",
                    overtime_base=str(base),
                    basic_rate=str(paid_basic),
                    excess=str(excess),
                    worker=_worker_of(line),
                )
            )
        return results or [_ok(self, "Every overtime figure on this payroll is computed on the basic wage alone.")]


class StatementOfComplianceMissingRule(ValidationRule):
    """The week carries no signed statement of compliance."""

    rule_id = "certified_payroll.statement_of_compliance_missing"
    name = "Week carries no signed statement of compliance"
    standard = "certified_payroll"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = (
        "A weekly payroll is certified by a signed statement of compliance naming the person who signs and "
        "their position. Without it the submission is a list of hours, not a certified payroll."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        week = _week(context)
        if not week:
            return [_ok(self, "No week header supplied, so there is no statement of compliance to check.")]
        ending = str(week.get("week_ending") or "an unstated date")
        missing: list[str] = []
        if not str(week.get("signatory_name") or "").strip():
            missing.append("the name of the person certifying it")
        if not str(week.get("signatory_title") or "").strip():
            missing.append("their position")
        if not week.get("signed_at"):
            missing.append("the date it was signed")
        if not str(week.get("statement_text") or "").strip():
            missing.append("the wording of the statement itself")
        if not missing:
            return [_ok(self, f"The payroll for the week ending {ending} carries a signed statement of compliance.")]
        return [
            _fail(
                self,
                f"The payroll for the week ending {ending} is missing {', '.join(missing)}, so no statement of "
                "compliance has been made for it.",
                str(week.get("id") or ""),
                "Certify the week: name the person signing and their position, and the statement of compliance "
                "is recorded with the signature.",
                week_ending=ending,
                missing=missing,
            )
        ]


class FringeElectionUnstatedRule(ValidationRule):
    """Fringe money is recorded but the payroll does not say how it was paid."""

    rule_id = "certified_payroll.fringe_election_unstated"
    name = "Fringe paid without saying whether to a plan or in cash"
    standard = "certified_payroll"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = (
        "A statement of compliance elects between paying fringe benefits into approved plans and paying them "
        "in cash. A payroll carrying fringe money but no election does not say which was done."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for line in _lines(context):
            fringe = _decimal(line.get("paid_fringe_rate")) or Decimal("0")
            if fringe <= 0:
                continue
            election = str(line.get("fringe_election") or "").strip().lower()
            if election in {"plan", "cash", "mixed"}:
                continue
            # Read off the same field the two rate rules read it off. This rule
            # used to write the amount with no currency at all while its
            # siblings wrote one from the very same line.
            currency = str(line.get("currency") or "").strip()
            results.append(
                _fail(
                    self,
                    f"{_worker_of(line)} is shown with {_fmt_money(fringe, currency)} an hour of fringe "
                    "benefit money and the payroll does not say whether it went into a benefit plan or "
                    "was paid in cash.",
                    str(line.get("resource_id") or line.get("worker_name") or ""),
                    "State the election for this worker: paid into a plan, paid in cash, or part to a plan "
                    "with the remainder in cash.",
                    fringe_rate=str(fringe),
                    worker=_worker_of(line),
                )
            )
        return results or [_ok(self, "Every fringe amount on this payroll says how it was paid.")]


class DeterminationOutOfWindowRule(ValidationRule):
    """The week worked falls outside the cited determination's effective window."""

    rule_id = "certified_payroll.determination_out_of_window"
    name = "Week falls outside the determination's effective window"
    standard = "certified_payroll"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "A wage determination binds between its effective date and the date it is superseded. Work certified "
        "against a determination that was not in force that week is citing the wrong document."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        week = _week(context)
        ending = str(week.get("week_ending") or "").strip()
        if not ending:
            return [_ok(self, "No week-ending date supplied, so no effective window could be checked.")]
        results: list[RuleResult] = []
        for line in _lines(context):
            effective = str(line.get("determination_effective_date") or "").strip()
            expires = str(line.get("determination_expires_on") or "").strip()
            if not effective and not expires:
                continue
            identifier = str(line.get("determination_identifier") or "on file").strip()
            # ISO dates compare correctly as strings, so no parsing is needed to
            # ask whether the window and the week overlap at all.
            starts_after = bool(effective) and effective > ending
            ended_before = bool(expires) and expires < _week_start(ending)
            if not starts_after and not ended_before:
                continue
            when = f"does not take effect until {effective}" if starts_after else f"was superseded on {expires}"
            results.append(
                _fail(
                    self,
                    f"The payroll for the week ending {ending} cites determination {identifier} for "
                    f"{_worker_of(line)}, but that determination {when}.",
                    str(line.get("determination_id") or ""),
                    "Cite the determination that was in force during this week, and add it to the project if "
                    "it is not on file yet.",
                    week_ending=ending,
                    effective_date=effective,
                    expires_on=expires,
                    determination=identifier,
                )
            )
        return results or [_ok(self, "Every determination cited by this payroll was in force during the week.")]


def _week_start(week_ending: str) -> str:
    """Return the first ISO day of the week ending on ``week_ending``.

    Falls back to the week-ending date itself when it cannot be parsed, which
    makes the comparison that uses it strictly narrower rather than wrong.
    """
    try:
        return week_days(week_ending)[0]
    except ValueError:
        return week_ending


CERTIFIED_PAYROLL_RULES: tuple[type[ValidationRule], ...] = (
    WorkerWithoutClassificationRule,
    HoursWithoutDeterminationRule,
    RateBelowDeterminationRule,
    OvertimeBaseIncludesFringeRule,
    StatementOfComplianceMissingRule,
    FringeElectionUnstatedRule,
    DeterminationOutOfWindowRule,
)


def register_certified_payroll_rules() -> None:
    """Register every certified payroll rule under the ``certified_payroll`` set.

    Idempotent: the registry keys on ``rule_id``, so calling this from module
    startup and again from a test fixture leaves one copy of each rule.
    """
    for rule_cls in CERTIFIED_PAYROLL_RULES:
        rule_registry.register(rule_cls(), [CERTIFIED_PAYROLL_RULE_SET])
    logger.debug("Registered %d certified payroll validation rules", len(CERTIFIED_PAYROLL_RULES))


__all__ = [
    "CERTIFIED_PAYROLL_RULES",
    "CERTIFIED_PAYROLL_RULE_SET",
    "DeterminationOutOfWindowRule",
    "FringeElectionUnstatedRule",
    "HoursWithoutDeterminationRule",
    "OvertimeBaseIncludesFringeRule",
    "RateBelowDeterminationRule",
    "StatementOfComplianceMissingRule",
    "WorkerWithoutClassificationRule",
    "register_certified_payroll_rules",
]
