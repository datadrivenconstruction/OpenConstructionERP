# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rules for a public funding application.

Public funding is lost in a small number of specific ways, and almost none of
them are caught by looking at the application form. They are caught by
comparing two dates, or two amounts, that live on different screens. That is
exactly what a validation rule is for, so these five are the module's rules
rather than a checklist somebody has to remember to open.

* ``funding.measure_starts_after_application`` - work began before the
  application was filed. This is the single most expensive mistake in the
  field, because it is usually unfixable: most programmes exclude the whole
  measure rather than the early part, and no later approval repairs it.
  German practice calls the prohibition Verbot des vorzeitigen
  Maßnahmenbeginns, United States federal practice calls the same money
  pre-award costs, and both allow it only with written permission granted in
  advance, which is why the rule can be told about that permission instead of
  being switched off.

* ``funding.costs_fall_in_the_award_period`` - a draw claims a period that
  reaches outside the window the award named. Costs dated outside it are not
  claimable, and a draw that overlaps the boundary is usually paid first and
  clawed back later, which is worse than a refusal.

* ``funding.own_share_is_covered`` - the applicant is not carrying the share
  the programme requires it to carry. Stated against the eligible base rather
  than the project total, because that is the base the programme computes on.

* ``funding.cumulation_within_aid_intensity`` - everything public on this
  project, added together, is over the ceiling one of its programmes names.
  Aid is cumulated across programmes and across levels of government, so an
  application that is faultless on its own can breach the cap by existing
  alongside another one.

* ``funding.proof_of_use_is_on_time`` - the award period has ended and the
  report that has to follow it is missing or late.

The first two are ERROR and the rest are WARNING, which is a departure from
the neighbouring modules, where every rule is a warning. The reason is not
severity of consequence but who can still act. A warning says two figures
disagree and a person must decide which to believe. These two say a date has
already passed in a way that cannot be argued with: the work started when it
started. Nothing downstream should treat such an application as submittable,
so they block.
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
# genuinely has, plus the code, so "1,234.00 EUR" rather than "1234.00". Taken
# from the core rules rather than rewritten here, because a second spelling of
# the same idea is how two findings on one screen end up disagreeing about
# what an amount looks like. Importing it does not register anything: the
# built-in rules go into the registry through an explicit call, not on import.
from app.core.validation.rules import _fmt_money

# The module's own bundle rather than the shared one, which ships four
# languages: these findings sit on a screen translated into every offered
# language, and a sentence the shared bundle cannot answer arrives in English.
from app.modules.funding.messages import translate

logger = logging.getLogger(__name__)

#: Rule set name callers pass to ``ValidationEngine.validate``.
FUNDING_RULE_SET = "funding"

#: Below this, two money figures are the same number. Both sides are rounded
#: to cents before they arrive, so a smaller gap is rounding, not a finding.
_MONEY_EPSILON = Decimal("0.01")

#: Below this, two percentages are the same rate. Funding rates are quoted to
#: at most two decimals by every programme seen so far.
_RATE_EPSILON = Decimal("0.01")


def _ok(locale: str) -> str:
    """Shared "OK" string, the same key every built-in rule uses."""
    return translate("common.ok", locale=locale)


def _locale(context: ValidationContext) -> str:
    """The caller's locale, defaulting to English."""
    meta = getattr(context, "metadata", None) or {}
    return str(meta.get("locale") or "en")


def _currency(context: ValidationContext) -> str:
    """The currency the application's amounts are in, or empty when unknown.

    Empty degrades to a bare figure written with two decimals, which is what
    every amount in a finding looked like before the application carried its
    currency at all.
    """
    return str(_section(context, "application").get("currency") or "")


