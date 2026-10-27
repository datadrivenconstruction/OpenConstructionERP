# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payroll​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ period validation rules (rule set ``payroll_period``).

* ``payroll.hours_without_cost_code`` - ERROR. Paid hours that no cost code carries.
* ``payroll.overtime_without_approval`` - ERROR. Overtime from a timesheet nobody
  marked as approved overtime.
* ``payroll.employee_without_pay_rate`` - ERROR. Hours of an employee whose pay rate is zero.
* ``payroll.exceeds_legal_maximum`` - WARNING. A day or week above the legal maximum of
  the rule profile (country data).
* ``payroll.export_after_lock`` - ERROR. An export of a period that is not locked.

Every rule reads the snapshot of
:meth:`app.modules.payroll.period_service.PayrollPeriodService.validation_snapshot`.
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

PAYROLL_RULE_SET = "payroll_period"
_OVERTIME = frozenset({"overtime", "overtime_weekly"})


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _lines(context: ValidationContext) -> list[dict[str, Any]]:
    rows = _data(context).get("lines")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


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


class _Rule(ValidationRule):
    standard = "payroll"
    category = RuleCategory.CONSISTENCY

    def check(self, context: ValidationContext) -> list[RuleResult]:  # pragma: no cover - overridden
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        found = self.check(context)
        return found or [_result(self, True, "OK")]


class HoursWithoutCostCode(_Rule):
    rule_id = "payroll.hours_without_cost_code"
    name = "Hours without a cost code"
    severity = Severity.ERROR
    description = "Every paid hour must land on a cost code, or the labour cost cannot reach the project actuals."

    def check(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for ln in _lines(context):
            if _dec(ln.get("hours")) > 0 and not str(ln.get("cost_code") or "").strip():
                out.append(
                    _result(
                        self,
                        False,
                        f"{ln.get('employee')} on {ln.get('work_date')}: {ln.get('hours')} h have no cost code.",
                        ln.get("employee"),
                    )
                )
        return out


class OvertimeWithoutApproval(_Rule):
    rule_id = "payroll.overtime_without_approval"
    name = "Overtime without approval"
    severity = Severity.ERROR
    description = "Overtime is paid only when the timesheet marks it as approved overtime."

    def check(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for ln in _lines(context):
            if ln.get("pay_type") in _OVERTIME and _dec(ln.get("hours")) > 0 and not ln.get("overtime_approved"):
                out.append(
                    _result(
                        self,
                        False,
                        f"{ln.get('employee')} on {ln.get('work_date')}: "
                        f"{ln.get('hours')} h overtime are not approved.",
                        ln.get("employee"),
                    )
                )
        return out


class EmployeeWithoutPayRate(_Rule):
    rule_id = "payroll.employee_without_pay_rate"
    name = "Employee without a pay rate"
    severity = Severity.ERROR
    description = "An employee with hours but a zero pay rate would be paid nothing."

    def check(self, context: ValidationContext) -> list[RuleResult]:
        seen: set[str] = set()
        out = []
        for ln in _lines(context):
            name = str(ln.get("employee") or "")
            if ln.get("pay_type") != "per_diem" and _dec(ln.get("rate")) <= 0 and name not in seen:
                seen.add(name)
                out.append(_result(self, False, f"{name} has hours but no pay rate.", name))
        return out


class ExceedsLegalMaximum(_Rule):
    rule_id = "payroll.exceeds_legal_maximum"
    name = "More hours than the legal maximum"
    severity = Severity.WARNING
    description = "Daily or weekly hours above the maximum the country profile allows."

    def check(self, context: ValidationContext) -> list[RuleResult]:
        rows = _data(context).get("max_hours_breaches") or []
        return [
            _result(
                self,
                False,
                f"{b.get('employee')}: {b.get('hours')} h in {b.get('scope')} {b.get('period')}, "
                f"the legal maximum is {b.get('limit')} h.",
                b.get("employee"),
                **b,
            )
            for b in rows
            if isinstance(b, dict)
        ]


class ExportAfterLock(_Rule):
    rule_id = "payroll.export_after_lock"
    name = "Export only after lock"
    severity = Severity.ERROR
    description = "A payroll export is final only when the period is locked against timesheet edits."

    def check(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        status = str((data.get("period") or {}).get("status") or "")
        if data.get("export_format") and status not in ("locked", "exported"):
            return [_result(self, False, f"The period is '{status}'. Lock it before exporting.")]
        return []


_RULES: tuple[ValidationRule, ...] = (
    HoursWithoutCostCode(),
    OvertimeWithoutApproval(),
    EmployeeWithoutPayRate(),
    ExceedsLegalMaximum(),
    ExportAfterLock(),
)
RULE_IDS: tuple[str, ...] = tuple(r.rule_id for r in _RULES)


def register_payroll_rules() -> None:
    """Register the rules with the core registry (idempotent)."""
    for rule in _RULES:
        rule_registry.register(rule, [PAYROLL_RULE_SET])


async def evaluate_period(snapshot: dict[str, Any], *, target_id: str = "") -> list[RuleResult]:
    """Failing results of the rule set over a snapshot."""
    register_payroll_rules()
    try:
        report = await validation_engine.validate(
            data=snapshot, rule_sets=[PAYROLL_RULE_SET], target_type="payroll_period", target_id=target_id
        )
    except Exception:  # noqa: BLE001 - findings augment a read
        logger.warning("payroll validation failed for %s", target_id, exc_info=True)
        return []
    return [r for r in report.results if not r.passed and not r.is_engine_error]
