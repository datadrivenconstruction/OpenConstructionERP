# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules ``equip_rate.*`` for the plant rate catalogue.

The rules read one payload::

    {"items": [{"id", "code", "value", "residual", "life_years", "months_per_year",
                "interest", "repair", "hours_per_month"}],
     "rentals": [{"id", "code", "rate", "catalogue_rate", "tolerance_pct", "synthetic",
                  "project_is_demo"}]}

Each result carries ``details.message_key`` so the client renders the sentence in the user's
language; ``message`` is the English text. Interest and repair are fractions (0.06 = 6%).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.equipment.rate_math import to_decimal

RATE_RULE_SET = "equipment_rates"

_MAX_INTEREST = Decimal("0.30")
_MAX_REPAIR = Decimal("3")


def _rows(context: ValidationContext, key: str) -> list[dict[str, Any]]:
    data = context.data if isinstance(context.data, dict) else {}
    return [r for r in (data.get(key) or []) if isinstance(r, dict)]


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


class _RateRule(ValidationRule):
    standard = "equipment"
    category = RuleCategory.CONSISTENCY
    severity = Severity.ERROR
    key = ""
    text = ""
    rows_key = "items"

    def _result(self, row: dict[str, Any], passed: bool, **params: Any) -> RuleResult:
        params = {"code": row.get("code", ""), **params}
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message="OK" if passed else self.text,
            element_ref=str(row.get("id") or row.get("code") or ""),
            details={"message_key": f"validation.equip_rate.{self.key}", **{k: str(v) for k, v in params.items()}},
        )

    def check(self, row: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [r for row in _rows(context, self.rows_key) if (r := self.check(row, context)) is not None]


class LifePositive(_RateRule):
    key = "life_not_positive"
    rule_id = "equip_rate.life_not_positive"
    name = "Useful Life Is Positive"
    description = "Useful life n is greater than 0."
    text = "Useful life n must be greater than 0."

    def check(self, row: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        if _blank(row.get("life_years")):
            return None
        n = to_decimal(row.get("life_years"))
        return self._result(row, n is not None and n > 0)


class MonthsInRange(_RateRule):
    key = "months_out_of_range"
    rule_id = "equip_rate.months_out_of_range"
    name = "Operating Months In Range"
    description = "Operating months per year are between 1 and 12."
    text = "Operating months per year must be between 1 and 12."

    def check(self, row: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        if _blank(row.get("months_per_year")):
            return None
        v = to_decimal(row.get("months_per_year"))
        return self._result(row, v is not None and Decimal(1) <= v <= Decimal(12))


class ResidualBelowValue(_RateRule):
    key = "residual_exceeds_value"
    rule_id = "equip_rate.residual_exceeds_value"
    name = "Residual Below Value"
    description = "The residual value is lower than the value."
    text = "Residual value is not lower than the value."

    def check(self, row: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        p, rv = to_decimal(row.get("value")), to_decimal(row.get("residual"))
        if p is None or rv is None:
            return None
        return self._result(row, rv < p)


class HoursPositive(_RateRule):
    key = "hours_not_positive"
    rule_id = "equip_rate.hours_not_positive"
    name = "Hours Per Month Positive"
    description = "Hours per month are greater than 0 to derive an hourly rate."
    text = "Hours per month must be greater than 0 to derive an hourly rate."

    def check(self, row: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        if _blank(row.get("hours_per_month")):
            return None
        h = to_decimal(row.get("hours_per_month"))
        return self._result(row, h is not None and h > 0)


class InterestUsual(_RateRule):
    key = "interest_unusual"
    rule_id = "equip_rate.interest_unusual"
    name = "Interest Rate Usual"
    description = "Interest is not negative and not above 30% per year."
    severity = Severity.WARNING
    text = "Interest rate is negative or above 30% p.a."

    def check(self, row: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        i = to_decimal(row.get("interest"))
        return None if i is None else self._result(row, Decimal(0) <= i <= _MAX_INTEREST)


class RepairUsual(_RateRule):
    key = "repair_unusual"
    rule_id = "equip_rate.repair_unusual"
    name = "Repair Factor Usual"
    description = "Repair over life is not above 300% of the value."
    severity = Severity.WARNING
    text = "Repair factor above 300% of value over life."

    def check(self, row: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        r = to_decimal(row.get("repair"))
        return None if r is None else self._result(row, r <= _MAX_REPAIR)


class RentalWithinTolerance(_RateRule):
    key = "rental_deviates"
    rule_id = "equip_rate.rental_deviates"
    name = "Rental Rate Close To Catalogue"
    description = "A rental rate differs from the catalogue rate by no more than the tolerance."
    severity = Severity.WARNING
    rows_key = "rentals"
    text = "Rental rate differs from catalogue rate by more than the configured tolerance."

    def check(self, row: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        rate = to_decimal(row.get("rate"))
        cat = to_decimal(row.get("catalogue_rate"))
        tol = to_decimal(row.get("tolerance_pct"))
        if rate is None or cat is None or tol is None or cat <= 0:
            return None
        return self._result(row, abs(rate - cat) / cat * 100 <= tol)


class DemoRateNotOnRealProject(_RateRule):
    key = "synthetic_in_use"
    rule_id = "equip_rate.synthetic_in_use"
    name = "Demo Rate Not On A Real Project"
    description = "A synthetic demo catalogue rate is not used on a real project."
    severity = Severity.WARNING
    rows_key = "rentals"
    text = "Demo catalogue rate used on a real project."

    def check(self, row: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        if not row.get("synthetic"):
            return None
        return self._result(row, bool(row.get("project_is_demo")))


RATE_RULES: tuple[type[_RateRule], ...] = (
    LifePositive,
    MonthsInRange,
    ResidualBelowValue,
    HoursPositive,
    InterestUsual,
    RepairUsual,
    RentalWithinTolerance,
    DemoRateNotOnRealProject,
)

IMPORT_ROW_INVALID = "equip_rate.import_row_invalid"


def import_row_issue(row_number: int, field: str) -> dict[str, Any]:
    """The ``equip_rate.import_row_invalid`` issue for one import row and field."""
    return {
        "rule_id": IMPORT_ROW_INVALID,
        "severity": "error",
        "row": row_number,
        "field": field,
        "message": f"Import row {row_number}: {field} missing or not a number.",
        "details": {"message_key": "validation.equip_rate.import_row_invalid", "n": str(row_number), "field": field},
    }


def register_rate_rules() -> None:
    """Idempotently register the rate catalogue rules."""
    for rule in RATE_RULES:
        rule_registry.register(rule(), rule_sets=[RATE_RULE_SET])


async def run_rate_rules(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every rate rule against one payload, as plain dicts (passed and failed)."""
    context = ValidationContext(data=payload, metadata={})
    out: list[dict[str, Any]] = []
    for rule_cls in RATE_RULES:
        for r in await rule_cls().validate(context):
            out.append(
                {
                    "rule_id": r.rule_id,
                    "passed": r.passed,
                    "severity": str(getattr(r.severity, "value", r.severity)),
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "details": r.details,
                }
            )
    return out


register_rate_rules()
