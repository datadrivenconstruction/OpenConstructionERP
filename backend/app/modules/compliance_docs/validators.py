# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Compliance document validation rules (rule set ``compliance_docs``).

Rules run over a plain dict built by the service, one record under one key::

    {"doc": {"id", "doc_type", "policy_number", "coverage_amount", "currency",
             "effective_date", "expires_at", "status"}}

``metadata['today']`` pins the reference day in tests; otherwise it is the UTC day.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.failure import finding
from app.core.validation.messages import DEFAULT_LOCALE
from app.core.validation.money_rules import blank, section, to_dec
from app.core.validation.quality_rules import QualityRule, parse_day, today_of

COMPLIANCE_DOCS_RULE_SET = "compliance_docs"

DOC_FIELDS = ("doc_type", "policy_number", "coverage_amount", "currency", "effective_date", "expires_at", "status")

_COVERED = ("insurance_", "bond_")
_ISO_CURRENCY = re.compile(r"^[A-Z]{3}$")
_LIVE = frozenset({"active", "expiring_soon"})


def _covered(doc_type: object) -> bool:
    return str(doc_type or "").startswith(_COVERED)


def needs_coverage(doc_type: object) -> bool:
    """True for an insurance or bond document type."""
    return _covered(doc_type)


def coverage_missing(doc_type: object, coverage_amount: object) -> bool:
    """True for an insurance or bond document with no coverage amount above zero."""
    if not _covered(doc_type):
        return False
    amount = to_dec(coverage_amount)
    return amount is None or amount <= 0


class _ComplianceRule(QualityRule):
    standard = COMPLIANCE_DOCS_RULE_SET
    message_section = "compliance_docs"


class CoverageAmountRule(_ComplianceRule):
    """An insurance policy or bond states the amount it covers; missing it warns, the document still saves."""

    rule_id = "compliance_docs.coverage_amount"
    name = "Insurance or bond states its coverage"
    severity = Severity.WARNING
    description = "insurance and bond documents should carry coverage_amount above zero"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        doc = section(context, "doc")
        ref = str(doc.get("id", ""))
        if coverage_missing(doc.get("doc_type"), doc.get("coverage_amount")):
            return [self.fail(context, "coverage_missing", ref=ref, kind=doc.get("doc_type"))]
        return [self.ok(ref)]


class CurrencyCodeRule(_ComplianceRule):
    """A stated currency is an ISO 4217 code; blank means the project currency."""

    rule_id = "compliance_docs.currency_code"
    name = "Currency is an ISO code"
    description = "currency, when given, must be three capital letters"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        doc = section(context, "doc")
        ref = str(doc.get("id", ""))
        raw = doc.get("currency")
        if not blank(raw) and not _ISO_CURRENCY.match(str(raw).strip()):
            return [self.fail(context, "currency_invalid", ref=ref, currency=str(raw).strip())]
        return [self.ok(ref)]


class StatusMatchesDatesRule(_ComplianceRule):
    """A status set by hand does not contradict the validity dates."""

    rule_id = "compliance_docs.status_matches_dates"
    name = "Status agrees with the validity dates"
    description = "a live status needs an unexpired window; expired needs a lapsed one"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        doc = section(context, "doc")
        ref = str(doc.get("id", ""))
        status = doc.get("status")
        expires = parse_day(doc.get("expires_at"))
        if expires is not None:
            today = today_of(context)
            if (status in _LIVE and expires < today) or (status == "expired" and expires >= today):
                return [self.fail(context, "status_contradicts_dates", ref=ref, status=status, expires=expires)]
        return [self.ok(ref)]


class PolicyNumberRule(_ComplianceRule):
    """An insurance policy or bond carries the number an auditor can look it up by."""

    rule_id = "compliance_docs.policy_number"
    name = "Insurance or bond has a policy number"
    severity = Severity.WARNING
    description = "insurance and bond documents should carry policy_number"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        doc = section(context, "doc")
        ref = str(doc.get("id", ""))
        if _covered(doc.get("doc_type")) and blank(doc.get("policy_number")):
            return [self.fail(context, "policy_number_missing", ref=ref, kind=doc.get("doc_type"))]
        return [self.ok(ref)]


COMPLIANCE_DOCS_RULES = (CoverageAmountRule, CurrencyCodeRule, StatusMatchesDatesRule, PolicyNumberRule)


def coverage_findings(doc: Any, locale: str = DEFAULT_LOCALE) -> list[dict[str, Any]]:
    """The coverage warning of one stored document, in the response shape."""
    doc_type = getattr(doc, "doc_type", None)
    if not coverage_missing(doc_type, getattr(doc, "coverage_amount", None)):
        return []
    rule = CoverageAmountRule()
    ctx = ValidationContext(data={}, metadata={"locale": locale})
    return [finding(rule.fail(ctx, "coverage_missing", ref=str(getattr(doc, "id", "") or ""), kind=doc_type))]


def register_compliance_docs_validation_rules() -> None:
    """Register the compliance document rules with the platform rule registry."""
    for rule_class in COMPLIANCE_DOCS_RULES:
        rule_registry.register(rule_class(), [COMPLIANCE_DOCS_RULE_SET])


__all__ = [
    "COMPLIANCE_DOCS_RULES",
    "COMPLIANCE_DOCS_RULE_SET",
    "DOC_FIELDS",
    "CoverageAmountRule",
    "coverage_findings",
    "coverage_missing",
    "needs_coverage",
    "register_compliance_docs_validation_rules",
]
