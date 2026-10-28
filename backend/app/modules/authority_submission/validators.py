# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rule for the authority-submission factory.

``submission_schema_valid`` is the gate that a submission must pass before it can
be marked submitted: the payload has to satisfy its profile's ``field_spec`` (no
missing required fields, no type mismatches). It reuses the pure
:func:`app.modules.authority_submission.service.validate_payload` engine so the
rule and the ``/validate`` endpoint can never disagree.
"""

from __future__ import annotations

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.authority_submission.service import validate_payload


class SubmissionSchemaValid(ValidationRule):
    """A submission validates cleanly against its profile's field spec.

    ``context.data`` is expected to carry ``payload`` and ``field_spec`` keys
    (the submission's payload and its profile's field spec). One aggregate
    result is returned so the rule reads as a single pass/fail in the dashboard,
    with the per-field detail in ``details``.
    """

    rule_id = "authority_submission.schema_valid"
    name = "Authority submission schema valid"
    standard = "authority_submission"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = (
        "The submission payload must satisfy its profile's field spec - all "
        "required fields present and correctly typed - before it can be sent."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data or {}
        payload = data.get("payload", {}) if isinstance(data, dict) else {}
        field_spec = data.get("field_spec", []) if isinstance(data, dict) else []

        report = validate_payload(payload, field_spec)
        passed = report["status"] == "passed"
        if passed:
            message = "All required fields present and correctly typed."
        else:
            problems = report["missing_required"] or [m["field"] for m in report["type_mismatches"]]
            message = "Schema check failed: " + ", ".join(problems[:8])

        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message=message,
                element_ref=context.project_id,
                details=report,
                suggestion=(None if passed else "Fill the missing / mistyped fields, then re-validate."),
            )
        ]


def register_authority_submission_rules() -> None:
    """Register the authority-submission validation rule(s)."""
    rule_registry.register(SubmissionSchemaValid(), rule_sets=["authority_submission"])


__all__ = ["SubmissionSchemaValid", "register_authority_submission_rules"]
