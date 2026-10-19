# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation of the VAT regime a contract is taxed under.

A contract states its regime in ``terms["vat_regime"]``::

    {"code": "EG_CONSTR_TRANSITIONAL_36",
     "evidence": {"approved_certificate": {"reference": "IPC-07", "issued_on": "2025-06-30"},
                  "einvoice": {"reference": "...", "issued_on": "2025-07-02"}},
     "allowed_increase_pct": "25"}

A contract that states none is on the default regime of its activity and
nothing here reports on it. The regimes and their conditions are data in
:mod:`app.core.vat_regimes`; these rules only read a contract against them, so
a country is added there, never here.

Three rules:

* ``contracts.vat_regime_known`` (ERROR, WARNING without a project country) -
  the regime exists for the project's country.
* ``contracts.vat_regime_eligible`` (ERROR, WARNING for a scope increase the
  contract sets no limit for) - the contract meets the regime's conditions:
  signed before its cutoff, holding the evidence it needs, dated before the
  cutoff, and not grown into a new contract.
* ``pay_application.vat_regime_in_force`` (ERROR) - a claim is dated inside
  the regime's window, so a certificate dated after a regime ended is not
  billed under it.

The contract rules run in the ``contracts`` rule set, so an ineligible regime
blocks putting the contract up for signature and shows on its completeness
panel; the claim rule runs when a claim is submitted.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, ValidationRule
from app.core.vat_regimes import ContractFacts, Evidence, Finding, eligibility_findings, lookup, regimes_for
from app.core.vat_regimes import window_findings as regime_window_findings
from app.modules.contracts.messages import translate

__all__ = [
    "VAT_REGIME_CONTEXT_KEY",
    "ClaimVatRegimeInForceRule",
    "ContractVatRegimeEligibleRule",
    "ContractVatRegimeKnownRule",
    "contract_facts",
    "stated_regime",
]

#: Where the claim context carries the contract's regime.
VAT_REGIME_CONTEXT_KEY = "vat_regime"

#: Message keys per finding, written out so the message test can read them.
_FINDING_MESSAGES: dict[str, tuple[str, str]] = {
    "contract_date_missing": (
        "vat_regime.contract_date_missing.fail",
        "vat_regime.contract_date_missing.suggestion",
    ),
    "contract_too_late": ("vat_regime.contract_too_late.fail", "vat_regime.contract_too_late.suggestion"),
    "evidence_missing": ("vat_regime.evidence_missing.fail", "vat_regime.evidence_missing.suggestion"),
    "evidence_date_missing": (
        "vat_regime.evidence_date_missing.fail",
        "vat_regime.evidence_date_missing.suggestion",
    ),
    "evidence_too_late": ("vat_regime.evidence_too_late.fail", "vat_regime.evidence_too_late.suggestion"),
    "scope_increase_unjudged": (
        "vat_regime.scope_increase_unjudged.fail",
        "vat_regime.scope_increase_unjudged.suggestion",
    ),
    "scope_increase_new_contract": (
        "vat_regime.scope_increase_new_contract.fail",
        "vat_regime.scope_increase_new_contract.suggestion",
    ),
}

#: The name of each kind of evidence inside a sentence.
_EVIDENCE_NAMES: dict[str, str] = {
    "approved_certificate": "vat_regime.evidence_kinds.approved_certificate",
    "einvoice": "vat_regime.evidence_kinds.einvoice",
    "main_contractor_certificate": "vat_regime.evidence_kinds.main_contractor_certificate",
}

#: Findings that say "cannot be judged" rather than "does not qualify".
_WARNING_FINDINGS = frozenset({"scope_increase_unjudged"})


def _locale(context: ValidationContext) -> str:
    meta = getattr(context, "metadata", None) or {}
    return str(meta.get("locale") or "en")


