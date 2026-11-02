# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Owner schedule validation rules (rule set ``owner_schedule``).

* ``owner_schedule.item_unpriced`` - ERROR. An owner pay item has no price.
* ``owner_schedule.extra_item`` - ERROR. A top-level BOQ line is not on the owner's list.
* ``owner_schedule.unit_changed`` - ERROR. The pricing position's unit differs from the owner's.
* ``owner_schedule.quantity_changed`` - ERROR. The pricing position's quantity differs from the
  owner's latest addendum.
* ``owner_schedule.rounding`` - ERROR. A line amount is not the owner's rounding of quantity x price.
* ``owner_schedule.alternate_unpriced`` - ERROR when the owner requires alternates, else WARNING.
* ``owner_schedule.total_mismatch`` - ERROR. The schedule total is not the sum of the rounded lines.

Rules read the snapshot of
:meth:`app.modules.owner_schedule.service.OwnerScheduleService.validation_snapshot`.
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

logger = logging.getLogger(__name__)

RULE_SET = "owner_schedule"


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _items(context: ValidationContext) -> list[dict[str, Any]]:
    rows = _data(context).get("items")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


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


class _PerItem(ValidationRule):
    standard = "owner_schedule"

    def check(self, item: dict[str, Any], context: ValidationContext) -> str | None:
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for it in _items(context):
            msg = self.check(it, context)
            out.append(_result(self, msg is None, msg or "OK", it.get("item_no")))
        return out


class ItemUnpriced(_PerItem):
    rule_id = "owner_schedule.item_unpriced"
    name = "Every Owner Item Is Priced"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Each pay item of the owner's schedule carries a price before the schedule is returned."

    def check(self, item: dict[str, Any], context: ValidationContext) -> str | None:
        if item.get("is_alternate"):
            return None
        if item.get("unit_price") is None:
            return f"Owner item {item.get('item_no')} has no price."
        return None


class UnitChanged(_PerItem):
    rule_id = "owner_schedule.unit_changed"
    name = "Owner Units Unchanged"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "The position that prices an owner item keeps the owner's unit."

    def check(self, item: dict[str, Any], context: ValidationContext) -> str | None:
        if item.get("position_unit") is None:
            return None
        if str(item["position_unit"]).strip().lower() != str(item.get("unit") or "").strip().lower():
            return (
                f"Owner item {item.get('item_no')} is in {item.get('unit')}, the estimate uses {item['position_unit']}."
            )
        return None


class QuantityChanged(_PerItem):
    rule_id = "owner_schedule.quantity_changed"
    name = "Owner Quantities Unchanged"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "The position that prices an owner item keeps the quantity of the latest addendum."

    def check(self, item: dict[str, Any], context: ValidationContext) -> str | None:
        pq, oq = _dec(item.get("position_quantity")), _dec(item.get("quantity"))
        if pq is None or oq is None or item.get("is_lump_sum"):
            return None
        if pq != oq:
            return f"Owner item {item.get('item_no')} has quantity {oq}, the estimate uses {pq}."
        return None


class Rounding(_PerItem):
    rule_id = "owner_schedule.rounding"
    name = "Owner Rounding Applied"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Each line amount is the owner's rounding of quantity times the rounded unit price."

    def check(self, item: dict[str, Any], context: ValidationContext) -> str | None:
        price, amount, qty = _dec(item.get("unit_price")), _dec(item.get("amount")), _dec(item.get("quantity"))
        if price is None or amount is None or qty is None or item.get("is_lump_sum"):
            return None
        rr = _data(context).get("rounding") or {}
        pdp, adp = int(rr.get("unit_price_decimals", 2)), int(rr.get("amount_decimals", 2))
        if price != price.quantize(Decimal(1).scaleb(-pdp)):
            return f"Owner item {item.get('item_no')}: unit price {price} has more than {pdp} decimals."
        expected = (price * qty).quantize(Decimal(1).scaleb(-adp), rounding="ROUND_HALF_UP")
        if amount != expected:
            return f"Owner item {item.get('item_no')}: amount {amount} should be {expected}."
        return None


class AlternateUnpriced(_PerItem):
    rule_id = "owner_schedule.alternate_unpriced"
    name = "Alternates Priced"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Alternates and options carry a price; an error when the owner requires them."

    def check(self, item: dict[str, Any], context: ValidationContext) -> str | None:
        if item.get("is_alternate") and item.get("unit_price") is None:
            return f"Alternate {item.get('item_no')} has no price."
        return None

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = await super().validate(context)
        if _data(context).get("alternates_required"):
            for r in out:
                r.severity = Severity.ERROR
        return out


class ExtraItem(ValidationRule):
    rule_id = "owner_schedule.extra_item"
    name = "No Items Added To The Owner List"
    standard = "owner_schedule"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Every top-level line of the estimate is an owner item; own breakdown sits below an owner item."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        extras = _data(context).get("extra_positions") or []
        if not extras:
            return [_result(self, True, "OK")]
        return [
            _result(self, False, f"Line {e.get('ordinal')} is not on the owner's schedule.", e.get("ordinal"))
            for e in extras
        ]


class TotalMismatch(ValidationRule):
    rule_id = "owner_schedule.total_mismatch"
    name = "Total Equals Sum Of Rounded Lines"
    standard = "owner_schedule"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "The schedule total equals the sum of the rounded line amounts exactly."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        total = _dec(data.get("total"))
        line_sum = sum(
            (_dec(i.get("amount")) or Decimal(0) for i in _items(context) if not i.get("is_alternate")), Decimal(0)
        )
        if total is None or total == line_sum:
            return [_result(self, True, "OK")]
        return [_result(self, False, f"Total {total} differs from the sum of lines {line_sum}.", "total")]


_RULES: tuple[ValidationRule, ...] = (
    ItemUnpriced(),
    ExtraItem(),
    UnitChanged(),
    QuantityChanged(),
    Rounding(),
    AlternateUnpriced(),
    TotalMismatch(),
)
RULE_IDS = tuple(r.rule_id for r in _RULES)


def register_owner_schedule_rules() -> None:
    """Register the rules with the core registry (idempotent)."""
    for rule in _RULES:
        rule_registry.register(rule, [RULE_SET])


async def evaluate(snapshot: dict[str, Any], *, target_id: str = "") -> list[RuleResult]:
    """Run the rule set over a snapshot and return the failing results only."""
    try:
        report = await validation_engine.validate(
            data=snapshot, rule_sets=[RULE_SET], target_type="owner_schedule", target_id=target_id
        )
    except Exception:  # noqa: BLE001 - findings augment a read, never break it
        logger.warning("owner_schedule validation failed for %s", target_id, exc_info=True)
        return []
    return [r for r in report.results if not r.passed and not r.is_engine_error]


__all__ = ["RULE_IDS", "RULE_SET", "evaluate", "register_owner_schedule_rules"]
