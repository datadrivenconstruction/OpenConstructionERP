# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service charges validation rules, registered under the ``service_charges`` rule set.

Each rule reads a plain dict built by ``ServiceChargesService.validation_payload``:
``{"association": {...}, "keys": [{"id", "name", "method", "shares": [str]}],
"budget": {...} | None, "duplicate_years": [int], "operation": "demand" | None,
"reconciliation": {...} | None, "currencies": [{"source", "currency"}]}``.

* ``service_charges.key_shares_total`` (ERROR): permille shares add up to exactly 1000,
  custom shares to exactly 100, area shares are all positive; Decimal, no tolerance.
* ``service_charges.demand_needs_approved_budget`` (ERROR): demands are raised only from an
  approved budget.
* ``service_charges.one_budget_per_year`` (ERROR): one budget per association and year.
* ``service_charges.reconciliation_balance`` (ERROR): every unit's balance is exactly its
  demands minus its share of actual costs, and the shares plus the unallocated part add up
  to the actual total.
* ``service_charges.currency_consistent`` (ERROR): budget, demands, cost sources and the
  legal entity all use the association's currency.
"""

from __future__ import annotations

import logging
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
from app.modules.service_charges.apportion import check_shares

logger = logging.getLogger(__name__)

SERVICE_CHARGES_RULE_SET = "service_charges"


def _dec(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("NaN")


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


class _Rule(ValidationRule):
    standard = "service_charges"
    severity = Severity.ERROR

    def _result(self, ref: str, passed: bool, message: str, **details: Any) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message="OK" if passed else message,
            element_ref=ref,
            details={k: str(v) if isinstance(v, Decimal) else v for k, v in details.items()},
        )


class KeySharesTotalRule(_Rule):
    rule_id = "service_charges.key_shares_total"
    name = "Apportionment shares add up exactly"
    category = RuleCategory.CONSISTENCY
    description = "Permille shares add up to 1000, custom shares to 100, area shares are all positive"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for key in _data(context).get("keys") or []:
            shares = [_dec(s) for s in key.get("shares") or []]
            ok, total, expected = check_shares(str(key.get("method")), shares)
            out.append(
                self._result(
                    str(key.get("id") or ""),
                    ok,
                    f"Key '{key.get('name')}': shares add up to {total}, expected {expected or 'all positive'}.",
                    key=key.get("name"),
                    method=key.get("method"),
                    total=total,
                    expected=expected,
                )
            )
        return out


class DemandNeedsApprovedBudgetRule(_Rule):
    rule_id = "service_charges.demand_needs_approved_budget"
    name = "Demands only from an approved budget"
    category = RuleCategory.CONSISTENCY
    description = "Service charge demands may only be raised from an approved budget"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        budget = data.get("budget") or {}
        if data.get("operation") != "demand" or not budget:
            return []
        status = str(budget.get("status"))
        return [
            self._result(
                str(budget.get("id") or ""),
                status == "approved",
                f"The budget is {status}; approve it before raising demands.",
                status=status,
            )
        ]


class OneBudgetPerYearRule(_Rule):
    rule_id = "service_charges.one_budget_per_year"
    name = "One budget per association per year"
    category = RuleCategory.CONSISTENCY
    description = "An association has at most one service charge budget per year"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        dup = [int(y) for y in data.get("duplicate_years") or []]
        ref = str((data.get("association") or {}).get("id") or "")
        return [self._result(ref, not dup, f"More than one budget for year(s) {dup}.", years=dup)]


class ReconciliationBalanceRule(_Rule):
    rule_id = "service_charges.reconciliation_balance"
    name = "Reconciliation balance is exact"
    category = RuleCategory.CONSISTENCY
    description = "Balance per unit equals demands minus the unit's share of actual costs, to the cent"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        rec = _data(context).get("reconciliation")
        if not rec:
            return []
        wrong = [
            str(u.get("unit_ref"))
            for u in rec.get("unit_balances") or []
            if _dec(u.get("balance")) != _dec(u.get("demanded")) - _dec(u.get("actual_share"))
        ]
        shares = sum((_dec(u.get("actual_share")) for u in rec.get("unit_balances") or []), Decimal("0"))
        unalloc = sum((_dec(v) for v in (rec.get("unallocated") or {}).values()), Decimal("0"))
        total = _dec(rec.get("total_actual"))
        passed = not wrong and shares + unalloc == total
        return [
            self._result(
                str(rec.get("id") or ""),
                passed,
                f"Balances do not reconcile: units {wrong}, shares {shares} + unallocated {unalloc} vs actual {total}.",
                units=wrong,
                shares=shares,
                unallocated=unalloc,
                total_actual=total,
            )
        ]


class CurrencyConsistentRule(_Rule):
    rule_id = "service_charges.currency_consistent"
    name = "One currency per association"
    category = RuleCategory.CONSISTENCY
    description = "Budget, demands, cost sources and the legal entity use the association's currency"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        assoc = data.get("association") or {}
        currency = str(assoc.get("currency") or "")
        foreign = [
            f"{c.get('source')}:{c.get('currency')}"
            for c in data.get("currencies") or []
            if c.get("currency") and str(c.get("currency")) != currency
        ]
        return [
            self._result(
                str(assoc.get("id") or ""),
                not foreign,
                f"Amounts in another currency than {currency}: " + ", ".join(foreign),
                currency=currency,
                foreign=foreign,
            )
        ]


_RULES: tuple[ValidationRule, ...] = (
    KeySharesTotalRule(),
    DemandNeedsApprovedBudgetRule(),
    OneBudgetPerYearRule(),
    ReconciliationBalanceRule(),
    CurrencyConsistentRule(),
)


def register_service_charges_validation_rules() -> None:
    """Register the service charges rules under the ``service_charges`` rule set."""
    for rule in _RULES:
        rule_registry.register(rule, [SERVICE_CHARGES_RULE_SET])
    logger.debug("service_charges: registered %d validation rules", len(_RULES))
