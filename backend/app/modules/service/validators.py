# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service & Maintenance validation rules (rule set ``service``).

Rules run over a plain dict context built by the caller::

    {"contract": {"id", "period_start", "period_end", "status", "value", "currency"},
     "work_order": {"id", "status", "currency"},
     "items": [{"id", "quantity", "unit_rate", "total"}]}

``metadata["today"]`` (ISO date) overrides the reference day.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, blank, currency_of, rows, section, to_dec
from app.core.validation.quality_rules import parse_day, today_of

SERVICE_RULE_SET = "service"

#: Work-order states in which the job is done and a bill follows.
_DONE_STATES = frozenset({"completed", "verified", "billed", "closed"})


class _ServiceRule(MoneyRule):
    standard = SERVICE_RULE_SET
    message_section = "service"
    own_message_keys = frozenset({"contract_date_invalid", "contract_lapsed", "completed_without_items"})


class ContractDatesRule(_ServiceRule):
    """The contract period is made of real calendar dates in order."""

    rule_id = "service.contract_dates_valid"
    name = "Service contract period is valid"
    description = "period_start and period_end must be real dates, the end not before the start"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        c = section(context, "contract")
        ref = str(c.get("id", ""))
        if not c:
            return [self.ok(ref)]
        days = {}
        for field in ("period_start", "period_end"):
            days[field] = parse_day(c.get(field))
            if days[field] is None and not blank(c.get(field)):
                return [self.fail(context, "contract_date_invalid", ref=ref, field=field, value=c.get(field))]
        start, end = days["period_start"], days["period_end"]
        if start and end and end < start:
            return [self.fail(context, "dates_ordered", ref=ref, earlier=start.isoformat(), later=end.isoformat())]
        return [self.ok(ref)]


class ContractCurrencyRule(_ServiceRule):
    """A contract with a value states its currency."""

    rule_id = "service.contract_currency_stated"
    name = "Service contract states its currency"
    severity = Severity.WARNING
    description = "value above zero needs a currency, or the figure cannot be summed or invoiced"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        c = section(context, "contract")
        ref = str(c.get("id", ""))
        value = to_dec(c.get("value"))
        if value is not None and value > 0 and not currency_of(c):
            return [self.fail(context, "currency_present", ref=ref)]
        return [self.ok(ref)]


class ContractLapsedRule(_ServiceRule):
    """An active contract has not run past its end date."""

    rule_id = "service.contract_not_lapsed"
    name = "Active service contract is within its period"
    severity = Severity.WARNING
    description = "status active with a period_end in the past: expire or renew the contract"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        c = section(context, "contract")
        ref = str(c.get("id", ""))
        end = parse_day(c.get("period_end"))
        if c.get("status") == "active" and end is not None and end < today_of(context):
            return [self.fail(context, "contract_lapsed", ref=ref, date=end.isoformat())]
        return [self.ok(ref)]


class WorkOrderItemTotalRule(_ServiceRule):
    """A line total typed by hand agrees with quantity times rate."""

    rule_id = "service.work_order_item_total"
    name = "Work order line total equals quantity x rate"
    description = "an explicit item total must match quantity x unit rate within a cent"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        wo = section(context, "work_order")
        ref = str(wo.get("id", ""))
        currency = currency_of(wo)
        out = []
        for item in rows(context, "items"):
            total, qty, rate = (to_dec(item.get(k)) for k in ("total", "quantity", "unit_rate"))
            if total is None or qty is None or rate is None:
                continue
            bad = self.total_mismatch(context, str(item.get("id", ref)), "line", total, qty * rate, currency)
            if bad:
                out.append(bad)
        return out or [self.ok(ref)]


class CompletedWorkItemsRule(_ServiceRule):
    """Finished work carries the labour and material it bills."""

    rule_id = "service.completed_work_has_items"
    name = "Completed work order has billable lines"
    severity = Severity.WARNING
    description = "a work order completed with no lines, or lines totalling zero, bills nothing"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        wo = section(context, "work_order")
        ref = str(wo.get("id", ""))
        if wo.get("status") not in _DONE_STATES:
            return [self.ok(ref)]
        total = sum((to_dec(i.get("total")) or Decimal("0") for i in rows(context, "items")), Decimal("0"))
        if total <= 0:
            return [self.fail(context, "completed_without_items", ref=ref)]
        return [self.ok(ref)]


SERVICE_RULES = (
    ContractDatesRule,
    ContractCurrencyRule,
    ContractLapsedRule,
    WorkOrderItemTotalRule,
    CompletedWorkItemsRule,
)


def register_service_validation_rules() -> None:
    """Register the service rules with the platform rule registry."""
    for rule_class in SERVICE_RULES:
        rule_registry.register(rule_class(), [SERVICE_RULE_SET])


__all__ = ["SERVICE_RULES", "SERVICE_RULE_SET", "register_service_validation_rules"]
