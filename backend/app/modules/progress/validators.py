# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Progress validation rules (rule set ``progress``).

Rules judge the reading or plan point being written::

    {"entry": {"id", "percent_complete", "previous_percent", "geo_lat", "geo_lon", "photos", "notes"},
     "plan": {"id", "period_label", "planned_pct", "earlier": [[label, pct]], "later": [[label, pct]]}}

* ``progress.geo_pair_complete`` (ERROR): a position fix has both latitude and longitude.
* ``progress.reading_not_backwards`` (WARNING): a reading is not below the position's last reading.
* ``progress.completion_evidenced`` (WARNING): 100% comes with a photo or a note.
* ``progress.plan_cumulative`` (WARNING): the planned S-curve never falls from one period to the next.
"""

from __future__ import annotations

from app.core.validation.control_rules import ControlRule
from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section, to_dec


class GeoPairCompleteRule(ControlRule):
    rule_id = "progress.geo_pair_complete"
    name = "Progress position fix is complete"
    standard = "progress"
    description = "geo_lat and geo_lon are given together or not at all"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        entry = section(context, "entry")
        ref = str(entry.get("id", ""))
        if (entry.get("geo_lat") is None) != (entry.get("geo_lon") is None):
            return [self.fail(context, "geo_incomplete", ref=ref)]
        return [self.ok(ref)]


class ReadingNotBackwardsRule(ControlRule):
    rule_id = "progress.reading_not_backwards"
    name = "Progress reading does not fall"
    standard = "progress"
    severity = Severity.WARNING
    description = "A reading below the position's previous one is a correction or a mistake; say which"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        entry = section(context, "entry")
        ref = str(entry.get("id", ""))
        new, previous = to_dec(entry.get("percent_complete")), to_dec(entry.get("previous_percent"))
        if new is None or previous is None or new >= previous:
            return [self.ok(ref)]
        return [self.fail(context, "progress_regression", ref=ref, new=new, previous=previous)]


class CompletionEvidencedRule(ControlRule):
    rule_id = "progress.completion_evidenced"
    name = "Completion reading has evidence"
    standard = "progress"
    severity = Severity.WARNING
    description = "A 100% reading carries a photo or a note, because it closes the position for payment"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        entry = section(context, "entry")
        ref = str(entry.get("id", ""))
        done = to_dec(entry.get("percent_complete"))
        if done is None or done < 100 or entry.get("photos") or not blank(entry.get("notes")):
            return [self.ok(ref)]
        return [self.fail(context, "completion_unevidenced", ref=ref)]


class PlanCumulativeRule(ControlRule):
    rule_id = "progress.plan_cumulative"
    name = "Planned S-curve does not fall"
    standard = "progress"
    severity = Severity.WARNING
    description = "A planned cumulative percent is not below an earlier period nor above a later one"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        plan = section(context, "plan")
        ref = str(plan.get("id", ""))
        pct = to_dec(plan.get("planned_pct"))
        if pct is None:
            return [self.ok(ref)]
        label = str(plan.get("period_label", ""))
        for other, other_pct in plan.get("earlier") or []:
            if (to_dec(other_pct) or pct) > pct:
                return [
                    self.fail(context, "plan_order", ref=ref, period=label, pct=pct, other=other, other_pct=other_pct)
                ]
        for other, other_pct in plan.get("later") or []:
            if (to_dec(other_pct) or pct) < pct:
                return [
                    self.fail(context, "plan_order", ref=ref, period=label, pct=pct, other=other, other_pct=other_pct)
                ]
        return [self.ok(ref)]


PROGRESS_RULE_SET = "progress"
PROGRESS_RULES = (GeoPairCompleteRule, ReadingNotBackwardsRule, CompletionEvidencedRule, PlanCumulativeRule)


def register_progress_validation_rules() -> None:
    """Register the progress rules with the platform rule registry."""
    for rule_class in PROGRESS_RULES:
        rule_registry.register(rule_class(), [PROGRESS_RULE_SET])
