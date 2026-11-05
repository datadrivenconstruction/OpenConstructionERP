# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quality management validation rules (rule set ``qms``).

Rules run over a plain dict built by the service, one record under one key::

    {"ncr":         {"id", "severity", "status", "root_cause", "cost_impact_amount", "cost_impact_currency"}}
    {"punch":       {"id", "raised_at", "due_date"}}
    {"calibration": {"id", "status", "calibration_date", "valid_until"}}

A rule looks only at the record kind and stage it guards, so a freshly raised NCR passes with its
root cause still to be found.
"""

from __future__ import annotations

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, blank, section, to_dec
from app.core.validation.quality_rules import parse_day, today_of

QMS_RULE_SET = "qms"

NCR_FIELDS = ("severity", "status", "root_cause", "cost_impact_amount", "cost_impact_currency")
PUNCH_FIELDS = ("raised_at", "due_date")
CALIBRATION_FIELDS = ("status", "calibration_date", "valid_until")

#: From verification onward a serious non-conformance has to name the cause that was corrected.
_ROOT_CAUSE_STATUSES = frozenset({"verifying", "closed"})
_SERIOUS = frozenset({"major", "critical"})


class _QmsRule(MoneyRule):
    standard = QMS_RULE_SET
    message_section = "qms"


class NcrCostCurrencyRule(_QmsRule):
    """A cost impact states its currency, or the cost of poor quality cannot be totalled."""

    rule_id = "qms.ncr_cost_currency"
    name = "NCR cost impact has a currency"
    description = "a cost_impact_amount above zero requires cost_impact_currency"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ncr = section(context, "ncr")
        ref = str(ncr.get("id", ""))
        amount = to_dec(ncr.get("cost_impact_amount"))
        if amount is not None and amount > 0 and blank(ncr.get("cost_impact_currency")):
            return [self.fail(context, "cost_currency_missing", ref=ref, amount=amount)]
        return [self.ok(ref)]


class NcrRootCauseRule(_QmsRule):
    """A major or critical NCR names its root cause before it goes to verification."""

    rule_id = "qms.ncr_root_cause"
    name = "Serious NCR records its root cause"
    description = "a major or critical NCR that is verifying or closed needs root_cause"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ncr = section(context, "ncr")
        ref = str(ncr.get("id", ""))
        if (
            ncr.get("severity") in _SERIOUS
            and ncr.get("status") in _ROOT_CAUSE_STATUSES
            and blank(ncr.get("root_cause"))
        ):
            return [self.fail(context, "root_cause_missing", ref=ref, grade=ncr.get("severity"))]
        return [self.ok(ref)]


class PunchDueDateRule(_QmsRule):
    """A punch item is not due before it was raised."""

    rule_id = "qms.punch_due_date"
    name = "Punch item due date is after it was raised"
    description = "due_date must not be before raised_at"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        punch = section(context, "punch")
        ref = str(punch.get("id", ""))
        raised, due = parse_day(punch.get("raised_at")), parse_day(punch.get("due_date"))
        if raised is not None and due is not None and due < raised:
            return [
                self.fail(context, "punch_due_before_raised", ref=ref, due=due.isoformat(), raised=raised.isoformat())
            ]
        return [self.ok(ref)]


class CalibrationWindowRule(_QmsRule):
    """A calibration certificate expires after the day the instrument was calibrated."""

    rule_id = "qms.calibration_window"
    name = "Calibration validity window is ordered"
    description = "valid_until must be after calibration_date"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        cal = section(context, "calibration")
        ref = str(cal.get("id", ""))
        start, end = parse_day(cal.get("calibration_date")), parse_day(cal.get("valid_until"))
        if start is not None and end is not None and end <= start:
            return [self.fail(context, "calibration_window", ref=ref, start=start.isoformat(), until=end.isoformat())]
        return [self.ok(ref)]


class CalibrationLapsedRule(_QmsRule):
    """An instrument still marked valid has not passed its recalibration date."""

    rule_id = "qms.calibration_lapsed"
    name = "Calibration marked valid has not lapsed"
    severity = Severity.WARNING
    description = "a calibration with status valid must have valid_until today or later"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        cal = section(context, "calibration")
        ref = str(cal.get("id", ""))
        end = parse_day(cal.get("valid_until"))
        if cal.get("status") == "valid" and end is not None and end < today_of(context):
            return [self.fail(context, "calibration_lapsed", ref=ref, until=end.isoformat())]
        return [self.ok(ref)]


QMS_RULES = (
    NcrCostCurrencyRule,
    NcrRootCauseRule,
    PunchDueDateRule,
    CalibrationWindowRule,
    CalibrationLapsedRule,
)


def register_qms_validation_rules() -> None:
    """Register the quality management rules with the platform rule registry."""
    for rule_class in QMS_RULES:
        rule_registry.register(rule_class(), [QMS_RULE_SET])


__all__ = ["QMS_RULES", "QMS_RULE_SET", "register_qms_validation_rules"]
