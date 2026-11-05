# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Allowance register validation rules (rule set ``allowances``).

Rules run over a plain dict context built by the service::

    {
        "allowance": {"id", "label", "allowance_type", "held_amount", "currency"},
        "drawdowns": [{"id", "amount", "note"}],
    }

Over-drawing a provisional sum is a real situation, so it is a warning; the
blocking rule is the unit slip that makes a register total meaningless.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MAX_SANE_AMOUNT, MoneyRule, blank, currency_of, rows, section, to_dec

ALLOWANCES_RULE_SET = "allowances"


class _AllowanceRule(MoneyRule):
    standard = ALLOWANCES_RULE_SET
    message_section = "allowances"
    own_message_keys = frozenset({"overdrawn", "drawdown_unexplained"})
    suggestion_key = "allowances.suggestion"


def _ref(context: ValidationContext) -> str:
    return str(section(context, "allowance").get("id", ""))


class AllowanceAmountsInRangeRule(_AllowanceRule):
    """The held amount and every drawdown stay below the unit-slip ceiling."""

    rule_id = "allowances.amounts_in_range"
    name = "Allowance amounts are sane"
    description = "Held amount and drawdowns must be between 0 and 1e12"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        out: list[RuleResult] = []
        bad = self.out_of_range(
            context,
            ref,
            "held_amount",
            to_dec(section(context, "allowance").get("held_amount")),
            Decimal(0),
            MAX_SANE_AMOUNT,
        )
        if bad:
            out.append(bad)
        for d in rows(context, "drawdowns"):
            bad = self.out_of_range(
                context, str(d.get("id") or ref), "amount", to_dec(d.get("amount")), Decimal(0), MAX_SANE_AMOUNT
            )
            if bad:
                out.append(bad)
        return out or [self.ok(ref)]


class AllowanceCurrencyRule(_AllowanceRule):
    """An allowance that carries money states the currency it is held in."""

    rule_id = "allowances.currency_stated"
    name = "Allowance currency stated"
    severity = Severity.WARNING
    description = "A non-zero held amount or drawdown needs a currency, or the register cannot total it"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        allowance = section(context, "allowance")
        ref = _ref(context)
        carries_money = (to_dec(allowance.get("held_amount")) or 0) > 0 or any(
            (to_dec(d.get("amount")) or 0) > 0 for d in rows(context, "drawdowns")
        )
        if carries_money and not currency_of(allowance):
            return [self.fail(context, "currency_present", ref=ref)]
        return [self.ok(ref)]


class AllowanceOverdrawnRule(_AllowanceRule):
    """Drawdowns taken together do not exceed what the allowance holds."""

    rule_id = "allowances.not_overdrawn"
    name = "Allowance is not overdrawn"
    severity = Severity.WARNING
    description = "Drawdowns above the held amount mean the sum was too small and the estimate is short"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        from app.core.currency_registry import sentence_amount  # noqa: PLC0415

        allowance = section(context, "allowance")
        ref = _ref(context)
        held = to_dec(allowance.get("held_amount"))
        drawn = sum((to_dec(d.get("amount")) or Decimal(0) for d in rows(context, "drawdowns")), Decimal(0))
        if held is None or drawn <= held:
            return [self.ok(ref)]
        currency = currency_of(allowance)
        return [
            self.fail(
                context,
                "overdrawn",
                ref=ref,
                label=allowance.get("label") or allowance.get("allowance_type") or "",
                drawn=sentence_amount(drawn, currency),
                held=sentence_amount(held, currency),
                excess=sentence_amount(drawn - held, currency),
            )
        ]


class DrawdownExplainedRule(_AllowanceRule):
    """Each drawdown says where the money went, so the release can be audited."""

    rule_id = "allowances.drawdown_explained"
    name = "Drawdowns carry a reason"
    severity = Severity.WARNING
    description = "A drawdown without a note cannot be traced to a package or instruction"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        count = sum(
            1 for d in rows(context, "drawdowns") if (to_dec(d.get("amount")) or 0) > 0 and blank(d.get("note"))
        )
        if count:
            return [self.fail(context, "drawdown_unexplained", ref=ref, count=count)]
        return [self.ok(ref)]


ALLOWANCES_RULES = (
    AllowanceAmountsInRangeRule,
    AllowanceCurrencyRule,
    AllowanceOverdrawnRule,
    DrawdownExplainedRule,
)


def register_allowances_validation_rules() -> None:
    """Register the allowance rules with the platform rule registry."""
    for rule_class in ALLOWANCES_RULES:
        rule_registry.register(rule_class(), [ALLOWANCES_RULE_SET])
