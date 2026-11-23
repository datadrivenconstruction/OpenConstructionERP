# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project intelligence validation rules (rule set ``project_intelligence``).

The forecast is a figure somebody steers a project by, so the rules check that
it is internally consistent before it is shown. They run over the plain dict of
the finished forecast::

    {"forecast": {"project_id", "currency",
                  "cost": {"available", "currency", "bac", "ev", "ac", "pv", "cpi", "spi", "eac", "etc", "vac"},
                  "schedule": {"available", "planned_pct_complete", "actual_pct_complete", "finish_variance_days"},
                  "risk": {"score", "confidence"}}}

A section that reports itself unavailable (no EVM snapshot, no dated activities) carries no
figures, so no rule fires on it. Messages come from the shared ``money`` section.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.money import money_quantum
from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MAX_SANE_AMOUNT, MoneyRule, currency_of, section, to_dec

PROJECT_INTELLIGENCE_RULE_SET = "project_intelligence"

#: A cost or schedule performance index above this is a slipped decimal, not a project that is ten times ahead.
MAX_PLAUSIBLE_INDEX = Decimal("10")
#: A forecast finish more than ten years from the baseline is a date slip.
MAX_PLAUSIBLE_VARIANCE_DAYS = Decimal("3650")


class _IntelligenceRule(MoneyRule):
    standard = PROJECT_INTELLIGENCE_RULE_SET


def _forecast(context: ValidationContext) -> dict:
    return section(context, "forecast")


def _sub(context: ValidationContext, key: str) -> dict:
    value = _forecast(context).get(key)
    return value if isinstance(value, dict) else {}


def _ref(context: ValidationContext) -> str:
    return str(_forecast(context).get("project_id", ""))


def _cost(context: ValidationContext) -> dict | None:
    """The cost section when it carries figures, else ``None``."""
    cost = _sub(context, "cost")
    return cost if cost.get("available") else None


def _currency(context: ValidationContext, cost: dict) -> str:
    return currency_of(cost) or currency_of(_forecast(context))


class EvmArithmeticRule(_IntelligenceRule):
    """ETC and VAC follow from EAC, AC and BAC."""

    rule_id = "project_intelligence.evm_ties"
    name = "Forecast earned-value figures tie"
    description = "ETC equals EAC minus AC, and VAC equals BAC minus EAC"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        cost = _cost(context)
        if cost is None:
            return [self.ok(ref)]
        currency = _currency(context, cost)
        # Each figure is rounded on its own, so the identity may be off by one minor unit per side.
        tolerance = money_quantum(currency) * 2
        bac, eac, ac = (to_dec(cost.get(k)) for k in ("bac", "eac", "ac"))
        out: list[RuleResult] = []
        for label, stated, expected in (
            ("ETC", to_dec(cost.get("etc")), None if eac is None or ac is None else eac - ac),
            ("VAC", to_dec(cost.get("vac")), None if bac is None or eac is None else bac - eac),
        ):
            if stated is None or expected is None:
                continue
            bad = self.total_mismatch(context, ref, label, stated, expected, currency, tolerance)
            if bad:
                out.append(bad)
        return out or [self.ok(ref)]


class CurrencyStatedRule(_IntelligenceRule):
    """A forecast that carries money states the currency it is in."""

    rule_id = "project_intelligence.currency_stated"
    name = "Forecast currency stated"
    description = "A cost forecast with a non-zero budget needs the project currency"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        cost = _cost(context)
        if cost is None:
            return [self.ok(ref)]
        has_money = any((to_dec(cost.get(k)) or 0) != 0 for k in ("bac", "ev", "ac", "pv"))
        if has_money and not _currency(context, cost):
            return [self.fail(context, "currency_present", ref=ref)]
        return [self.ok(ref)]


class EvmInputsSaneRule(_IntelligenceRule):
    """The snapshot amounts are not negative and not a unit slip."""

    rule_id = "project_intelligence.evm_inputs_sane"
    name = "Earned-value inputs are sane"
    description = "BAC, EV, AC and PV lie between zero and a figure no construction project reaches"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        cost = _cost(context)
        if cost is None:
            return [self.ok(ref)]
        out = [
            bad
            for key in ("bac", "ev", "ac", "pv")
            if (bad := self.out_of_range(context, ref, key.upper(), to_dec(cost.get(key)), Decimal(0), MAX_SANE_AMOUNT))
        ]
        return out or [self.ok(ref)]