def _decimal(value: Any) -> Decimal:
    """Coerce a money-ish value to Decimal, degrading to zero on junk."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _day(value: Any) -> str:
    """The calendar day of an ISO-8601 value, or empty when there is none.

    Dates arrive as ``2026-03-01`` from a date picker and as
    ``2026-03-01T09:30:00+01:00`` from anything that once passed through a
    timestamp. Comparing the first ten characters compares calendar days in
    the order they fall, which is the comparison every rule here wants, and
    it does it without inventing a timezone for a deadline that does not have
    one. Anything that is not a plausible day is treated as absent, because a
    rule that guesses at a broken date states a finding nobody can act on.
    """
    text = str(value or "").strip()
    if len(text) < 10:
        return ""
    day = text[:10]
    if day[4] != "-" or day[7] != "-":
        return ""
    if not (day[:4].isdigit() and day[5:7].isdigit() and day[8:10].isdigit()):
        return ""
    return day


def _section(context: ValidationContext, key: str) -> dict[str, Any]:
    """One named object out of the validated payload."""
    data = context.data
    if isinstance(data, dict):
        value = data.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _rows(context: ValidationContext, key: str) -> list[dict[str, Any]]:
    """One named list of records out of the validated payload."""
    data = context.data
    if isinstance(data, dict):
        raw = data.get(key) or []
        if isinstance(raw, list):
            return [row for row in raw if isinstance(row, dict)]
    return []


class FundingMeasureStartsAfterApplication(ValidationRule):
    """Work must not have begun before the application was filed."""

    rule_id = "funding.measure_starts_after_application"
    name = "Measure Starts After The Application"
    standard = "funding"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Flags an application whose works began before it was filed, without permission to start early."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _locale(context)
        application = _section(context, "application")
        programme = _section(context, "programme")

        # A programme that allows a free start has nothing to check. This is
        # rare and it is a property of the programme, so it is read from the
        # programme rather than from a per-application override: an applicant
        # cannot grant themselves the exemption.
        if not programme.get("requires_application_before_start", True):
            return []

        start = _day(application.get("measure_start_on"))
        filed = _day(application.get("submitted_on"))
        # Nothing to compare yet. A draft with no dates is not a finding, it
        # is a draft, and reporting it would train people to ignore the rule.
        if not start or not filed:
            return []

        early = start < filed
        permitted = bool(application.get("early_start_approved"))
        passed = not early or permitted
        reference = str(application.get("early_start_reference") or "")

        # An early start that is permitted but names no permission is worth
        # saying out loud without failing: the fact is fine, the evidence for
        # it is missing, and an auditor asks for the evidence.
        message = _ok(locale)
        suggestion: str | None = None
        if early and permitted and not reference:
            message = translate("funding.measure_starts_after_application.unevidenced", locale=locale, start=start)
            suggestion = translate("funding.measure_starts_after_application.evidence", locale=locale)
        elif early and not permitted:
            message = translate(
                "funding.measure_starts_after_application.fail",
                locale=locale,
                start=start,
                filed=filed,
            )
            suggestion = translate("funding.measure_starts_after_application.suggestion", locale=locale)

        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message=message,
                element_ref=str(application.get("code") or application.get("id") or ""),
                suggestion=suggestion,
            )
        ]


class FundingCostsFallInTheAwardPeriod(ValidationRule):
    """Every draw claims a period inside the window the award named."""

    rule_id = "funding.costs_fall_in_the_award_period"
    name = "Costs Fall In The Award Period"
    standard = "funding"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Flags a disbursement whose claimed period reaches outside the awarded window."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _locale(context)
        application = _section(context, "application")
        period_start = _day(application.get("award_period_start"))
        period_end = _day(application.get("award_period_end"))
        # No award period means no award yet, or a programme that sets none.
        # Either way there is nothing to be outside of.
        if not period_start and not period_end:
            return []

        results: list[RuleResult] = []
        for row in _rows(context, "disbursements"):
            # A draft draw is a working note. It becomes a claim when it is
            # submitted, and that is when its dates start to matter.
            if str(row.get("status") or "draft") == "draft":
                continue
            claim_from = _day(row.get("period_from"))
            claim_to = _day(row.get("period_to"))
            if not claim_from and not claim_to:
                continue

            before = bool(period_start and claim_from and claim_from < period_start)
            after = bool(period_end and claim_to and claim_to > period_end)
            label = str(row.get("code") or row.get("sequence") or "")

            if before and after:
                fault = "spans"
            elif before:
                fault = "before"
            elif after:
                fault = "after"
            else:
                fault = ""

            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=not fault,
                    message=(
                        _ok(locale)
                        if not fault
                        else translate(
                            f"funding.costs_fall_in_the_award_period.{fault}",
                            locale=locale,
                            draw=label,
                            period_start=period_start or "-",
                            period_end=period_end or "-",
                        )
                    ),
                    element_ref=str(row.get("id") or label),
                    suggestion=(
                        None
                        if not fault
                        else translate("funding.costs_fall_in_the_award_period.suggestion", locale=locale)
                    ),
                )
            )
        return results


class FundingOwnShareIsCovered(ValidationRule):
    """The applicant carries the share of eligible costs it has to carry."""

    rule_id = "funding.own_share_is_covered"
    name = "Own Share Is Covered"
    standard = "funding"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags an application whose recorded own contribution is below what the programme requires."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _locale(context)
        currency = _currency(context)
        application = _section(context, "application")
        programme = _section(context, "programme")

        required_rate = _decimal(programme.get("own_share_percent"))
        if required_rate <= 0:
            return []

        base = _decimal(application.get("eligible_cost_base"))
        if base <= 0:
            return []

        required = (base * required_rate / Decimal("100")).quantize(Decimal("0.01"))
        recorded = _decimal(application.get("own_share_amount"))
        short = required - recorded
        passed = short <= _MONEY_EPSILON

        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message=(
                    _ok(locale)
                    if passed
                    else translate(
                        "funding.own_share_is_covered.fail",
                        locale=locale,
                        # Passed as Decimal. The formatter accepts either, and
                        # both values are Decimal already, one quantized to the
                        # cent a few lines above, so the trip through float was
                        # a narrowing with nothing on the other side of it.
                        #
                        # Not a rendering fix, and the measurement is written
                        # down here so nobody has to redo it to find that out.
                        # Sampling two-decimal amounts by magnitude, no output
                        # differs below 1e13 in a currency with subunits, and
                        # none below 1e14 in IDR, VND, KRW or JPY, which are the
                        # currencies whose figures run largest. No subsidy
                        # reaches either. This is here because money is Decimal
                        # everywhere in this project and a conversion that buys
                        # nothing is worth removing on that ground alone.
                        required=_fmt_money(required, currency),
                        recorded=_fmt_money(recorded, currency),
                        rate=format(required_rate.normalize(), "f"),
                    )
                ),
                element_ref=str(application.get("code") or application.get("id") or ""),
                suggestion=(None if passed else translate("funding.own_share_is_covered.suggestion", locale=locale)),
            )
        ]


class FundingCumulationWithinAidIntensity(ValidationRule):
    """Everything public on this project stays under the declared ceiling."""

    rule_id = "funding.cumulation_within_aid_intensity"
    name = "Cumulation Stays Within The Aid Intensity"
    standard = "funding"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Flags a project whose combined public funding exceeds the lowest ceiling its programmes declare."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _locale(context)
        application = _section(context, "application")
        peers = _rows(context, "project_applications")
        if not peers:
            return []

        # The binding ceiling is the lowest one any participating programme
        # names, not this programme's own. A programme with a 40 percent cap
        # does not stop caring because a second programme allows 80.
        caps = [
            _decimal(row.get("aid_intensity_cap_percent"))
            for row in peers
            if _decimal(row.get("aid_intensity_cap_percent")) > 0
        ]
        if not caps:
            return []
        cap = min(caps)

        base = _decimal(application.get("eligible_cost_base"))
        if base <= 0:
            return []

        # Withdrawn and rejected applications carry no money. Everything else
        # does, including one still in review: an applicant who books a
        # ceiling on the assumption that a pending application will fail has
        # planned for its failure.
        public_total = sum(
            (
                _decimal(row.get("approved_amount")) or _decimal(row.get("requested_amount"))
                for row in peers
                if str(row.get("status") or "") not in ("withdrawn", "rejected")
            ),
            Decimal("0"),
        )
        intensity = (public_total * Decimal("100") / base).quantize(Decimal("0.01"))
        passed = intensity - cap <= _RATE_EPSILON

        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message=(
                    _ok(locale)
                    if passed
                    else translate(
                        "funding.cumulation_within_aid_intensity.fail",
                        locale=locale,
                        intensity=format(intensity, "f"),
                        cap=format(cap.normalize(), "f"),
                        count=str(len(peers)),
                    )
                ),
                element_ref=str(application.get("project_id") or ""),
                suggestion=(
                    None if passed else translate("funding.cumulation_within_aid_intensity.suggestion", locale=locale)
                ),
            )
        ]


class FundingProofOfUseIsOnTime(ValidationRule):
    """The report that has to follow the award period exists and is not late."""

    rule_id = "funding.proof_of_use_is_on_time"
    name = "Proof Of Use Is On Time"
    standard = "funding"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags a finished award whose proof of use is missing or past its due date."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _locale(context)
        application = _section(context, "application")
        if str(application.get("status") or "") != "approved":
            return []

        period_end = _day(application.get("award_period_end"))
        today = _day(_section(context, "clock").get("today"))
        # Without a clock the rule cannot say what is late, and guessing the
        # server's own date here would make the same application pass or fail
        # depending on which machine asked. The caller supplies it.
        if not period_end or not today or today <= period_end:
            return []

        finals = [row for row in _rows(context, "proofs_of_use") if str(row.get("kind") or "final") == "final"]
        if not finals:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=translate("funding.proof_of_use_is_on_time.missing", locale=locale, period_end=period_end),
                    element_ref=str(application.get("code") or application.get("id") or ""),
                    suggestion=translate("funding.proof_of_use_is_on_time.suggestion", locale=locale),
                )
            ]

        results: list[RuleResult] = []
        for row in finals:
            due = _day(row.get("due_on"))
            submitted = _day(row.get("submitted_on"))
            accepted = str(row.get("status") or "") == "accepted"
            # Accepted closes the question regardless of when it arrived: the
            # authority has already decided it was in time.
            late = bool(due and not accepted and (submitted > due if submitted else today > due))
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=not late,
                    message=(
                        _ok(locale)
                        if not late
                        else translate(
                            "funding.proof_of_use_is_on_time.late"
                            if submitted
                            else "funding.proof_of_use_is_on_time.overdue",
                            locale=locale,
                            due=due,
                            submitted=submitted or today,
                        )
                    ),
                    element_ref=str(row.get("id") or ""),
                    suggestion=(
                        None if not late else translate("funding.proof_of_use_is_on_time.suggestion", locale=locale)
                    ),
                )
            )
        return results


#: Every rule in the set, named once. The registrar iterates this and the
#: tests assert against it, so a rule added to the module cannot quietly be
#: absent from either.
FUNDING_RULES: tuple[type[ValidationRule], ...] = (
    FundingMeasureStartsAfterApplication,
    FundingCostsFallInTheAwardPeriod,
    FundingOwnShareIsCovered,
    FundingCumulationWithinAidIntensity,
    FundingProofOfUseIsOnTime,
)


def register_funding_rules() -> None:
    """Idempotently register the public funding rules.

    Registration is keyed on ``rule_id`` inside the registry, so calling this
    twice replaces each rule with an equal one rather than doubling the set.
    """
    for rule in FUNDING_RULES:
        rule_registry.register(rule(), rule_sets=[FUNDING_RULE_SET])
