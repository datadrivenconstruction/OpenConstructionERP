# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Subcontractor insurance validation rules​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ - the ``subcontractor_insurance`` rule set.

Payload: ``{"as_of": "YYYY-MM-DD", "subcontractor_id": str, "certificates": [...]}``
with each certificate shaped by :func:`app.modules.subcontractors.insurance.certificate_payload`.

* ``subcontractor_insurance.mandatory_certificate_valid`` (error) - a mandatory
  certificate type has no live certificate. An error here blocks finance
  approval and payment (see ``InsuranceComplianceService.assert_payment_allowed``).
* ``subcontractor_insurance.certificate_expiring`` (warning) - a certificate
  expires within 30 days.
* ``subcontractor_insurance.policy_details_recorded`` (warning) - a mandatory
  certificate carries no policy number or no cover amount.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.subcontractors.messages import translate

RULE_SET = "subcontractor_insurance"


def _locale(context: ValidationContext) -> str:
    meta = getattr(context, "metadata", None) or {}
    return str(meta.get("locale") or "en")


def _certs(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data if isinstance(context.data, dict) else {}
    rows = data.get("certificates")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _as_of(context: ValidationContext) -> date | None:
    data = context.data if isinstance(context.data, dict) else {}
    raw = data.get("as_of")
    try:
        return date.fromisoformat(str(raw)[:10]) if raw else None
    except ValueError:
        return None


def _type_label(cert_type: str, locale: str) -> str:
    key = f"subcontractor_insurance.cert_types.{cert_type}"
    word = translate(key, locale=locale)
    return cert_type if word == key else word


def check_mandatory_valid(certs: list[dict[str, Any]], as_of: date) -> list[dict[str, Any]]:
    """Mandatory types with no certificate live on ``as_of``."""
    live: set[str] = set()
    for c in certs:
        until = c.get("valid_until")
        start = c.get("issue_date")
        if c.get("revoked"):
            continue
        if until and date.fromisoformat(until) < as_of:
            continue
        if start and date.fromisoformat(start) > as_of:
            continue
        live.add(str(c.get("cert_type")))
    out: dict[str, dict[str, Any]] = {}
    for c in certs:
        t = str(c.get("cert_type"))
        if c.get("is_mandatory") and t not in live:
            prev = out.get(t)
            if prev is None or (c.get("valid_until") or "") > (prev.get("valid_until") or ""):
                out[t] = c
    return [out[k] for k in sorted(out)]


def check_expiring(certs: list[dict[str, Any]], as_of: date, days: int = 30) -> list[dict[str, Any]]:
    """Live certificates that expire within ``days``."""
    found = []
    for c in certs:
        until = c.get("valid_until")
        if c.get("revoked") or not until:
            continue
        delta = (date.fromisoformat(until) - as_of).days
        if 0 <= delta <= days:
            found.append({**c, "days_to_expiry": delta})
    return found


def check_policy_details(certs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mandatory certificates without policy number or cover amount."""
    return [c for c in certs if c.get("is_mandatory") and (not c.get("policy_number") or not c.get("coverage_amount"))]


class _InsuranceRule(ValidationRule):
    standard = RULE_SET

    def _ok(self, locale: str) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=True,
            message=translate("common.ok", locale=locale),
        )

    def _fail(self, locale: str, cert: dict[str, Any], **params: Any) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=False,
            message=translate(f"{self.rule_id}.fail", locale=locale, **params),
            element_ref=str(cert.get("id") or ""),
            details={"certificate_id": cert.get("id"), "cert_type": cert.get("cert_type")},
            suggestion=translate(f"{self.rule_id}.suggestion", locale=locale),
        )


class MandatoryCertificateValid(_InsuranceRule):
    """A mandatory insurance certificate must be live; a lapse blocks payment."""

    rule_id = "subcontractor_insurance.mandatory_certificate_valid"
    name = "Mandatory Insurance Certificate Valid"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Blocks payment while a mandatory insurance certificate has lapsed or was revoked."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        certs, as_of, locale = _certs(context), _as_of(context), _locale(context)
        if as_of is None or not any(c.get("is_mandatory") for c in certs):
            return []
        bad = check_mandatory_valid(certs, as_of)
        if not bad:
            return [self._ok(locale)]
        return [
            self._fail(
                locale,
                c,
                document=_type_label(str(c.get("cert_type")), locale),
                date=c.get("valid_until") or "-",
            )
            for c in bad
        ]


class CertificateExpiring(_InsuranceRule):
    """A certificate expiring within 30 days needs renewing before it blocks payment."""

    rule_id = "subcontractor_insurance.certificate_expiring"
    name = "Insurance Certificate Expiring"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Flags an insurance certificate that expires within 30 days."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        certs, as_of, locale = _certs(context), _as_of(context), _locale(context)
        if as_of is None or not certs:
            return []
        found = check_expiring(certs, as_of)
        if not found:
            return [self._ok(locale)]
        return [
            self._fail(
                locale,
                c,
                document=_type_label(str(c.get("cert_type")), locale),
                date=c.get("valid_until"),
                days=c["days_to_expiry"],
            )
            for c in found
        ]


class PolicyDetailsRecorded(_InsuranceRule):
    """A mandatory certificate should name its policy and its cover."""

    rule_id = "subcontractor_insurance.policy_details_recorded"
    name = "Insurance Policy Details Recorded"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags a mandatory insurance certificate with no policy number or cover amount."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        certs, locale = _certs(context), _locale(context)
        if not any(c.get("is_mandatory") for c in certs):
            return []
        found = check_policy_details(certs)
        if not found:
            return [self._ok(locale)]
        return [self._fail(locale, c, document=_type_label(str(c.get("cert_type")), locale)) for c in found]


INSURANCE_RULES: tuple[type[ValidationRule], ...] = (
    MandatoryCertificateValid,
    CertificateExpiring,
    PolicyDetailsRecorded,
)


def register_insurance_rules() -> str:
    """Register the rule set once; a second call is a no-op."""
    if rule_registry.has_rules(RULE_SET):
        return RULE_SET
    for rule_class in INSURANCE_RULES:
        rule_registry.register(rule_class(), [RULE_SET])
    return RULE_SET
