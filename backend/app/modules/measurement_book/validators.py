# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Measurement book validation rules, registered under the ``measurement_book`` rule set.

Each rule reads the dict built by ``MeasurementBookService.validate``:
``{"positions": [summary], "entries": [{"id", "boq_position_id", "entry_date", "quantity",
"check_status", "check_quantity"}], "deviation_threshold_pct": Decimal}``.

* ``measurement_book.measured_within_boq`` (WARNING): the cumulative measured quantity of a
  position stays within its BOQ quantity; more is a variation to raise, not a bill line.
* ``measurement_book.checked_before_certification`` (ERROR): every entry is check-measured;
  an unchecked or disputed entry blocks the running bill from being certified.
* ``measurement_book.check_deviation`` (WARNING): the checker's quantity sits within the
  threshold (default 5 percent) of the measured quantity.
"""

from __future__ import annotations

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

RULE_SET = "measurement_book"


def _dec(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


class _Rule(ValidationRule):
    standard = RULE_SET

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


class MeasuredWithinBoqRule(_Rule):
    rule_id = "measurement_book.measured_within_boq"
    name = "Measured quantity within BOQ quantity"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "The cumulative measured quantity of a position does not exceed its BOQ quantity"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for pos in _data(context).get("positions") or []:
            if not pos.get("entry_count"):
                continue
            boq = _dec(pos.get("boq_quantity")) or Decimal("0")
            measured = _dec(pos.get("measured_quantity")) or Decimal("0")
            out.append(
                self._result(
                    str(pos.get("ordinal") or pos.get("boq_position_id")),
                    measured <= boq,
                    f"Position {pos.get('ordinal')}: measured {measured} {pos.get('unit')} "
                    f"exceeds the BOQ quantity {boq}; raise a variation for the excess",
                    boq_quantity=boq,
                    measured_quantity=measured,
                )
            )
        return out


class CheckedBeforeCertificationRule(_Rule):
    rule_id = "measurement_book.checked_before_certification"
    name = "Measurements checked before certification"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Every measurement is check-measured before the running bill is certified"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for e in _data(context).get("entries") or []:
            state = e.get("check_status")
            out.append(
                self._result(
                    str(e.get("id")),
                    state == "checked",
                    f"Measurement of {e.get('entry_date')} is {state}; it blocks certification until checked",
                    check_status=state,
                )
            )
        return out


class CheckDeviationRule(_Rule):
    rule_id = "measurement_book.check_deviation"
    name = "Check-measure deviation within threshold"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "The checker's re-measured quantity is within the threshold of the measured quantity"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        threshold = _dec(data.get("deviation_threshold_pct")) or Decimal("5")
        out = []
        for e in data.get("entries") or []:
            check = _dec(e.get("check_quantity"))
            measured = _dec(e.get("quantity")) or Decimal("0")
            if check is None or e.get("check_status") == "unchecked":
                continue
            if measured == 0:
                deviation = Decimal("0") if check == 0 else Decimal("100")
            else:
                deviation = (abs(check - measured) / abs(measured) * 100).quantize(Decimal("0.01"))
            out.append(
                self._result(
                    str(e.get("id")),
                    deviation <= threshold,
                    f"Measurement of {e.get('entry_date')}: check quantity {check} differs from "
                    f"measured {measured} by {deviation}%, over the {threshold}% threshold",
                    deviation_pct=deviation,
                    threshold_pct=threshold,
                )
            )
        return out


RULES: tuple[ValidationRule, ...] = (
    MeasuredWithinBoqRule(),
    CheckedBeforeCertificationRule(),
    CheckDeviationRule(),
)


def register_measurement_book_rules() -> None:
    """Register the rules under the ``measurement_book`` rule set."""
    for rule in RULES:
        rule_registry.register(rule, [RULE_SET])