def _day(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def _amount(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


def stated_regime(terms: Any) -> Mapping[str, Any] | None:
    """The regime block of a contract's terms, or ``None`` when it states none."""
    if not isinstance(terms, Mapping):
        return None
    block = terms.get("vat_regime")
    if not isinstance(block, Mapping) or not str(block.get("code") or "").strip():
        return None
    return block


def contract_facts(contract: Mapping[str, Any], block: Mapping[str, Any]) -> ContractFacts:
    """Read one contract and its regime block into the facts the eligibility check takes."""
    evidence: dict[str, Evidence] = {}
    raw = block.get("evidence")
    if isinstance(raw, Mapping):
        for kind, item in raw.items():
            if isinstance(item, Mapping):
                evidence[str(kind)] = Evidence(str(item.get("reference") or ""), _day(item.get("issued_on")))
    return ContractFacts(
        signed_on=_day(contract.get("signed_at")),
        started_on=_day(contract.get("start_date")),
        is_subcontract=bool(contract.get("is_subcontract")),
        evidence=evidence,
        original_value=_amount(contract.get("original_contract_value")),
        current_value=_amount(contract.get("total_value")),
        allowed_increase_pct=_amount(block.get("allowed_increase_pct")),
    )


def _params(finding: Finding, locale: str) -> dict[str, str]:
    params = dict(finding.params)
    kind = params.get("evidence")
    if kind in _EVIDENCE_NAMES:
        params["evidence"] = translate(_EVIDENCE_NAMES[kind], locale=locale)
    return params


def _contract(context: ValidationContext) -> dict[str, Any]:
    data = context.data if isinstance(context.data, dict) else {}
    contract = data.get("contract")
    return contract if isinstance(contract, dict) else {}


class ContractVatRegimeKnownRule(ValidationRule):
    """The regime a contract names exists for its project's country."""

    rule_id = "contracts.vat_regime_known"
    name = "VAT regime exists for the project's country"
    standard = "contracts"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "A contract's VAT regime must be one its project's country has"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        contract = _contract(context)
        block = stated_regime(contract.get("terms"))
        if block is None:
            return []
        locale = _locale(context)
        code = str(block["code"]).strip()
        country = str(contract.get("country_code") or "").strip().upper()
        params = {"contract": str(contract.get("code") or contract.get("id") or ""), "regime": code}
        if not country:
            # Nothing to check against yet; said, not passed.
            fail, hint = "vat_regime.country_unknown.fail", "vat_regime.country_unknown.suggestion"
            severity = Severity.WARNING
        elif lookup(regimes_for(country), country=country, code=code) is None:
            fail, hint = "vat_regime.unknown.fail", "vat_regime.unknown.suggestion"
            severity = self.severity
            params["country"] = country
        else:
            return [self._result(contract, passed=True, locale=locale)]
        return [self._result(contract, passed=False, locale=locale, fail=fail, hint=hint, sev=severity, **params)]

    def _result(
        self,
        record: Mapping[str, Any],
        /,
        *,
        passed: bool,
        locale: str,
        fail: str = "",
        hint: str = "",
        sev: Severity | None = None,
        **params: str,
    ) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=sev or self.severity,
            category=self.category,
            passed=passed,
            message=translate("common.ok", locale=locale) if passed else translate(fail, locale=locale, **params),
            element_ref=str(record.get("id", "")),
            suggestion=None if passed else translate(hint, locale=locale),
            details={} if passed else dict(params),
        )


class ContractVatRegimeEligibleRule(ValidationRule):
    """The contract meets the conditions of the regime it names."""

    rule_id = "contracts.vat_regime_eligible"
    name = "Contract qualifies for its VAT regime"
    standard = "contracts"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "A contract taxed under a conditional VAT regime must meet its conditions"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        contract = _contract(context)
        block = stated_regime(contract.get("terms"))
        country = str(contract.get("country_code") or "").strip().upper()
        if block is None or not country:
            return []
        regime = lookup(regimes_for(country), country=country, code=str(block["code"]).strip())
        if regime is None:
            # Reported by contracts.vat_regime_known; one mistake, one finding.
            return []
        locale = _locale(context)
        findings = eligibility_findings(regime, contract_facts(contract, block))
        if not findings:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message=translate("common.ok", locale=locale),
                    element_ref=str(contract.get("id", "")),
                )
            ]
        results: list[RuleResult] = []
        for finding in findings:
            fail, hint = _FINDING_MESSAGES[finding.key]
            params = {**_params(finding, locale), "regime": regime.code}
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=Severity.WARNING if finding.key in _WARNING_FINDINGS else self.severity,
                    category=self.category,
                    passed=False,
                    message=translate(fail, locale=locale, **params),
                    element_ref=str(contract.get("id", "")),
                    suggestion=translate(hint, locale=locale),
                    details={"finding": finding.key, **params},
                )
            )
        return results


class ClaimVatRegimeInForceRule(ValidationRule):
    """A claim is dated inside the window of the regime its contract is taxed under."""

    rule_id = "pay_application.vat_regime_in_force"
    name = "Claim date falls inside the contract's VAT regime"
    standard = "pay_application"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "A claim cannot be billed under a VAT regime that is not in force on its date"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        block = data.get(VAT_REGIME_CONTEXT_KEY)
        claim = data.get("claim") if isinstance(data.get("claim"), dict) else {}
        if not isinstance(block, Mapping) or not claim:
            return []
        country = str(block.get("country_code") or "").strip().upper()
        regimes = regimes_for(country)
        regime = lookup(regimes, country=country, code=str(block.get("code") or "").strip())
        # The day the claim is taxed on: its application date, else the date
        # it carries, else the end of its period.
        on = _day(claim.get("application_date")) or _day(claim.get("claim_date")) or _day(claim.get("period_to"))
        if regime is None or on is None:
            return []
        locale = _locale(context)
        label = str(claim.get("number") or claim.get("id") or "")
        findings = regime_window_findings(regime, regimes, on)
        if not findings:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message=translate("common.ok", locale=locale),
                    element_ref=str(claim.get("id", "")),
                )
            ]
        params = {**dict(findings[0].params), "claim": label}
        fail = "vat_regime.not_in_force.before" if on < regime.effective_from else "vat_regime.not_in_force.after"
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=translate(fail, locale=locale, **params),
                element_ref=str(claim.get("id", "")),
                suggestion=translate("vat_regime.not_in_force.suggestion", locale=locale),
                details=params,
            )
        ]
