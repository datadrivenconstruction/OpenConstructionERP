# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dataflow validation rules.

``dataflow.counts_reported`` (WARNING): an installed module must report at least
one object counter; context data is ``{"modules": [ModuleCounts as dict, ...]}``.

``dataflow.critical_input_present`` (ERROR): a module that already holds records
must not miss a critical input (BOQ without quantities, contract without an
award); context data is ``{"health": [HealthItem as dict, ...]}``, as returned by
the platform map.
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


class CountsReportedRule(ValidationRule):
    """An installed module must contribute at least one counter."""

    rule_id = "dataflow.counts_reported"
    name = "Installed module reports counters"
    standard = "dataflow"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Every installed module listed in the data map should report at least one object counter"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data: Any = context.data
        modules = data.get("modules", []) if isinstance(data, dict) else []
        results: list[RuleResult] = []
        for mod in modules:
            if not mod.get("installed"):
                continue
            passed = bool(mod.get("objects"))
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK" if passed else f"Module {mod.get('module')} reports no counters",
                    element_ref=str(mod.get("module")),
                )
            )
        return results


class CriticalInputPresentRule(ValidationRule):
    """A module with records must not be missing a critical input."""

    rule_id = "dataflow.critical_input_present"
    name = "Critical inputs are present"
    standard = "dataflow"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A module that holds records needs every input its declaration marks critical"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data: Any = context.data
        items = data.get("health", []) if isinstance(data, dict) else []
        if not items:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message="OK",
                )
            ]
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=f"{item.get('module')} has records but nothing from {item.get('source')}",
                element_ref=str(item.get("path_id")),
            )
            for item in items
        ]


def register_dataflow_validation_rules() -> None:
    """Register the dataflow rule set."""
    rule_registry.register(CountsReportedRule(), ["dataflow"])
    rule_registry.register(CriticalInputPresentRule(), ["dataflow"])