class EarnedWithinBudgetRule(_IntelligenceRule):
    """Work earned or planned beyond the whole budget points at a stale or mistyped baseline."""

    rule_id = "project_intelligence.earned_within_budget"
    name = "Earned and planned value within the budget"
    severity = Severity.WARNING
    description = "EV or PV above BAC means the budget at completion no longer matches the progress"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        cost = _cost(context)
        bac = to_dec(cost.get("bac")) if cost else None
        if cost is None or bac is None or bac <= 0:
            return [self.ok(ref)]
        out = [
            bad
            for key in ("ev", "pv")
            if (bad := self.out_of_range(context, ref, key.upper(), to_dec(cost.get(key)), Decimal(0), bac))
        ]
        return out or [self.ok(ref)]


class PerformanceIndexRule(_IntelligenceRule):
    """CPI and SPI stay inside a band a real project reaches."""

    rule_id = "project_intelligence.index_plausible"
    name = "Performance indices are plausible"
    severity = Severity.WARNING
    description = "CPI or SPI above 10 usually means a slipped decimal in actual cost or planned value"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        cost = _cost(context)
        if cost is None:
            return [self.ok(ref)]
        out = [
            bad
            for key in ("cpi", "spi")
            if (
                bad := self.out_of_range(
                    context, ref, key.upper(), to_dec(cost.get(key)), Decimal(0), MAX_PLAUSIBLE_INDEX
                )
            )
        ]
        return out or [self.ok(ref)]


class RiskScoreRule(_IntelligenceRule):
    """The risk score and its confidence are shares between 0 and 1."""

    rule_id = "project_intelligence.risk_score_bounded"
    name = "Risk score is bounded"
    description = "Score and confidence lie between 0 and 1"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        risk = _sub(context, "risk")
        out = [
            bad
            for key in ("score", "confidence")
            if (bad := self.out_of_range(context, ref, key, to_dec(risk.get(key)), Decimal(0), Decimal(1)))
        ]
        return out or [self.ok(ref)]


class ScheduleProgressRule(_IntelligenceRule):
    """Percent complete is a percentage, and the projected finish slip is a believable number of days."""

    rule_id = "project_intelligence.schedule_bounded"
    name = "Schedule projection is bounded"
    description = "Planned and actual percent complete lie between 0 and 100; finish variance within ten years"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        schedule = _sub(context, "schedule")
        if not schedule.get("available"):
            return [self.ok(ref)]
        out = [
            bad
            for key in ("planned_pct_complete", "actual_pct_complete")
            if (bad := self.out_of_range(context, ref, key, to_dec(schedule.get(key)), Decimal(0), Decimal(100)))
        ]
        bad = self.out_of_range(
            context,
            ref,
            "finish_variance_days",
            to_dec(schedule.get("finish_variance_days")),
            -MAX_PLAUSIBLE_VARIANCE_DAYS,
            MAX_PLAUSIBLE_VARIANCE_DAYS,
        )
        if bad:
            out.append(bad)
        return out or [self.ok(ref)]


PROJECT_INTELLIGENCE_RULES = (
    EvmArithmeticRule,
    CurrencyStatedRule,
    EvmInputsSaneRule,
    EarnedWithinBudgetRule,
    PerformanceIndexRule,
    RiskScoreRule,
    ScheduleProgressRule,
)


def register_project_intelligence_validation_rules() -> None:
    """Register the project intelligence rules with the platform rule registry."""
    for rule_class in PROJECT_INTELLIGENCE_RULES:
        rule_registry.register(rule_class(), [PROJECT_INTELLIGENCE_RULE_SET])


__all__ = [
    "PROJECT_INTELLIGENCE_RULES",
    "PROJECT_INTELLIGENCE_RULE_SET",
    "register_project_intelligence_validation_rules",
]
