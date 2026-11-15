# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Compliance document validation rules (rule set ``compliance_docs``).

* ``compliance_docs.coverage_amount_recorded`` (warning): an insurance or bond document has no
  coverage amount. The document still saves; the finding rides on the response.

Rules read ``context.data["compliance_doc"]`` = ``{"id", "doc_type", "coverage_amount"}``.
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
from app.core.validation.messages import DEFAULT_LOCALE, translate

COMPLIANCE_RULE_SET = "compliance_docs"
COVERAGE_RULE_ID = "compliance_docs.coverage_amount_recorded"
_COVERAGE_PREFIXES = ("insurance_", "bond_")


def needs_coverage(doc_type: str) -> bool:
    return doc_type.startswith(_COVERAGE_PREFIXES)


def coverage_missing(doc_type: str, coverage_amount: Any) -> bool:
    """True for an insurance or bond document with no coverage amount (zero counts as missing)."""
    return needs_coverage(doc_type) and not coverage_amount


def coverage_findings(doc: Any, locale: str = DEFAULT_LOCALE) -> list[dict[str, Any]]:
    """The non-blocking findings of one stored document, in the response shape."""
    doc_type = str(getattr(doc, "doc_type", "") or "")
    if not coverage_missing(doc_type, getattr(doc, "coverage_amount", None)):
        return []
    return [
        {
            "rule_id": COVERAGE_RULE_ID,
            "severity": "warning",
            "message": translate(f"{COVERAGE_RULE_ID}.fail", locale, doc_type=doc_type),
            "suggestion": translate(f"{COVERAGE_RULE_ID}.suggestion", locale),
        }
    ]


class CoverageAmountRecorded(ValidationRule):
    rule_id = COVERAGE_RULE_ID
    name = "Coverage amount recorded"
    standard = "universal"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "An insurance or bond document should state its coverage amount."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        doc = data.get("compliance_doc")
        if not isinstance(doc, dict):
            return []
        meta = getattr(context, "metadata", None)
        locale = meta.get("locale") if isinstance(meta, dict) and meta.get("locale") else DEFAULT_LOCALE
        ref = str(doc.get("id") or "")
        doc_type = str(doc.get("doc_type") or "")
        failed = coverage_missing(doc_type, doc.get("coverage_amount"))
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=not failed,
                message=translate(f"{self.rule_id}.fail", locale, doc_type=doc_type) if failed else "",
                element_ref=ref,
                suggestion=translate(f"{self.rule_id}.suggestion", locale) if failed else None,
            )
        ]


def register_compliance_docs_rules() -> None:
    rule_registry.register(CoverageAmountRecorded(), [COMPLIANCE_RULE_SET])
