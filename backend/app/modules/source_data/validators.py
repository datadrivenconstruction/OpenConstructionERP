# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rules for the source-data register.

Ships the module-local ``source_data_completeness`` rule: a delivery must not
proceed while a required prerequisite (permit, survey, technical conditions, ...)
is still outstanding. The rule is registered into the core rule registry under
the ``source_data`` rule set from the module ``on_startup`` hook, so it never
edits the shared rules file.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

logger = logging.getLogger(__name__)

# Checklist statuses that count as resolved (mirrors the service constant, kept
# local so the rule has no import-time dependency on the service).
_RESOLVED_CHECKLIST: frozenset[str] = frozenset({"satisfied", "waived"})


def _checklist_items(context: ValidationContext) -> list[dict[str, Any]]:
    """Pull checklist-item dicts from the context data.

    Accepts either a bare list of item dicts or a dict carrying them under
    ``checklist_items`` / ``checklist`` so callers can hand the rule whatever
    shape is convenient.
    """
    data = context.data
    if isinstance(data, list):
        return [i for i in data if isinstance(i, dict)]
    if isinstance(data, dict):
        items = data.get("checklist_items") or data.get("checklist") or []
        return [i for i in items if isinstance(i, dict)]
    return []


class SourceDataCompleteness(ValidationRule):
    """Every required source-data checklist item must be satisfied or waived."""

    rule_id = "source_data.completeness"
    name = "Source Data Completeness"
    standard = "source_data"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = (
        "Every required prerequisite on the source-data checklist must be "
        "satisfied or explicitly waived before the schedule can proceed."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for item in _checklist_items(context):
            if not item.get("required", True):
                continue
            status = item.get("status", "pending")
            resolved = status in _RESOLVED_CHECKLIST
            label = item.get("label") or item.get("id") or "item"
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=resolved,
                    message=("OK" if resolved else f"Required prerequisite '{label}' is still {status}."),
                    element_ref=str(item.get("id")) if item.get("id") is not None else None,
                    suggestion=(None if resolved else "Supply the document, or waive the item if it is not needed."),
                )
            )
        return results


_SOURCE_DATA_RULES: tuple[ValidationRule, ...] = (SourceDataCompleteness(),)


def register_source_data_rules() -> None:
    """Register the module's validation rules with the core rule registry.

    Idempotent - the registry overwrites a rule by id, so a re-import / hot
    reload re-registers cleanly. Called from the module ``on_startup`` hook.
    """
    for rule in _SOURCE_DATA_RULES:
        rule_registry.register(rule, ["source_data"])
    logger.debug("Registered %d source_data validation rules", len(_SOURCE_DATA_RULES))


__all__ = ["SourceDataCompleteness", "register_source_data_rules"]
