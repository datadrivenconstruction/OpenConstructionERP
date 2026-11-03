# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules for answers saved to a project record.

Rule set ``doc_assistant_answer``:

* ``doc_assistant_answer.citations_present`` - WARNING. An answer kept on a
  note or an RFI without a single citation is an unsourced statement that
  reads like a project fact. It is saved (the person may want the text) but
  flagged, so a reviewer knows nothing in the documents backs it.
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
from app.core.validation.messages import translate

DOC_ASSISTANT_RULE_SET = "doc_assistant_answer"


def _locale(context: ValidationContext) -> str:
    locale = (context.metadata or {}).get("locale")
    return locale.strip() if isinstance(locale, str) and locale.strip() else "en"


class SavedAnswerHasCitations(ValidationRule):
    """An answer saved to a record must cite at least one project document."""

    rule_id = "doc_assistant_answer.citations_present"
    name = "Saved answer cites its sources"
    standard = DOC_ASSISTANT_RULE_SET
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "An answer saved to a note or RFI without citations is an unsourced statement."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        citations = [c for c in data.get("citations") or [] if isinstance(c, dict) and c.get("source_id")]
        passed = bool(citations)
        locale = _locale(context)
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message="OK" if passed else translate("doc_assistant.citations_present.fail", locale),
                element_ref=str(data.get("target_id") or "") or None,
                suggestion=None if passed else translate("doc_assistant.citations_present.suggestion", locale),
                details={"citations": len(citations)},
            )
        ]


_RULES: list[ValidationRule] = [SavedAnswerHasCitations()]


def register_doc_assistant_rules() -> None:
    """Register the rule set; idempotent (the registry overwrites by id)."""
    for rule in _RULES:
        rule_registry.register(rule, [DOC_ASSISTANT_RULE_SET])
