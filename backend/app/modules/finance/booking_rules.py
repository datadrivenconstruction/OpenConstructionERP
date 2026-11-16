# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules of the booking export: ``booking.*`` (neutral) and ``datev.*`` (EXTF writer).

Both sets read one payload, ``{"invoices": [InvoiceIn], "mapping": Mapping, "period_from": date,
"period_to": date, "settings": dict, "reexport": bool}``, and report what the batch planner and
the writer's settings check find. A failed result carries ``details`` for the client message.
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
from app.modules.finance.booking_export import WRITERS, plan_batch

_SEVERITY = {"error": Severity.ERROR, "warning": Severity.WARNING, "info": Severity.INFO}

# key -> (severity, name, description); shared keys exist under both prefixes.
SHARED_RULES: dict[str, tuple[str, str, str]] = {
    "account_unmapped": ("error", "Account Is Mapped", "Every invoice has an external account and a creditor."),
    "amounts_inconsistent": ("error", "Net Plus Tax Equals Gross", "Net plus tax equals gross on every invoice."),
    "not_approved": ("info", "Invoice Approved", "Invoices not yet approved are left out of the batch."),
    "already_exported": (
        "warning",
        "Invoice Not Exported Before",
        "An invoice is exported once unless re-export is on.",
    ),
    "foreign_currency": ("warning", "Invoice In Base Currency", "A foreign currency invoice needs an exchange rate."),
    "text_truncated": ("warning", "Booking Text Within Limit", "Booking text is shortened to the format limit."),
}
DATEV_ONLY: dict[str, tuple[str, str, str]] = {
    "header_incomplete": ("error", "Header Complete", "Advisor, client, fiscal year start and account length are set."),
    "period_crosses_fiscal_year": ("error", "Period In One Fiscal Year", "A batch does not span two fiscal years."),
    "account_length": ("error", "Account Within Length", "G/L accounts fit the configured account length."),
}


class _BookingRule(ValidationRule):
    standard = "booking_export"
    category = RuleCategory.COMPLETENESS
    prefix = "booking"
    key = ""

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        if "invoices" not in data:
            return []
        writer = WRITERS.get(str(data.get("connector_type") or "booking_csv"))
        plan = plan_batch(
            data["invoices"],
            data["mapping"],
            data["period_from"],
            data["period_to"],
            reexport=bool(data.get("reexport")),
            prefix=self.prefix,
            base_currency=str((data.get("settings") or {}).get("base_currency") or ""),
            text_limit=writer.text_limit if writer else None,
        )
        findings = list(plan.findings)
        if writer is not None:
            findings += writer.check_settings(data.get("settings") or {}, data["period_from"], data["period_to"])
        found = [f for f in findings if f["rule_id"] == self.rule_id]
        if not found:
            return [self._result(True, "OK", "", {})]
        return [self._result(False, f["rule_id"], f.get("invoice", ""), f["details"]) for f in found]

    def _result(self, passed: bool, message: str, ref: str, details: dict[str, Any]) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message=message,
            element_ref=ref,
            details=details,
        )


def _make(prefix: str, key: str, spec: tuple[str, str, str]) -> type[_BookingRule]:
    return type(
        f"{prefix.title()}_{key}",
        (_BookingRule,),
        {
            "prefix": prefix,
            "key": key,
            "rule_id": f"{prefix}.{key}",
            "name": spec[1],
            "description": spec[2],
            "severity": _SEVERITY[spec[0]],
        },
    )


BOOKING_RULES = tuple(_make("booking", k, v) for k, v in SHARED_RULES.items())
DATEV_RULES = tuple(_make("datev", k, v) for k, v in {**SHARED_RULES, **DATEV_ONLY}.items())


def register_booking_rules() -> None:
    for rule in BOOKING_RULES:
        rule_registry.register(rule(), rule_sets=["booking_export"])


register_booking_rules()
