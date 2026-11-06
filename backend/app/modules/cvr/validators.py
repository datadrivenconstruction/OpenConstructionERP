# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠CVR validation guards (first-class, pure, DB-free).

Two rules matter for a Cost-Value Reconciliation:

1. **Single currency (hard).** Every line of a report is expressed in the
   report's own currency; a line that declares a different currency is rejected
   outright so totals are never summed across currencies.
2. **Forecast sanity (advisory).** A final forecast should not fall below what
   has already been spent (``cost_to_date``) or earned (``value_to_date``). This
   is a *soft* flag: the service surfaces it on the line and in the summary
   ``warnings`` rather than blocking the write, because an in-progress CVR can
   legitimately carry a not-yet-updated forecast.

Everything here is a pure function so the unit suite asserts on it without a
database or a session.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleResult, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, section


class CvrValidationError(ValueError):
    """Raised when a hard CVR validation rule is violated (single currency)."""


def normalise_currency(code: str | None) -> str:
    """Return an upper-cased, trimmed ISO 4217 code (``""`` when blank)."""
    return (code or "").strip().upper()


def assert_single_currency(report_currency: str | None, incoming_currency: str | None) -> None:
    """Guard: a line (or child record) may only carry the report's currency.

    A blank ``incoming_currency`` inherits the report currency (no conflict). A
    non-blank incoming currency that differs from a non-blank report currency
    raises :class:`CvrValidationError`.
    """
    report = normalise_currency(report_currency)
    incoming = normalise_currency(incoming_currency)
    if incoming and report and incoming != report:
        raise CvrValidationError(
            f"Line currency '{incoming}' does not match report currency '{report}'. "
            "All lines of a CVR report must share one currency."
        )


def forecast_flags(
    *,
    cost_to_date: Decimal,
    value_to_date: Decimal,
    forecast_cost: Decimal,
    forecast_value: Decimal,
) -> list[str]:
    """Return advisory flags when a forecast sits below the position-to-date.

    ``forecast_cost < cost_to_date`` and ``forecast_value < value_to_date`` are
    each surfaced as a soft flag. An empty list means the line looks consistent.
    """
    flags: list[str] = []
    if forecast_cost < cost_to_date:
        flags.append("forecast_cost_below_cost_to_date")
    if forecast_value < value_to_date:
        flags.append("forecast_value_below_value_to_date")
    return flags


CVR_RULE_SET = "cvr"


class CvrCurrencyConsistentRule(MoneyRule):
    """A line states no currency of its own, or the report's currency."""

    standard = CVR_RULE_SET
    rule_id = "cvr.currency_consistent"
    name = "CVR line currency matches the report"
    description = "Every line of a CVR report shares the report currency; a blank line currency inherits it"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        report = normalise_currency(section(context, "report").get("currency"))
        line = normalise_currency(section(context, "line").get("currency"))
        if report and line and report != line:
            ref = str(section(context, "line").get("id", ""))
            return [self.fail(context, "currency_consistent", ref=ref, currencies=", ".join(sorted({report, line})))]
        return [self.ok()]


def register_cvr_validation_rules() -> None:
    """Register the CVR rule set (idempotent)."""
    rule_registry.register(CvrCurrencyConsistentRule(), [CVR_RULE_SET])
