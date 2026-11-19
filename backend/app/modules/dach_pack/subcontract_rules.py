# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""German rules on a subcontract deduction statement (VOB/B).

Registered into the neutral ``subcontract_terms`` set and silent unless the
project is in Germany. The retention ceiling is read from this pack's own
``progress_billing`` block, never written here.

* ``de.payment_discount_unagreed``: a payment discount (Skonto) taken that the
  contract does not state; VOB/B section 16 (5) no. 2 allows it only when agreed.
* ``de.retention_over_vob_cap``: retention above the per-payment maximum of
  VOB/B section 17 (6) no. 1.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.validation.engine import RuleCategory, Severity
from app.core.validation.rules.subcontract_terms import SUBCONTRACT_TERMS_RULE_SET, FindingRule
from app.modules.subcontractors.terms import money, opt_decimal
from app.modules.subcontractors.validators import Finding

COUNTRY = "DE"


def vob_retention_maximum() -> tuple[Decimal | None, str]:
    """The per-payment retention maximum and its statute, from the DE progress billing block."""
    from app.core.regional_packs import resolve_progress_billing

    figures = resolve_progress_billing(country_code=COUNTRY) or {}
    policy = figures.get("retention_policy") or {}
    if not policy.get("rate_is_maximum"):
        return None, ""
    rates = [opt_decimal(t.get("rate")) for t in policy.get("tiers") or [] if isinstance(t, dict)]
    rates = [r for r in rates if r is not None]
    return (max(rates) if rates else None), str(policy.get("statute_reference") or "")


def check_payment_discount_unagreed(payload: dict[str, Any]) -> list[Finding]:
    """A discount is computed on the statement but the contract does not state it."""
    if money(payload.get("payment_discount_amount")) <= 0 or payload.get("payment_discount_agreed"):
        return []
    return [
        Finding(
            element_ref=str(payload.get("element_ref") or ""),
            params={"discount": f"{money(payload.get('payment_discount_amount')):.2f}"},
        )
    ]


def check_retention_over_vob_cap(payload: dict[str, Any], maximum: Decimal | None) -> list[Finding]:
    """Retention per payment above the VOB/B maximum."""
    rate = opt_decimal(payload.get("retention_percent"))
    if maximum is None or rate is None or rate <= maximum:
        return []
    return [
        Finding(
            element_ref=str(payload.get("element_ref") or ""),
            params={"rate": f"{rate.normalize():f}", "maximum": f"{maximum.normalize():f}"},
        )
    ]


class _GermanRule(FindingRule):
    standard = "vob"

    def applies(self, payload: dict[str, Any]) -> bool:
        return str(payload.get("country_code") or "").upper() == COUNTRY


class DePaymentDiscountUnagreed(_GermanRule):
    """Payment discount used but not agreed in the contract (VOB/B 16 (5) 2)."""

    rule_id = "de.payment_discount_unagreed"
    name = "Payment Discount Not Agreed (VOB/B)"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Flags a payment discount on a German subcontract that the contract does not state."

    def check(self, payload: dict[str, Any]) -> list[Any]:
        return check_payment_discount_unagreed(payload)


class DeRetentionOverVobCap(_GermanRule):
    """Retention above the per-payment maximum of VOB/B 17 (6) 1."""

    rule_id = "de.retention_over_vob_cap"
    name = "Retention Above VOB/B Maximum"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Flags retention per payment above the VOB/B maximum on a German subcontract."

    def check(self, payload: dict[str, Any]) -> list[Any]:
        maximum, _statute = vob_retention_maximum()
        return check_retention_over_vob_cap(payload, maximum)


GERMAN_SUBCONTRACT_RULES = (DePaymentDiscountUnagreed, DeRetentionOverVobCap)


def register_german_subcontract_rules() -> None:
    """Register the German deduction rules into the ``subcontract_terms`` set."""
    from app.core.validation.engine import rule_registry

    for rule in GERMAN_SUBCONTRACT_RULES:
        rule_registry.register(rule(), rule_sets=[SUBCONTRACT_TERMS_RULE_SET])
