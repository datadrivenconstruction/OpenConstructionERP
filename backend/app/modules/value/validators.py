# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Value-module validation rules (rule set ``value``): the hours-saved minute factors.

Rules run over a plain dict context built by the caller::

    {"factors": [{"module", "action", "minutes", "default_minutes", "known"}]}

``known`` is true when the pair has a seed default; ``default_minutes`` is that default (or ``None``).
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, rows, to_dec

VALUE_RULE_SET = "value"

#: One saved action rarely saves more than a working day; above this the figure is probably hours typed as minutes.
WORKDAY_MINUTES = Decimal("480")


class _FactorRule(MoneyRule):
    standard = VALUE_RULE_SET
    message_section = "value"
    own_message_keys = frozenset({"factor_duplicate", "factor_unknown_action", "factor_over_workday"})


def _ref(row: dict) -> str:
    return f"{row.get('module', '')}.{row.get('action', '')}"


class FactorPairUniqueRule(_FactorRule):
    """Each module and action pair appears once in a batch."""

    rule_id = "value.factor_pair_unique"
    name = "Each minute factor is set once per update"
    description = "the same module/action pair twice in one update is ambiguous"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        seen: set[tuple[str, str]] = set()
        out: list[RuleResult] = []
        for row in rows(context, "factors"):
            key = (str(row.get("module", "")), str(row.get("action", "")))
            if key in seen:
                out.append(self.fail(context, "factor_duplicate", ref=_ref(row), module=key[0], action=key[1]))
            seen.add(key)
        return out or [self.ok()]


class FactorKnownActionRule(_FactorRule):
    """The factor is for an action the platform records."""

    rule_id = "value.factor_action_known"
    name = "Minute factor names a recorded action"
    severity = Severity.WARNING
    description = "an override for a module/action pair without a seed default is never used by the hours-saved figure"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = [
            self.fail(context, "factor_unknown_action", ref=_ref(r), module=r.get("module"), action=r.get("action"))
            for r in rows(context, "factors")
            if not r.get("known")
        ]
        return out or [self.ok()]


class FactorWithinWorkdayRule(_FactorRule):
    """One action does not save more than a working day."""

    rule_id = "value.factor_within_workday"
    name = "Minute factor is within a working day"
    severity = Severity.WARNING
    description = "more than 480 minutes saved per action usually means hours were typed as minutes"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for r in rows(context, "factors"):
            minutes = to_dec(r.get("minutes"))
            if minutes is not None and minutes > WORKDAY_MINUTES:
                out.append(self.fail(context, "factor_over_workday", ref=_ref(r), minutes=minutes, max=WORKDAY_MINUTES))
        return out or [self.ok()]


VALUE_RULES = (FactorPairUniqueRule, FactorKnownActionRule, FactorWithinWorkdayRule)


def register_value_validation_rules() -> None:
    """Register the value rules with the platform rule registry."""
    for rule_class in VALUE_RULES:
        rule_registry.register(rule_class(), [VALUE_RULE_SET])


__all__ = ["VALUE_RULES", "VALUE_RULE_SET", "WORKDAY_MINUTES", "register_value_validation_rules"]
