# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Guarantees​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ register validation rules (rule set ``guarantees``).

* ``guarantees.performance_bond_before_first_payment`` - ERROR. A contract that has
  an interim payment, or is about to get its first, holds no live performance
  bond (FIDIC 2017 Sub-Clause 14.6 / 4.2: no payment before the Performance Security).
* ``guarantees.expiry_covers_defects_period`` - WARNING. A performance, retention or
  warranty security expires before contract completion plus the defects period.
* ``guarantees.advance_covers_outstanding`` - ERROR. An advance payment guarantee is
  worth less than the advance still to be recovered.
* ``guarantees.amount_matches_contract_percent`` - WARNING. The face value does not
  match the stated percentage of the contract value.

Every rule reads the plain snapshot built by
:func:`app.modules.guarantees.service.GuaranteesService.validation_snapshot`, so the
rules run against a dict with no database. Messages are English prose with the
numbers in them; the screen translates the rule name by id.
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
    validation_engine,
)
from app.modules.guarantees import logic

logger = logging.getLogger(__name__)

GUARANTEES_RULE_SET = "guarantees"
_DURATION_TYPES = frozenset({"performance_bond", "retention_bond", "warranty_bond"})


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _guarantees(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data if isinstance(context.data, dict) else {}
    rows = data.get("guarantees")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _contracts(context: ValidationContext) -> dict[str, dict[str, Any]]:
    data = context.data if isinstance(context.data, dict) else {}
    rows = data.get("contracts")
    return {str(k): v for k, v in rows.items() if isinstance(v, dict)} if isinstance(rows, dict) else {}


def _result(rule: ValidationRule, passed: bool, message: str, ref: str | None = None, **details: Any) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=ref,
        details=details,
    )


def _money(amount: Decimal | None, currency: str) -> str:
    return f"{format(amount if amount is not None else Decimal('0'), ',.2f')} {currency}".strip()


class PerformanceBondBeforeFirstPayment(ValidationRule):
    """No interim payment on a contract without a live performance bond."""

    rule_id = "guarantees.performance_bond_before_first_payment"
    name = "Performance Bond Held Before The First Payment"
    standard = "FIDIC"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "A contract that requires a performance security receives no interim payment until it is issued."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        live = {
            str(g.get("contract_id"))
            for g in _guarantees(context)
            if g.get("guarantee_type") == "performance_bond"
            and g.get("direction", "given") == "given"
            and logic.is_live(g.get("status"))
        }
        for cid, contract in _contracts(context).items():
            if not contract.get("requires_performance_bond", True) or not contract.get("payment_due"):
                continue
            ref = contract.get("code") or cid
            if cid in live:
                results.append(_result(self, True, "OK", ref))
                continue
            results.append(
                _result(
                    self,
                    False,
                    f"Contract {ref} has an interim payment due or made but no issued performance bond "
                    "is on the register.",
                    ref,
                    contract_id=cid,
                )
            )
        return results


class ExpiryCoversDefectsPeriod(ValidationRule):
    """A security that must last through the defects period expires before it ends."""

    rule_id = "guarantees.expiry_covers_defects_period"
    name = "Security Valid Through Completion And The Defects Period"
    standard = "FIDIC"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "Performance, retention and warranty securities stay valid until the contract is complete and the "
        "defects notification period has ended (FIDIC 2017 Sub-Clause 4.2)."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        contracts = _contracts(context)
        for g in _guarantees(context):
            if g.get("guarantee_type") not in _DURATION_TYPES or g.get("status") in logic.CLOSED_STATUSES:
                continue
            contract = contracts.get(str(g.get("contract_id"))) or {}
            months = g.get("defects_period_months")
            if months is None:
                months = contract.get("defects_period_months")
            needed = logic.required_until(logic.parse_date(contract.get("completion_date")), months)
            expiry = logic.parse_date(g.get("expiry_date"))
            if needed is None or expiry is None:
                continue
            ref = g.get("reference")
            if expiry >= needed or g.get("auto_extend"):
                results.append(_result(self, True, "OK", ref))
                continue
            results.append(
                _result(
                    self,
                    False,
                    f"{ref} expires on {expiry.isoformat()}, {(needed - expiry).days} days before completion "
                    f"plus the defects period ends on {needed.isoformat()}.",
                    ref,
                    guarantee_id=g.get("id"),
                    expiry_date=expiry.isoformat(),
                    required_until=needed.isoformat(),
                )
            )
        return results


