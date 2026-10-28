# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rules for the FX register.

An exchange rate is the quietest way to get a cost report wrong. Nothing about
a project priced against a stale set, or against a set that does not quote the
currency the client is reported in, looks broken on screen - the numbers are
there, they are just not the numbers anyone agreed to. These rules are the
traffic light for that, and they run as part of the workflow rather than as a
button somebody remembers to press.

Five rules, all in the ``fx`` rule set:

* ``fx.quote_integrity``          - ERROR. Every quote must carry a real
  three-letter code that is not the set's own base, and a strictly positive
  rate. A zero rate divides by zero on the next conversion; a negative one
  flips the sign of a budget.
* ``fx.quote_movement``           - WARNING. A quote that jumped more than the
  tolerated percentage against the set it supersedes is flagged. A misplaced
  decimal in a feed or a hand-entered set reprices a whole estimate silently,
  and this is the only place it is visible before it does.
* ``fx.policy_currency_coverage`` - ERROR. The three currencies a project
  declares - estimating, procurement, reporting - must all be convertible with
  the rate set backing it, or the project cannot report at all.
* ``fx.pinned_set_resolvable``    - ERROR. A project pinned to a rate set must
  name one that exists and is locked. An unlocked pin is not a pin: the set can
  be rewritten by the next refresh and the "reproducible" estimate moves.
* ``fx.rate_freshness``           - WARNING. The backing set must be no older
  than the project's own tolerance.

Every rule reads the plain-dict context that
:meth:`app.modules.fx.service.FxService.build_validation_context` assembles, so
none of them needs a database session and all are unit-testable in isolation.
Rules stay silent (return no results) when there is nothing of their kind to
check - a project with no rate set on file must not bank a passing score from
checks that examined nothing.
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

logger = logging.getLogger(__name__)

#: The rule set every FX rule registers under.
FX_RULE_SET = "fx"

#: Default tolerated day-over-day move for one quote, in percent. Beyond this a
#: quote is flagged for a human to look at, never rejected: currencies really do
#: move this far, just not often and not quietly.
DEFAULT_MAX_QUOTE_MOVE_PCT = Decimal("10")

#: Rate mode that requires a pinned set. Mirrors
#: :data:`app.modules.fx.models.RATE_MODE_PINNED` without importing models, so
#: the rules stay free of the ORM.
RATE_MODE_PINNED = "pinned"

#: The three roles a project currency can play, and how to name them in a
#: message an estimator reads.
POLICY_CURRENCY_FIELDS: tuple[tuple[str, str], ...] = (
    ("estimating_currency", "estimating"),
    ("procurement_currency", "procurement"),
    ("reporting_currency", "reporting"),
)


# ── Context helpers ──────────────────────────────────────────────────────────


def _payload(context: ValidationContext) -> dict[str, Any]:
    """The context payload as a dict (or an empty one)."""
    data = context.data
    return data if isinstance(data, dict) else {}


def _block(context: ValidationContext, key: str) -> dict[str, Any] | None:
    """One named sub-dict of the payload, or None when absent or malformed."""
    value = _payload(context).get(key)
    return value if isinstance(value, dict) else None


def _quotes(rate_set: dict[str, Any] | None) -> dict[str, Any]:
    """The ``{currency: rate}`` mapping carried on a rate-set block."""
    if rate_set is None:
        return {}
    quotes = rate_set.get("quotes")
    return quotes if isinstance(quotes, dict) else {}


def _as_decimal(value: object) -> Decimal | None:
    """Parse a rate to Decimal, or None when it is not a number at all."""
    if isinstance(value, Decimal):
        return value
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _as_date(value: object) -> date | None:
    """Parse an ISO date string, or None."""
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _rate_set_label(rate_set: dict[str, Any]) -> str:
    """A human-facing name for a rate set: base, date and where it came from."""
    base = str(rate_set.get("base_currency") or "?")
    when = str(rate_set.get("rate_date") or "?")
    source = str(rate_set.get("source") or "?")
    return f"{base} rates for {when} from {source}"


def _result(
    rule: ValidationRule,
    passed: bool,
    message: str,
    *,
    element_ref: str | None = None,
    suggestion: str | None = None,
    details: dict[str, Any] | None = None,
) -> RuleResult:
    """Build a RuleResult carrying the rule's own id / name / severity / category."""
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=element_ref,
        suggestion=suggestion,
        details=details or {},
    )


# ── Rule 1: every quote must be usable arithmetic ────────────────────────────


