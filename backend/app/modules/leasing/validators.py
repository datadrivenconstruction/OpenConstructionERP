# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Leasing validation rules, registered under the ``leasing`` rule set.

Each rule reads a plain dict built by the service (see ``LeasingService.validation_payload``):
``{"lease": {...}, "country": "XX" | None, "entity_currency": "EUR" | None,
"overlaps": [codes], "tenant_identifier_schemes": [...]}``.

* ``leasing.end_after_start`` (ERROR): the lease ends after it starts.
* ``leasing.no_overlap`` (ERROR): no other active or notice lease holds the unit in the same period.
* ``leasing.deposit_non_negative`` (ERROR): the deposit is zero or more.
* ``leasing.deposit_within_cap`` (ERROR): the deposit stays within the country cap, when the
  country data publishes one (``lease_rules.json``); no row, no cap.
* ``leasing.currency_matches_entity`` (ERROR): the lease currency is the landlord entity's
  functional currency.
* ``leasing.tenant_identifier`` (ERROR): the tenant carries an identifier the country requires;
  no requirement in the country data, nothing to check.

Messages are English with ``details`` carrying the figures; the UI renders them
from its own keys per ``rule_id``.
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
from app.modules.leasing.country_rules import deposit_cap_months, tenant_identifier_schemes
from app.modules.leasing.schedule import FREQUENCY_MONTHS

logger = logging.getLogger(__name__)

LEASING_RULE_SET = "leasing"


def _dec(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _lease(context: ValidationContext) -> dict[str, Any]:
    data = context.data if isinstance(context.data, dict) else {}
    return dict(data.get("lease") or {})


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


class _LeaseRule(ValidationRule):
    standard = "leasing"
    severity = Severity.ERROR

    def _result(self, context: ValidationContext, passed: bool, message: str, **details: Any) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message="OK" if passed else message,
            element_ref=str(_lease(context).get("id") or ""),
            details={k: str(v) if isinstance(v, Decimal) else v for k, v in details.items()},
        )


class EndAfterStartRule(_LeaseRule):
    rule_id = "leasing.end_after_start"
    name = "Lease ends after it starts"
    category = RuleCategory.STRUCTURE
    description = "The end date of a lease must be after its start date"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        lease = _lease(context)
        start, end = str(lease.get("start_date") or ""), str(lease.get("end_date") or "")
        passed = bool(start and end and end > start)
        return [self._result(context, passed, "The lease must end after it starts.", start=start, end=end)]


class NoOverlapRule(_LeaseRule):
    rule_id = "leasing.no_overlap"
    name = "One active lease per unit per period"
    category = RuleCategory.CONSISTENCY
    description = "No other active or notice lease may hold the same unit in an overlapping period"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        overlaps = [str(c) for c in _data(context).get("overlaps") or []]
        return [
            self._result(
                context,
                not overlaps,
                "Another lease already holds this unit in this period: " + ", ".join(overlaps),
                overlaps=overlaps,
            )
        ]


class DepositNonNegativeRule(_LeaseRule):
    rule_id = "leasing.deposit_non_negative"
    name = "Deposit is not negative"
    category = RuleCategory.STRUCTURE
    description = "The deposit must be zero or more"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        deposit = _dec(_lease(context).get("deposit")) or Decimal("0")
        return [self._result(context, deposit >= 0, "The deposit cannot be negative.", deposit=deposit)]


class DepositWithinCapRule(_LeaseRule):
    rule_id = "leasing.deposit_within_cap"
    name = "Deposit within the country cap"
    category = RuleCategory.COMPLIANCE
    description = "Where the country data publishes a deposit cap in months of rent, the deposit stays within it"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        lease = _lease(context)
        cap = deposit_cap_months(data.get("country"), str(lease.get("lease_kind") or "default"))
        if cap is None:
            return []
        rent = _dec(lease.get("rent_amount")) or Decimal("0")
        months = FREQUENCY_MONTHS.get(str(lease.get("frequency") or "monthly"), 1)
        monthly = rent / Decimal(months)
        limit = (monthly * cap).quantize(Decimal("0.01"))
        deposit = _dec(lease.get("deposit")) or Decimal("0")
        return [
            self._result(
                context,
                deposit <= limit,
                f"The deposit exceeds the cap of {cap} months of rent ({limit}).",
                cap_months=cap,
                limit=limit,
                deposit=deposit,
                country=data.get("country"),
            )
        ]


class CurrencyMatchesEntityRule(_LeaseRule):
    rule_id = "leasing.currency_matches_entity"
    name = "Lease currency is the landlord's currency"
    category = RuleCategory.CONSISTENCY
    description = "The lease is kept in the functional currency of the landlord legal entity"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        entity_currency = _data(context).get("entity_currency")
        if not entity_currency:
            return []
        currency = str(_lease(context).get("currency") or "")
        return [
            self._result(
                context,
                currency == entity_currency,
                f"The lease is in {currency} and the landlord keeps its books in {entity_currency}.",
                currency=currency,
                entity_currency=entity_currency,
            )
        ]


class TenantIdentifierRule(_LeaseRule):
    rule_id = "leasing.tenant_identifier"
    name = "Tenant carries the identifier the country requires"
    category = RuleCategory.COMPLETENESS
    description = "Where the country data requires a tenant identifier, the tenant contact carries one"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        required = tenant_identifier_schemes(data.get("country"))
        if not required:
            return []
        held = {str(s) for s in data.get("tenant_identifier_schemes") or []}
        passed = bool(held & set(required))
        return [
            self._result(
                context,
                passed,
                "The tenant needs one of these identifiers: " + ", ".join(required),
                required=required,
            )
        ]


_RULES: tuple[ValidationRule, ...] = (
    EndAfterStartRule(),
    NoOverlapRule(),
    DepositNonNegativeRule(),
    DepositWithinCapRule(),
    CurrencyMatchesEntityRule(),
    TenantIdentifierRule(),
)


def register_leasing_validation_rules() -> None:
    """Register the leasing rules under the ``leasing`` rule set."""
    for rule in _RULES:
        rule_registry.register(rule, [LEASING_RULE_SET])
    logger.debug("leasing: registered %d validation rules", len(_RULES))
