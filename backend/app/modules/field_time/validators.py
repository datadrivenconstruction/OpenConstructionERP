# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rule set ``payroll_export``: the ``payexp.*`` rules of the hours export.

The rules read one payload, ``{"lines": [HourLine], "profile": ExportProfile,
"unapproved": [ref], "overlaps": [run label]}``, and report what
:func:`app.modules.field_time.payroll_export.check_run` finds. Each failed result carries
``details.message_key`` so the client renders the sentence in the user's language.
"""

from __future__ import annotations

from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.field_time.payroll_export import ExportProfile, check_run

PAYROLL_EXPORT_RULE_SET = "payroll_export"

_SEVERITY = {"error": Severity.ERROR, "warning": Severity.WARNING, "info": Severity.INFO}


class _PayExpRule(ValidationRule):
    standard = "payroll_export"
    category = RuleCategory.COMPLETENESS
    severity = Severity.ERROR
    key = ""

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        profile = data.get("profile")
        if not isinstance(profile, ExportProfile):
            return []
        found = [
            i
            for i in check_run(
                data.get("lines") or [],
                profile,
                unapproved_refs=data.get("unapproved") or [],
                overlapping_runs=data.get("overlaps") or [],
            )
            if i["rule_id"] == self.rule_id
        ]
        if not found:
            return [self._result(True, "OK", {})]
        return [self._result(False, i["message"], i["details"]) for i in found]

    def _result(self, passed: bool, message: str, details: dict[str, Any]) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message=message,
            element_ref="",
            details=details,
        )


def _rule(key: str, severity: str, name: str, description: str) -> type[_PayExpRule]:
    return type(
        f"PayExp_{key}",
        (_PayExpRule,),
        {
            "key": key,
            "rule_id": f"payexp.{key}",
            "name": name,
            "description": description,
            "severity": _SEVERITY[severity],
        },
    )


PAYEXP_RULES: tuple[type[_PayExpRule], ...] = (
    _rule(
        "worker_without_ref", "error", "Worker Has Payroll Reference", "Every exported worker has a payroll reference."
    ),
    _rule(
        "day_over_24h", "error", "Day Not Over 24 Hours", "A worker has at most 24 hours on one day across projects."
    ),
    _rule(
        "day_over_threshold",
        "warning",
        "Day Within Profile Threshold",
        "Hours per day stay under the profile threshold.",
    ),
    _rule(
        "hour_type_unmapped",
        "error",
        "Hour Type Has Pay Code",
        "Every exported hour type has a pay code in the profile.",
    ),
    _rule("cost_code_missing", "warning", "Line Has Cost Code", "Every exported line carries a cost code."),
    _rule("not_approved", "info", "Timesheet Approved", "Timesheets not yet approved are left out of the export."),
    _rule("period_overlap", "warning", "Period Does Not Overlap A Run", "The period does not overlap an earlier run."),
    _rule("negative_total", "error", "Net Hours Not Negative", "Net hours per worker and day are not below zero."),
)


def register_payroll_export_rules() -> None:
    """Idempotently register the payexp rules."""
    for rule in PAYEXP_RULES:
        rule_registry.register(rule(), rule_sets=[PAYROLL_EXPORT_RULE_SET])


register_payroll_export_rules()
