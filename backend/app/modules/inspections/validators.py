# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Inspection validation rules (rule set ``inspections``).

Rules run over a plain dict context built by the caller::

    {"inspection": {"id", "status", "result", "inspector_id", "inspection_date",
                    "checklist_data": [{"response", ...}]}}

``metadata["today"]`` (ISO date) overrides the reference day for the overdue check.
"""

from __future__ import annotations

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section
from app.core.validation.quality_rules import QualityRule, parse_day, today_of

INSPECTIONS_RULE_SET = "inspections"

#: Checklist answers that count as a failed check (same set the completion event uses).
FAILED_RESPONSES = frozenset({"fail", "no", "false"})


def _failed_count(inspection: dict) -> int:
    items = inspection.get("checklist_data")
    if not isinstance(items, list):
        return 0
    return sum(1 for i in items if isinstance(i, dict) and str(i.get("response", "")).lower() in FAILED_RESPONSES)


class InspectionResultMatchesChecklistRule(QualityRule):
    """A passing result cannot sit on top of failed checklist items."""

    rule_id = "inspections.result_matches_checklist"
    name = "Inspection result agrees with its checklist"
    standard = INSPECTIONS_RULE_SET
    description = "result pass with failed checklist items is contradictory"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        insp = section(context, "inspection")
        ref = str(insp.get("id", ""))
        count = _failed_count(insp)
        if insp.get("result") == "pass" and count:
            return [self.fail(context, "result_contradicts_checklist", ref=ref, result="pass", count=count)]
        return [self.ok(ref)]


class InspectionCompletedHasInspectorRule(QualityRule):
    """A completed inspection names the inspector who signed it off."""

    rule_id = "inspections.completed_has_inspector"
    name = "Completed inspection names its inspector"
    standard = INSPECTIONS_RULE_SET
    description = "status completed requires inspector_id"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        insp = section(context, "inspection")
        ref = str(insp.get("id", ""))
        if insp.get("status") == "completed" and blank(insp.get("inspector_id")):
            return [self.fail(context, "field_required_for_state", ref=ref, state="completed", field="inspector_id")]
        return [self.ok(ref)]


class InspectionCompletedHasResultRule(QualityRule):
    """A completed inspection records a result."""

    rule_id = "inspections.completed_has_result"
    name = "Completed inspection records a result"
    standard = INSPECTIONS_RULE_SET
    description = "status completed requires result"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        insp = section(context, "inspection")
        ref = str(insp.get("id", ""))
        if insp.get("status") == "completed" and blank(insp.get("result")):
            return [self.fail(context, "field_required_for_state", ref=ref, state="completed", field="result")]
        return [self.ok(ref)]


class InspectionNotOverdueRule(QualityRule):
    """A scheduled inspection is not left pending after its date."""

    rule_id = "inspections.not_overdue"
    name = "Scheduled inspection is not in the past"
    standard = INSPECTIONS_RULE_SET
    severity = Severity.WARNING
    description = "an inspection still scheduled after its inspection_date is overdue"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        insp = section(context, "inspection")
        ref = str(insp.get("id", ""))
        day = parse_day(insp.get("inspection_date"))
        if day is not None and insp.get("status") == "scheduled" and day < today_of(context):
            return [self.fail(context, "overdue", ref=ref, status="scheduled", date=day.isoformat())]
        return [self.ok(ref)]


INSPECTIONS_RULES = (
    InspectionResultMatchesChecklistRule,
    InspectionCompletedHasInspectorRule,
    InspectionCompletedHasResultRule,
    InspectionNotOverdueRule,
)


def register_inspections_validation_rules() -> None:
    """Register the inspection rules with the platform rule registry."""
    for rule_class in INSPECTIONS_RULES:
        rule_registry.register(rule_class(), [INSPECTIONS_RULE_SET])


__all__ = ["INSPECTIONS_RULES", "INSPECTIONS_RULE_SET", "register_inspections_validation_rules"]
