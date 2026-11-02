# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Productivity and workforce-demand validation rules.

``field_productivity`` reads the ``productivity_rows`` block the foreman
productivity report builds (:mod:`app.modules.field_time.productivity`);
``workforce`` reads the ``workforce_activities`` block of the trade demand
forecast (:mod:`app.modules.resources.workforce_demand`). A payload without its
block makes each rule return nothing, so neither set fires on a timesheet.
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
)
from app.core.validation.messages import translate
from app.core.validation.rules import _get_locale


def _payload(context: ValidationContext) -> dict[str, Any]:
    data = context.data
    return data if isinstance(data, dict) else {}


def _num(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return out if out.is_finite() else None


def _fail(rule: ValidationRule, locale: str, key: str, element_ref: str, **params: str) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=False,
        message=translate(f"{key}.fail", locale=locale, **params),
        element_ref=element_ref,
        suggestion=translate(f"{key}.suggestion", locale=locale),
    )


class ProductivityHoursWithoutProgress(ValidationRule):
    """Hours booked to a position that shows no installed quantity in the same period."""

    rule_id = "field_productivity.hours_without_progress"
    name = "Hours Booked Without Measured Progress"
    standard = "field_productivity"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags a bill position with labour hours in the period but no measured or reported progress."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        rows = payload.get("productivity_rows")
        if not isinstance(rows, list):
            return []
        locale = _get_locale(context)
        out: list[RuleResult] = []
        for row in rows:
            hours = _num(row.get("labour_hours")) or Decimal("0")
            qty = _num(row.get("installed_quantity")) or Decimal("0")
            if hours > 0 and qty <= 0:
                out.append(
                    _fail(
                        self,
                        locale,
                        "field_productivity.hours_without_progress",
                        str(row.get("position_id") or ""),
                        ref=str(row.get("ref") or row.get("position_id") or ""),
                        hours=str(hours),
                        date_from=str(payload.get("date_from") or ""),
                        date_to=str(payload.get("date_to") or ""),
                    )
                )
        return out


class ProductivityFactorImplausible(ValidationRule):
    """A productivity factor so far from 1 that a booking or unit error is likelier than site reality."""

    rule_id = "field_productivity.factor_implausible"
    name = "Productivity Factor Outside Plausible Band"
    standard = "field_productivity"
    severity = Severity.INFO
    category = RuleCategory.CONSISTENCY
    description = "Flags a position whose spent-over-earned hours factor lies outside the plausible band."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        rows = payload.get("productivity_rows")
        if not isinstance(rows, list):
            return []
        low = _num(payload.get("band_low")) or Decimal("0.5")
        high = _num(payload.get("band_high")) or Decimal("2")
        locale = _get_locale(context)
        out: list[RuleResult] = []
        for row in rows:
            factor = _num(row.get("productivity_factor"))
            if factor is None or low <= factor <= high:
                continue
            out.append(
                _fail(
                    self,
                    locale,
                    "field_productivity.factor_implausible",
                    str(row.get("position_id") or ""),
                    ref=str(row.get("ref") or row.get("position_id") or ""),
                    factor=str(factor),
                    low=str(low),
                    high=str(high),
                )
            )
        return out


class ActivityLabourWithoutTrade(ValidationRule):
    """A schedule activity loads labour that names no trade, so nobody can be matched to it."""

    rule_id = "workforce.activity_labour_without_trade"
    name = "Activity Labour Without Trade"
    standard = "workforce"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags a schedule activity whose labour resource carries hours or crew size but no trade."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        activities = _payload(context).get("workforce_activities")
        if not isinstance(activities, list):
            return []
        locale = _get_locale(context)
        out: list[RuleResult] = []
        for act in activities:
            if act.get("trade"):
                continue
            fte = _num(act.get("fte")) or Decimal("0")
            hours = _num(act.get("man_hours")) or Decimal("0")
            if fte <= 0 and hours <= 0:
                continue
            out.append(
                _fail(
                    self,
                    locale,
                    "workforce.activity_labour_without_trade",
                    str(act.get("activity_id") or ""),
                    activity=str(act.get("name") or act.get("activity_id") or ""),
                    project=str(act.get("project_name") or ""),
                )
            )
        return out


PRODUCTIVITY_RULES: tuple[ValidationRule, ...] = (
    ProductivityHoursWithoutProgress(),
    ProductivityFactorImplausible(),
    ActivityLabourWithoutTrade(),
)

__all__ = [
    "PRODUCTIVITY_RULES",
    "ActivityLabourWithoutTrade",
    "ProductivityFactorImplausible",
    "ProductivityHoursWithoutProgress",
]
