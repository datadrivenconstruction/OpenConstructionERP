# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Work-type route classifier validation rules.

Ships one first-class rule registered with the platform rule registry:

* ``RouteDeterminedRule`` (ERROR) - a project must have a *confirmed* route
  assessment whose route is not ``undetermined`` before it proceeds. An
  unclassified or still-draft project is a blocking gap.

The rule runs against a plain dict context (no ORM), shaped by the service /
caller as ``{"assessments": [{status, determined_route}], "project_id": ...}``
(a single assessment dict or a bare list is also accepted). This keeps the rule
pure and trivially unit-testable while satisfying the platform "no module
without validation rules" requirement.
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


def _assessments(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data
    if isinstance(data, dict):
        if "assessments" in data:
            items = data.get("assessments", [])
            return [a for a in items if isinstance(a, dict)]
        # A single assessment dict.
        return [data]
    if isinstance(data, list):
        return [a for a in data if isinstance(a, dict)]
    return []


class RouteDeterminedRule(ValidationRule):
    """A confirmed, non-undetermined delivery route must exist for the project."""

    rule_id = "project_route.route_determined"
    name = "Delivery route determined"
    standard = "project_route"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "The project must have a confirmed delivery / permit route before it proceeds"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        assessments = _assessments(context)
        confirmed = [
            a
            for a in assessments
            if str(a.get("status")) == "confirmed"
            and str(a.get("determined_route") or "undetermined") != "undetermined"
        ]
        passed = bool(confirmed)
        if passed:
            message = "OK"
            suggestion = None
        elif not assessments:
            message = "No work-type route assessment exists for this project"
            suggestion = "Classify the project's work type and confirm its delivery route"
        else:
            message = "No confirmed delivery route (assessment is still draft or undetermined)"
            suggestion = "Confirm a determined route before the project proceeds"
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message=message,
                element_ref=str(context.project_id) if context.project_id else None,
                suggestion=suggestion,
            )
        ]


def register_project_route_validation_rules() -> None:
    """Register the work-type route rules with the platform rule registry."""
    rule_registry.register(RouteDeterminedRule(), ["project_route"])
    logger.debug("project_route: registered 1 validation rule")