class FxQuoteIntegrity(ValidationRule):
    """Every quote carries a real currency code and a strictly positive rate."""

    rule_id = "fx.quote_integrity"
    name = "FX Quotes Are Usable"
    standard = "fx"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "Each quote must name a three-letter currency other than the base and carry a positive rate."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        rate_set = _block(context, "rate_set")
        quotes = _quotes(rate_set)
        if rate_set is None or not quotes:
            return []
        base = str(rate_set.get("base_currency") or "").upper()
        set_ref = str(rate_set.get("id") or "")
        results: list[RuleResult] = []
        for code, raw in sorted(quotes.items()):
            currency = str(code).upper()
            problems: list[str] = []
            if len(currency) != 3 or not currency.isalpha():
                problems.append(f"'{code}' is not a three-letter currency code")
            elif currency == base:
                problems.append(f"the set is quoted against {base}, so {base} cannot also be a quote in it")
            rate = _as_decimal(raw)
            if rate is None:
                problems.append(f"the rate '{raw}' is not a number")
            elif rate <= 0:
                problems.append(f"the rate {rate} is not positive, so it cannot be divided by")
            if not problems:
                results.append(_result(self, True, "OK", element_ref=f"{set_ref}:{currency}"))
                continue
            results.append(
                _result(
                    self,
                    False,
                    f"Quote {currency} in {_rate_set_label(rate_set)} is unusable: {'; '.join(problems)}.",
                    element_ref=f"{set_ref}:{currency}",
                    suggestion="Correct the rate at its source and re-import the set, or remove the quote.",
                    details={"currency": currency, "rate": str(raw), "problems": problems},
                )
            )
        return results


# ── Rule 2: a quote that jumped needs a human ────────────────────────────────


class FxQuoteMovement(ValidationRule):
    """No quote may move further than tolerated against the set it supersedes."""

    rule_id = "fx.quote_movement"
    name = "FX Quote Movement Within Tolerance"
    standard = "fx"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "A quote that jumped sharply against the previous set usually means a bad figure, not a bad market."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        rate_set = _block(context, "rate_set")
        previous = _block(context, "previous_rate_set")
        current_quotes = _quotes(rate_set)
        previous_quotes = _quotes(previous)
        if rate_set is None or previous is None or not current_quotes or not previous_quotes:
            # Nothing to compare against: the first set ever ingested has no
            # predecessor, and reporting that as a pass would vouch for figures
            # this rule never examined.
            return []

        tolerance = _as_decimal(context.metadata.get("max_quote_move_pct")) or DEFAULT_MAX_QUOTE_MOVE_PCT
        set_ref = str(rate_set.get("id") or "")
        results: list[RuleResult] = []
        for code in sorted(set(current_quotes) & set(previous_quotes)):
            now = _as_decimal(current_quotes.get(code))
            before = _as_decimal(previous_quotes.get(code))
            # A non-numeric or non-positive rate is rule 1's finding; comparing
            # against it here would report one mistake twice.
            if now is None or before is None or before <= 0 or now <= 0:
                continue
            move_pct = (now - before) / before * Decimal(100)
            if move_pct.copy_abs() <= tolerance:
                results.append(_result(self, True, "OK", element_ref=f"{set_ref}:{code}"))
                continue
            direction = "up" if move_pct > 0 else "down"
            results.append(
                _result(
                    self,
                    False,
                    (
                        f"{code} moved {direction} {move_pct.copy_abs():.1f}% against "
                        f"{_rate_set_label(previous)} ({before} to {now}), beyond the {tolerance}% tolerance."
                    ),
                    element_ref=f"{set_ref}:{code}",
                    suggestion=(
                        "Check the figure against its source before pricing with it; "
                        "a misplaced decimal looks exactly like this."
                    ),
                    details={
                        "currency": code,
                        "previous_rate": str(before),
                        "current_rate": str(now),
                        "move_pct": str(move_pct.quantize(Decimal("0.01"))),
                        "tolerance_pct": str(tolerance),
                    },
                )
            )
        return results


# ── Rule 3: the project's own currencies must be convertible ─────────────────


class FxPolicyCurrencyCoverage(ValidationRule):
    """Every currency the project declares must be convertible with its rates."""

    rule_id = "fx.policy_currency_coverage"
    name = "Project Currencies Covered By Rates"
    standard = "fx"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "The estimating, procurement and reporting currencies must all be quoted by the backing rate set."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        policy = _block(context, "policy")
        rate_set = _block(context, "rate_set")
        if policy is None or rate_set is None:
            return []
        quotes = _quotes(rate_set)
        base = str(rate_set.get("base_currency") or "").upper()
        available = {str(code).upper() for code in quotes} | ({base} if base else set())
        if not available:
            return []
        project_ref = str(policy.get("project_id") or "")
        results: list[RuleResult] = []
        for field, role in POLICY_CURRENCY_FIELDS:
            currency = str(policy.get(field) or "").upper()
            if not currency:
                results.append(
                    _result(
                        self,
                        False,
                        f"The project has no {role} currency set.",
                        element_ref=project_ref,
                        suggestion=f"Choose a {role} currency in the project's FX policy.",
                        details={"field": field, "role": role},
                    )
                )
                continue
            if currency in available:
                results.append(_result(self, True, "OK", element_ref=project_ref))
                continue
            results.append(
                _result(
                    self,
                    False,
                    (
                        f"The {role} currency {currency} is not quoted by {_rate_set_label(rate_set)}, "
                        "so figures in it cannot be converted."
                    ),
                    element_ref=project_ref,
                    suggestion=(
                        f"Record a rate for {currency} in that set, or change the {role} currency to one it quotes."
                    ),
                    details={
                        "field": field,
                        "role": role,
                        "currency": currency,
                        "available_count": len(available),
                    },
                )
            )
        return results


