# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Management-of-change validation rules (rule set ``moc``).

Rules judge the entry as it will be after the write::

    {"moc": {"id", "status", "previous_status", "risk_level", "cost_impact", "currency",
             "schedule_delta_days", "decision_notes"},
     "impacts": [{"id", "cost_impact", "currency", "mitigation"}]}

* ``moc.schedule_days_sane`` (ERROR): the schedule delta is within +-3650 days.
* ``moc.currency_stated`` (WARNING): a cost impact carries a currency.
* ``moc.cost_matches_impacts`` (WARNING): the stated cost equals the impact lines, once lines carry cost.
* ``moc.high_risk_mitigated`` (ERROR): a high or critical change is not accepted without a mitigation.
* ``moc.decline_reason_recorded`` (ERROR): a declined change records why.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.control_rules import ControlRule
from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, currency_of, rows, section, to_dec

MOC_RULE_SET = "moc"
MAX_SCHEDULE_DAYS = Decimal("3650")
_HIGH = frozenset({"high", "critical"})


class ScheduleDaysSaneRule(ControlRule):
    rule_id = "moc.schedule_days_sane"
    name = "Change schedule delta is plausible"
    standard = MOC_RULE_SET
    description = "schedule_delta_days within +-3650 days; a larger figure is a slipped unit"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        moc = section(context, "moc")
        ref = str(moc.get("id", ""))
        bad = self.out_of_range(
            context,
            ref,
            "schedule_delta_days",
            to_dec(moc.get("schedule_delta_days")),
            -MAX_SCHEDULE_DAYS,
            MAX_SCHEDULE_DAYS,
        )
        return [bad] if bad else [self.ok(ref)]


class CurrencyStatedRule(ControlRule):
    rule_id = "moc.currency_stated"
    name = "Change cost impact states a currency"
    standard = MOC_RULE_SET
    severity = Severity.WARNING
    description = "A change with a cost impact names its currency, the same on every impact line"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        moc = section(context, "moc")
        ref = str(moc.get("id", ""))
        lines = rows(context, "impacts")
        carries_money = (to_dec(moc.get("cost_impact")) or 0) != 0 or any(
            (to_dec(i.get("cost_impact")) or 0) != 0 for i in lines
        )
        if not carries_money:
            return [self.ok(ref)]
        found = self.currency_findings(context, ref, currency_of(moc), [currency_of(i) for i in lines])
        for f in found:
            f.severity = Severity.WARNING
        return found or [self.ok(ref)]


class CostMatchesImpactsRule(ControlRule):
    rule_id = "moc.cost_matches_impacts"
    name = "Change cost equals its impact lines"
    standard = MOC_RULE_SET
    severity = Severity.WARNING
    description = "When impact lines carry cost and the entry states one, the entry equals their sum"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        moc = section(context, "moc")
        ref = str(moc.get("id", ""))
        stated = to_dec(moc.get("cost_impact"))
        total = sum((to_dec(i.get("cost_impact")) or Decimal("0") for i in rows(context, "impacts")), Decimal("0"))
        if stated is None or stated == 0 or total == 0:
            return [self.ok(ref)]
        bad = self.total_mismatch(context, ref, "MoC", stated, total, currency_of(moc))
        if bad:
            bad.severity = Severity.WARNING
        return [bad] if bad else [self.ok(ref)]


class HighRiskMitigatedRule(ControlRule):
    rule_id = "moc.high_risk_mitigated"
    name = "High-risk change accepted only with a mitigation"
    standard = MOC_RULE_SET
    description = "Accepting a high or critical change needs a mitigation on at least one impact line"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        moc = section(context, "moc")
        ref = str(moc.get("id", ""))
        if moc.get("status") != "accepted" or moc.get("previous_status") == "accepted":
            return [self.ok(ref)]
        level = str(moc.get("risk_level") or "")
        if level not in _HIGH or any(not blank(i.get("mitigation")) for i in rows(context, "impacts")):
            return [self.ok(ref)]
        return [self.fail(context, "high_risk_unmitigated", ref=ref, risk_level=level)]


class DeclineReasonRecordedRule(ControlRule):
    rule_id = "moc.decline_reason_recorded"
    name = "Declined change records the reason"
    standard = MOC_RULE_SET
    description = "A declined change carries the reason for the decision"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        moc = section(context, "moc")
        ref = str(moc.get("id", ""))
        declining = moc.get("status") == "declined" and moc.get("previous_status") != "declined"
        if declining and blank(moc.get("decision_notes")):
            return [self.fail(context, "decline_reason_missing", ref=ref)]
        return [self.ok(ref)]


MOC_RULES = (
    ScheduleDaysSaneRule,
    CurrencyStatedRule,
    CostMatchesImpactsRule,
    HighRiskMitigatedRule,
    DeclineReasonRecordedRule,
)


def register_moc_validation_rules() -> None:
    """Register the management-of-change rules with the platform rule registry."""
    for rule_class in MOC_RULES:
        rule_registry.register(rule_class(), [MOC_RULE_SET])