class AdvanceCoversOutstanding(ValidationRule):
    """An advance payment guarantee worth less than the advance still to be recovered."""

    rule_id = "guarantees.advance_covers_outstanding"
    name = "Advance Guarantee Covers The Outstanding Advance"
    standard = "FIDIC"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Until the advance is repaid the advance payment guarantee is at least the amount outstanding."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for g in _guarantees(context):
            if g.get("guarantee_type") != "advance_payment" or g.get("status") in logic.CLOSED_STATUSES:
                continue
            advance = _dec(g.get("advance_amount"))
            if advance is None:
                continue
            outstanding = logic.outstanding_advance(advance, _dec(g.get("advance_recovered")))
            amount = _dec(g.get("amount")) or Decimal("0")
            ref = g.get("reference")
            if amount >= outstanding:
                results.append(_result(self, True, "OK", ref))
                continue
            currency = g.get("currency") or ""
            results.append(
                _result(
                    self,
                    False,
                    f"{ref} is worth {_money(amount, currency)} but {_money(outstanding, currency)} of the "
                    "advance is still to be recovered.",
                    ref,
                    guarantee_id=g.get("id"),
                    amount=str(amount),
                    outstanding_advance=str(outstanding),
                )
            )
        return results


class AmountMatchesContractPercent(ValidationRule):
    """Face value and stated percentage of contract value disagree."""

    rule_id = "guarantees.amount_matches_contract_percent"
    name = "Guarantee Amount Matches The Contract Percentage"
    standard = "custom"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Where a percentage of contract value is stated, the face value equals it within half a percent."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        contracts = _contracts(context)
        for g in _guarantees(context):
            if g.get("guarantee_type") == "advance_payment" and g.get("status") == "reduced":
                continue
            percent = _dec(g.get("percent_of_contract"))
            value = _dec(g.get("contract_value"))
            if value is None:
                value = _dec((contracts.get(str(g.get("contract_id"))) or {}).get("value"))
            amount = _dec(g.get("original_amount")) or _dec(g.get("amount")) or Decimal("0")
            verdict = logic.amount_matches_percent(amount, value, percent)
            if verdict is None:
                continue
            ref = g.get("reference")
            if verdict:
                results.append(_result(self, True, "OK", ref))
                continue
            currency = g.get("currency") or ""
            expected = logic.expected_amount(value, percent)
            results.append(
                _result(
                    self,
                    False,
                    f"{ref} is {_money(amount, currency)}, but {percent}% of the contract value "
                    f"{_money(value, currency)} is {_money(expected, currency)}.",
                    ref,
                    guarantee_id=g.get("id"),
                    expected_amount=str(expected),
                )
            )
        return results


_RULES: tuple[ValidationRule, ...] = (
    PerformanceBondBeforeFirstPayment(),
    ExpiryCoversDefectsPeriod(),
    AdvanceCoversOutstanding(),
    AmountMatchesContractPercent(),
)
RULE_IDS: tuple[str, ...] = tuple(r.rule_id for r in _RULES)


def register_guarantees_rules() -> None:
    """Register the rules with the core registry (idempotent: the registry overwrites by id)."""
    for rule in _RULES:
        rule_registry.register(rule, [GUARANTEES_RULE_SET])


async def evaluate(snapshot: dict[str, Any], *, target_id: str = "") -> list[RuleResult]:
    """Run the rule set over a snapshot and return the failing results only.

    A broken rule must not break a register read, so an engine failure logs and
    returns no findings.
    """
    try:
        report = await validation_engine.validate(
            data=snapshot, rule_sets=[GUARANTEES_RULE_SET], target_type="guarantees", target_id=target_id
        )
    except Exception:  # noqa: BLE001 - findings augment a read, never break it
        logger.warning("guarantees validation failed for %s", target_id, exc_info=True)
        return []
    return [r for r in report.results if not r.passed and not r.is_engine_error]


__all__ = [
    "GUARANTEES_RULE_SET",
    "RULE_IDS",
    "AdvanceCoversOutstanding",
    "AmountMatchesContractPercent",
    "ExpiryCoversDefectsPeriod",
    "PerformanceBondBeforeFirstPayment",
    "evaluate",
    "register_guarantees_rules",
]
