# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Review-authority validation rules.

Ships one first-class rule with the platform rule registry:

* ``ReviewCycleCompletenessRule`` (ERROR) - a review cycle that has been
  submitted must carry a pinned document version, and must not be moved to a
  final approved decision while remarks are still unresolved (``open`` or
  ``responded``). Both are blocking gaps in the review record.

The rule runs against a plain dict context (no ORM), shaped by the service /
caller as::

    {
        "cycle": {"status": ..., "pinned_document_version": ...},
        "remarks": [{"ordinal": ..., "status": ...}, ...],
    }

Keeping it pure makes it trivially unit-testable and satisfies the platform
"no module without validation rules" requirement.

NOTE: the shared rule file ``app/core/validation/rules/__init__.py`` is NOT
edited by this module; the rule is defined here and registered at module
startup via :func:`register_review_authority_validation_rules`, exactly as the
closeout module does. If the platform later moves to central registration, this
rule class is ready to be referenced from there unchanged.
"""

from __future__ import annotations

import logging

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

logger = logging.getLogger(__name__)

# Cycle statuses that mean "the authority is actively reviewing a pinned set",
# so a pinned version is mandatory.
_SUBMITTED_STATES = frozenset(
    {"submitted", "under_review", "remarks_issued", "responding", "resubmitted", "approved", "rejected"}
)
# Remark statuses that are not yet resolved.
_UNRESOLVED_REMARK_STATES = frozenset({"open", "responded"})


class ReviewCycleCompletenessRule(ValidationRule):
    """A submitted cycle needs a pinned version and no unresolved remarks at approval."""

    rule_id = "review_authority.cycle_completeness"
    name = "Review cycle completeness"
    standard = "review_authority"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = (
        "A submitted review cycle must have a pinned document version, and must "
        "not be approved while remarks remain unresolved"
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        cycle = data.get("cycle") if isinstance(data.get("cycle"), dict) else {}
        remarks = data.get("remarks") if isinstance(data.get("remarks"), list) else []

        status = str(cycle.get("status", "draft"))
        results: list[RuleResult] = []

        # 1. A submitted (or later) cycle must have a pinned document version.
        if status in _SUBMITTED_STATES:
            pinned = cycle.get("pinned_document_version")
            passed = bool(pinned)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK" if passed else "Submitted cycle has no pinned document version",
                    element_ref=str(cycle.get("id") or ""),
                    suggestion=None if passed else "Submit the cycle so the reviewed document version is frozen",
                )
            )

        # 2. An approved cycle must not carry unresolved remarks.
        if status == "approved":
            unresolved = [
                r for r in remarks if isinstance(r, dict) and str(r.get("status", "open")) in _UNRESOLVED_REMARK_STATES
            ]
            passed = not unresolved
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=("OK" if passed else f"{len(unresolved)} remark(s) still unresolved on an approved cycle"),
                    element_ref=str(cycle.get("id") or ""),
                    suggestion=None if passed else "Resolve every remark (accept / contest / withdraw) before approval",
                )
            )

        return results


def register_review_authority_validation_rules() -> None:
    """Register the review-authority rules with the platform rule registry."""
    rule_registry.register(ReviewCycleCompletenessRule(), ["review_authority"])
    logger.debug("review_authority: registered 1 validation rule")


__all__ = [
    "ReviewCycleCompletenessRule",
    "register_review_authority_validation_rules",
]
