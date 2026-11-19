# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rules on a subcontract deduction statement and on a bidder radius search.

Two neutral sets:

* ``subcontract_terms`` reads the statement built by
  ``subcontractors.terms.build_deductions``: the levy lines and retention must
  add up to the payable amount, and the payment discount must be its rate of
  the payable. Country packs register their own rules into the same set.
* ``bidder_search`` reads ``{"radius_km", "recipients": [...]}`` and names each
  firm farther from the site than the radius (information only).

The checks themselves live in ``app.modules.subcontractors.terms_checks``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
)
from app.core.validation.messages import translate

SUBCONTRACT_TERMS_RULE_SET = "subcontract_terms"
BIDDER_SEARCH_RULE_SET = "bidder_search"


def _locale(context: ValidationContext) -> str:
    meta = getattr(context, "metadata", None) or {}
    return str(meta.get("locale") or "en")


class FindingRule(ValidationRule):
    """Run one pure check returning ``Finding`` objects and translate them.

    Subclasses set :meth:`check`; :meth:`applies` may switch a rule off for a
    payload (a country rule off another country) so it returns nothing at all.
    """

    standard = "subcontract"
    emit_pass = True

    def applies(self, payload: dict[str, Any]) -> bool:
        return True

    def check(self, payload: dict[str, Any]) -> list[Any]:
        raise NotImplementedError

    def extra_params(self, payload: dict[str, Any]) -> dict[str, str]:
        return {}

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _locale(context)
        payload = context.data if isinstance(context.data, dict) else {}
        if not payload or not self.applies(payload):
            return []
        findings = self.check(payload)
        if not findings:
            if not self.emit_pass:
                return []
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message=translate("common.ok", locale=locale),
                )
            ]
        extra = self.extra_params(payload)
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=translate(f"{self.rule_id}.fail", locale=locale, **{**extra, **finding.params}),
                element_ref=finding.element_ref,
                details=dict(finding.details),
                suggestion=translate(f"{self.rule_id}.suggestion", locale=locale),
            )
            for finding in findings
        ]


def _check(name: str) -> Callable[[dict[str, Any]], list[Any]]:
    def run(payload: dict[str, Any]) -> list[Any]:
        from app.modules.subcontractors import terms_checks

        return getattr(terms_checks, name)(payload)

    return run


class SubcontractLeviesReconcile(FindingRule):
    """Work value less levies and retention equals the payable amount."""

    rule_id = "subcontract.levies_reconcile"
    name = "Subcontract Levies Reconcile"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags a deduction statement whose levy lines and retention do not add up to the payable amount."

    def check(self, payload: dict[str, Any]) -> list[Any]:
        return _check("check_levies_reconcile")(payload)


class SubcontractPaymentDiscountReconciles(FindingRule):
    """The payment discount is its agreed rate of the payable amount."""

    rule_id = "subcontract.payment_discount_reconciles"
    name = "Subcontract Payment Discount Reconciles"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags a payment discount that is not its rate of the payable amount."

    def check(self, payload: dict[str, Any]) -> list[Any]:
        return _check("check_discount_reconciles")(payload)


class TenderRecipientOutsideRadius(FindingRule):
    """A firm on the bidder list is farther from the site than the search radius."""

    rule_id = "tender.recipient_outside_radius"
    name = "Tender Recipient Outside Radius"
    severity = Severity.INFO
    category = RuleCategory.CONSISTENCY
    standard = "tender"
    emit_pass = False
    description = "Names each firm on the bidder list that lies outside the search radius around the site."

    def check(self, payload: dict[str, Any]) -> list[Any]:
        return _check("check_recipient_outside_radius")(payload)


SUBCONTRACT_TERMS_RULES: tuple[tuple[ValidationRule, list[str]], ...] = (
    (SubcontractLeviesReconcile(), [SUBCONTRACT_TERMS_RULE_SET]),
    (SubcontractPaymentDiscountReconciles(), [SUBCONTRACT_TERMS_RULE_SET]),
    (TenderRecipientOutsideRadius(), [BIDDER_SEARCH_RULE_SET]),
)

__all__ = [
    "BIDDER_SEARCH_RULE_SET",
    "SUBCONTRACT_TERMS_RULES",
    "SUBCONTRACT_TERMS_RULE_SET",
    "FindingRule",
    "SubcontractLeviesReconcile",
    "SubcontractPaymentDiscountReconciles",
    "TenderRecipientOutsideRadius",
]