# ── Rule 4: a pin must actually hold ─────────────────────────────────────────


class FxPinnedSetResolvable(ValidationRule):
    """A pinned project must name a rate set that exists and is locked."""

    rule_id = "fx.pinned_set_resolvable"
    name = "Pinned Rate Set Holds"
    standard = "fx"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "A project pinned to a rate set needs that set to exist and to be locked against further edits."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        policy = _block(context, "policy")
        if policy is None or str(policy.get("rate_mode") or "") != RATE_MODE_PINNED:
            # A project on live rates has no pin to check.
            return []
        project_ref = str(policy.get("project_id") or "")
        pinned_id = str(policy.get("pinned_rate_set_id") or "")
        if not pinned_id:
            return [
                _result(
                    self,
                    False,
                    "The project is set to use a pinned rate set but no set is named.",
                    element_ref=project_ref,
                    suggestion="Pick the rate set to pin to, or put the project back on live rates.",
                    details={"rate_mode": RATE_MODE_PINNED},
                )
            ]

        rate_set = _block(context, "rate_set")
        if rate_set is None or str(rate_set.get("id") or "") != pinned_id:
            return [
                _result(
                    self,
                    False,
                    f"The pinned rate set {pinned_id} could not be resolved, so the project cannot be priced.",
                    element_ref=project_ref,
                    suggestion="Pin to a rate set that is still on file, or put the project back on live rates.",
                    details={"pinned_rate_set_id": pinned_id},
                )
            ]

        if not bool(rate_set.get("is_locked")):
            return [
                _result(
                    self,
                    False,
                    (
                        f"The project is pinned to {_rate_set_label(rate_set)}, but that set is not locked, "
                        "so a refresh can still rewrite it and move the estimate."
                    ),
                    element_ref=project_ref,
                    suggestion="Lock the pinned rate set so the figures it produced can be reproduced.",
                    details={"pinned_rate_set_id": pinned_id, "is_locked": False},
                )
            ]

        return [_result(self, True, "OK", element_ref=project_ref)]


# ── Rule 5: rates go off ─────────────────────────────────────────────────────


class FxRateFreshness(ValidationRule):
    """The backing rate set must be within the project's staleness tolerance."""

    rule_id = "fx.rate_freshness"
    name = "FX Rates Within Tolerance Age"
    standard = "fx"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "Rates older than the project tolerates quietly misprice every figure converted with them."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        policy = _block(context, "policy")
        rate_set = _block(context, "rate_set")
        if policy is None or rate_set is None:
            return []
        rate_date = _as_date(rate_set.get("rate_date"))
        as_of = _as_date(_payload(context).get("as_of"))
        if rate_date is None or as_of is None:
            return []
        # A pinned project is deliberately using old rates; that is the point of
        # pinning, and warning about it would train people to ignore the light.
        if str(policy.get("rate_mode") or "") == RATE_MODE_PINNED:
            return []

        tolerance_days = policy.get("max_rate_age_days")
        tolerance = int(tolerance_days) if isinstance(tolerance_days, int) else 30
        age_days = (as_of - rate_date).days
        project_ref = str(policy.get("project_id") or "")
        if age_days <= tolerance:
            return [_result(self, True, "OK", element_ref=project_ref)]
        return [
            _result(
                self,
                False,
                (
                    f"The project is pricing against {_rate_set_label(rate_set)}, which is {age_days} days old; "
                    f"the project tolerates {tolerance}."
                ),
                element_ref=project_ref,
                suggestion="Refresh the rates, or raise the tolerance if the project genuinely works this way.",
                details={
                    "rate_date": rate_date.isoformat(),
                    "as_of": as_of.isoformat(),
                    "age_days": age_days,
                    "max_rate_age_days": tolerance,
                },
            )
        ]


# ── Registration ─────────────────────────────────────────────────────────────

_FX_RULES: tuple[ValidationRule, ...] = (
    FxQuoteIntegrity(),
    FxQuoteMovement(),
    FxPolicyCurrencyCoverage(),
    FxPinnedSetResolvable(),
    FxRateFreshness(),
)


def register_fx_rules() -> None:
    """Register the FX rules with the core rule registry.

    Idempotent - the registry overwrites a rule by id, so a re-import or hot
    reload re-registers cleanly. Called from the module ``on_startup`` hook,
    which is what makes ``fx`` a reachable rule set rather than a name nothing
    answers to.
    """
    for rule in _FX_RULES:
        rule_registry.register(rule, [FX_RULE_SET])
    logger.debug("Registered %d fx validation rules", len(_FX_RULES))
