# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rule set ``economics``.

One rule per finding code of :mod:`app.modules.economics.rules`, all reading the
payload built by ``EconomicsService.validation_payload``. Every rule calls the
same pure function the service and the gate evidence use and keeps the findings
of its own code, so a check has one implementation. A rule that finds nothing
returns one passing result on the ``project`` reference, so the dashboard can
show it green.
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
from app.modules.economics import rules
from app.modules.economics.messages import translate

ECONOMICS_RULE_SET = "economics"

#: finding code -> (rule name, category). The name is the English display name of the rule.
_RULES: dict[str, tuple[str, RuleCategory]] = {
    "discount_rate_missing": ("Discount Rate Set", RuleCategory.COMPLETENESS),
    "no_investment": ("Investment Entered", RuleCategory.COMPLETENESS),
    "no_benefit": ("Benefit Entered", RuleCategory.COMPLETENESS),
    "cash_flow_years_invalid": ("Cash Flow Years In Order", RuleCategory.STRUCTURE),
    "cash_flow_outside_horizon": ("Cash Flow Within Horizon", RuleCategory.CONSISTENCY),
    "investment_below_frame": ("Investment Covers Cost Frame", RuleCategory.CONSISTENCY),
    "frame_empty": ("Cost Frame Entered", RuleCategory.COMPLETENESS),
    "frame_lines_overlap": ("Cost Frame Lines Disjoint", RuleCategory.STRUCTURE),
    "frame_zero_amount": ("Cost Frame Line Has Amount", RuleCategory.COMPLETENESS),
    "estimate_over_frame": ("Estimate Within Cost Frame", RuleCategory.CONSISTENCY),
    "estimate_unassigned": ("Estimate Under A Frame Line", RuleCategory.COMPLETENESS),
    "markups_over_allowance": ("Markups Within Allowance", RuleCategory.CONSISTENCY),
    "no_bill": ("Estimate Available", RuleCategory.COMPLETENESS),
    "several_bills": ("One Bill Read", RuleCategory.CONSISTENCY),
    "currency_mismatch": ("Plan And Bill Share A Currency", RuleCategory.CONSISTENCY),
    "committed_over_frame": ("Commitments Within Cost Frame", RuleCategory.CONSISTENCY),
    "committed_unassigned": ("Commitments Under A Frame Line", RuleCategory.COMPLETENESS),
    "committed_unknown": ("Commitments Known", RuleCategory.COMPLETENESS),
    "no_sources": ("Funding Source Entered", RuleCategory.COMPLETENESS),
    "financing_shortfall": ("Financing Covers Requirement", RuleCategory.CONSISTENCY),
    "tranches_differ_from_source": ("Tranches Add Up To Source", RuleCategory.CONSISTENCY),
    "source_without_tranches": ("Source Has Tranches", RuleCategory.COMPLETENESS),
    "grant_without_application": ("Grant Has Application", RuleCategory.COMPLETENESS),
    "grant_over_award": ("Grant Within Award", RuleCategory.CONSISTENCY),
    "security_expired": ("Securities Valid", RuleCategory.CONSISTENCY),
    "insurance_expired": ("Insurance Valid", RuleCategory.CONSISTENCY),
    "tax_not_confirmed": ("Tax Treatment Confirmed", RuleCategory.COMPLETENESS),
    "process_not_set_up": ("Processes Set Up", RuleCategory.COMPLETENESS),
}


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _locale(context: ValidationContext) -> str:
    return str((getattr(context, "metadata", None) or {}).get("locale") or "en")


class _EconomicsRule(ValidationRule):
    standard = "economics"
    code = ""

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        found = [f for f in rules.all_findings(_data(context)) if f.code == self.code]
        if not found:
            return [self._result(loc, True, "project", self.severity)]
        return [
            self._result(
                loc, False, f.ref, Severity.ERROR if f.severity == rules.ERROR else Severity.WARNING, **f.params
            )
            for f in found
        ]

    def _result(self, locale: str, passed: bool, ref: str, severity: Severity, **params: Any) -> RuleResult:
        base = f"economics.rules.{self.code}"
        shown = ref
        if self.code == "process_not_set_up" and not passed:
            area_key = f"economics.process_area.{ref}"
            area = translate(area_key, locale=locale)
            shown = area if area != area_key else ref
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=severity,
            category=self.category,
            passed=passed,
            message=translate("economics.rules.ok", locale=locale)
            if passed
            else translate(f"{base}.fail", locale=locale, ref=shown, **params),
            element_ref=ref,
            suggestion=None if passed else translate(f"{base}.suggestion", locale=locale),
        )


def _make(code: str, name: str, category: RuleCategory) -> type[ValidationRule]:
    severity = Severity.ERROR if rules.CODES[code] == rules.ERROR else Severity.WARNING
    return type(
        "".join(part.capitalize() for part in code.split("_")),
        (_EconomicsRule,),
        {
            "code": code,
            "rule_id": f"economics.{code}",
            "name": name,
            "description": name,
            "severity": severity,
            "category": category,
        },
    )


ECONOMICS_RULES: tuple[type[ValidationRule], ...] = tuple(_make(c, n, cat) for c, (n, cat) in _RULES.items())


def register_economics_rules() -> None:
    """Idempotently register the economics rules."""
    for rule in ECONOMICS_RULES:
        rule_registry.register(rule(), rule_sets=[ECONOMICS_RULE_SET])


# Registered on import as well, like the platform rule modules: whoever imports the rules sees them,
# not only an app that ran the startup hook. Registration is idempotent.
register_economics_rules()
