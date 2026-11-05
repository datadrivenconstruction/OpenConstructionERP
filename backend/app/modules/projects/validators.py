# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project register validation rules (rule set ``projects``).

Rules run over a plain dict built by the service, one record under one key::

    {"project": {"id", "planned_start_date", "planned_end_date", "actual_start_date",
                 "actual_end_date", "contract_value", "budget_estimate", "contingency_pct",
                 "gross_floor_area", "currency"}}

Dates and amounts are free text on the project form (the schema already refuses malformed amounts), so
the rules read them leniently: a value that is absent is never a finding, and a date that cannot be
read is left alone.
"""

from __future__ import annotations

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section, to_dec
from app.core.validation.quality_rules import QualityRule, latest_local_day, parse_day

PROJECTS_RULE_SET = "projects"

PROJECT_FIELDS = (
    "planned_start_date",
    "planned_end_date",
    "actual_start_date",
    "actual_end_date",
    "contract_value",
    "budget_estimate",
    "contingency_pct",
    "currency",
)


class _ProjectRule(QualityRule):
    standard = PROJECTS_RULE_SET
    message_section = "projects"


class PlannedDatesOrderRule(_ProjectRule):
    """The planned finish is not before the planned start."""

    rule_id = "projects.planned_dates_order"
    name = "Planned finish is not before planned start"
    description = "planned_end_date must not be before planned_start_date"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        p = section(context, "project")
        ref = str(p.get("id", ""))
        start, end = parse_day(p.get("planned_start_date")), parse_day(p.get("planned_end_date"))
        if start is not None and end is not None and end < start:
            return [self.fail(context, "planned_dates_order", ref=ref, start=start.isoformat(), end=end.isoformat())]
        return [self.ok(ref)]


class ActualDatesOrderRule(_ProjectRule):
    """The actual finish is not before the actual start."""

    rule_id = "projects.actual_dates_order"
    name = "Actual finish is not before actual start"
    description = "actual_end_date must not be before actual_start_date"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        p = section(context, "project")
        ref = str(p.get("id", ""))
        start, end = parse_day(p.get("actual_start_date")), parse_day(p.get("actual_end_date"))
        if start is not None and end is not None and end < start:
            return [self.fail(context, "actual_dates_order", ref=ref, start=start.isoformat(), end=end.isoformat())]
        return [self.ok(ref)]


class ActualEndNeedsStartRule(_ProjectRule):
    """A project cannot have finished before it has started."""

    rule_id = "projects.actual_end_needs_start"
    name = "Actual finish has an actual start"
    description = "actual_end_date requires actual_start_date"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        p = section(context, "project")
        ref = str(p.get("id", ""))
        end = parse_day(p.get("actual_end_date"))
        if end is not None and parse_day(p.get("actual_start_date")) is None:
            return [self.fail(context, "actual_end_without_start", ref=ref, end=end.isoformat())]
        return [self.ok(ref)]


class ActualDatesNotFutureRule(_ProjectRule):
    """An actual start or finish has already happened."""

    rule_id = "projects.actual_not_in_future"
    name = "Actual dates are not in the future"
    severity = Severity.WARNING
    description = "actual_start_date and actual_end_date should not be after today"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        p = section(context, "project")
        ref = str(p.get("id", ""))
        limit = latest_local_day(context)
        out = []
        for name in ("actual_start_date", "actual_end_date"):
            day = parse_day(p.get(name))
            if day is not None and day > limit:
                out.append(self.fail(context, "actual_in_future", ref=ref, field=name, date=day.isoformat()))
        return out or [self.ok(ref)]


class MoneyNeedsCurrencyRule(_ProjectRule):
    """A project with a contract value or budget states the currency of those figures."""

    rule_id = "projects.money_has_currency"
    name = "Project money has a currency"
    severity = Severity.WARNING
    description = "a contract_value or budget_estimate above zero requires a currency"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        p = section(context, "project")
        ref = str(p.get("id", ""))
        if blank(p.get("currency")):
            for name in ("contract_value", "budget_estimate"):
                value = to_dec(p.get(name))
                if value is not None and value > 0:
                    return [self.fail(context, "money_without_currency", ref=ref, field=name, value=value)]
        return [self.ok(ref)]


class BudgetNeedsContingencyRule(_ProjectRule):
    """A budget carries a contingency allowance, even if the allowance is nil."""

    rule_id = "projects.budget_has_contingency"
    name = "Budget states its contingency"
    severity = Severity.WARNING
    description = "a budget_estimate above zero should come with a contingency_pct"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        p = section(context, "project")
        ref = str(p.get("id", ""))
        budget = to_dec(p.get("budget_estimate"))
        if budget is not None and budget > 0 and blank(p.get("contingency_pct")):
            return [self.fail(context, "contingency_missing", ref=ref, budget=budget)]
        return [self.ok(ref)]


PROJECTS_RULES = (
    PlannedDatesOrderRule,
    ActualDatesOrderRule,
    ActualEndNeedsStartRule,
    ActualDatesNotFutureRule,
    MoneyNeedsCurrencyRule,
    BudgetNeedsContingencyRule,
)


def register_projects_validation_rules() -> None:
    """Register the project register rules with the platform rule registry."""
    for rule_class in PROJECTS_RULES:
        rule_registry.register(rule_class(), [PROJECTS_RULE_SET])


__all__ = ["PROJECTS_RULES", "PROJECTS_RULE_SET", "PROJECT_FIELDS", "register_projects_validation_rules"]
