# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site preparation validation rules (rule set ``site_prep``).

Rules run over a plain dict built by the service. An item is checked as::

    {"item": {"id", "status", "is_gate", "responsible_party", "due_date", "completed_date", "notes"}}

and the mobilisation plan as::

    {"plan": {"id", "status", "target_start_date"}}

A not-yet-started item or a draft plan passes with its owner and dates still to be filled in.
"""

from __future__ import annotations

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, blank, section
from app.core.validation.quality_rules import latest_local_day, parse_day

SITE_PREP_RULE_SET = "site_prep"

ITEM_FIELDS = ("status", "is_gate", "responsible_party", "due_date", "completed_date", "notes")
PLAN_FIELDS = ("status", "target_start_date")

_OPEN_GATE_STATUSES = frozenset({"not_started", "in_progress", "blocked"})


class _SitePrepRule(MoneyRule):
    standard = SITE_PREP_RULE_SET
    message_section = "site_prep"


class CompletedNotInFutureRule(_SitePrepRule):
    """Work cannot have been completed on a day that has not come."""

    rule_id = "site_prep.completed_not_in_future"
    name = "Readiness item completion is not in the future"
    description = "completed_date must be no later than today"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        item = section(context, "item")
        ref = str(item.get("id", ""))
        day = parse_day(item.get("completed_date"))
        if day is not None and day > latest_local_day(context):
            return [self.fail(context, "completed_in_future", ref=ref, date=day.isoformat())]
        return [self.ok(ref)]


class ReadyItemDatedRule(_SitePrepRule):
    """A ready item records when it became ready."""

    rule_id = "site_prep.ready_item_dated"
    name = "Ready item has a completion date"
    severity = Severity.WARNING
    description = "an item with status ready should carry its completed_date"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        item = section(context, "item")
        ref = str(item.get("id", ""))
        if item.get("status") == "ready" and blank(item.get("completed_date")):
            return [self.fail(context, "ready_undated", ref=ref)]
        return [self.ok(ref)]


class GateItemOwnedRule(_SitePrepRule):
    """A commencement gate item that is still open has somebody answering for it."""

    rule_id = "site_prep.gate_item_owned"
    name = "Open gate item has a responsible party"
    severity = Severity.WARNING
    description = "a gate item that is not ready needs a responsible_party"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        item = section(context, "item")
        ref = str(item.get("id", ""))
        if item.get("is_gate") and item.get("status") in _OPEN_GATE_STATUSES and blank(item.get("responsible_party")):
            return [self.fail(context, "gate_item_unowned", ref=ref, status=item.get("status"))]
        return [self.ok(ref)]


class ActivePlanStartRule(_SitePrepRule):
    """A plan that is under way or done states the start date it works towards."""

    rule_id = "site_prep.active_plan_start_date"
    name = "Active mobilisation plan has a target start date"
    description = "an active or complete plan needs its target_start_date"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        plan = section(context, "plan")
        ref = str(plan.get("id", ""))
        if plan.get("status") in ("active", "complete") and blank(plan.get("target_start_date")):
            return [self.fail(context, "plan_start_missing", ref=ref, status=plan.get("status"))]
        return [self.ok(ref)]


SITE_PREP_RULES = (
    CompletedNotInFutureRule,
    ReadyItemDatedRule,
    GateItemOwnedRule,
    ActivePlanStartRule,
)


def register_site_prep_validation_rules() -> None:
    """Register the site preparation rules with the platform rule registry."""
    for rule_class in SITE_PREP_RULES:
        rule_registry.register(rule_class(), [SITE_PREP_RULE_SET])


__all__ = ["SITE_PREP_RULES", "SITE_PREP_RULE_SET", "register_site_prep_validation_rules"]
