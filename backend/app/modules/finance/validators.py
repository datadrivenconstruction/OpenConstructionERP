# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Finance validation rules.

One rule, registered under the ``finance`` rule set:

* ``finance.invoice_agrees_with_certificate`` - ERROR. An invoice raised from a
  certified payment certificate carries the certificate's amount before VAT and
  its VAT, in its currency. The certificate is what the two parties signed, so
  an invoice that says something else bills an amount nobody certified.

The rule reads a plain dict, so the figures can be checked before anything is
stored or exported::

    {"record_type": "claim_invoice",
     "invoice_number", "currency_code", "amount_subtotal", "tax_amount",
     "certificate": {"currency_code", "net_amount", "vat_computed"}}

``vat_computed`` is ``None`` while the certificate's VAT is held; the rule then
compares what it can and leaves the held figure to the rule that owns it. The
comparison itself is :func:`app.modules.finance.einvoice_tr.agreement_problems`,
which the e-invoice export calls too, so the two cannot give different answers.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
    validation_engine,
)

logger = logging.getLogger(__name__)

__all__ = [
    "FINANCE_RULE_SET",
    "RECORD_CLAIM_INVOICE",
    "InvoiceAgreesWithCertificate",
    "evaluate_claim_invoice",
    "register_finance_rules",
]

FINANCE_RULE_SET = "finance"
RECORD_CLAIM_INVOICE = "claim_invoice"


def _amount(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


class InvoiceAgreesWithCertificate(ValidationRule):
    rule_id = "finance.invoice_agrees_with_certificate"
    name = "Invoice Agrees With Its Payment Certificate"
    standard = "finance"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = (
        "An invoice raised from a certified payment certificate must carry the certificate's amount "
        "before VAT, its VAT and its currency."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        from app.modules.finance.einvoice_tr import agreement_problems

        record = context.data if isinstance(context.data, dict) else {}
        if str(record.get("record_type") or "") != RECORD_CLAIM_INVOICE:
            return []
        certificate = record.get("certificate") if isinstance(record.get("certificate"), dict) else {}
        problems = agreement_problems(
            invoice_net=_amount(record.get("amount_subtotal")) or Decimal("0"),
            invoice_vat=_amount(record.get("tax_amount")) or Decimal("0"),
            invoice_currency=str(record.get("currency_code") or ""),
            taxes_net=_amount(certificate.get("net_amount")),
            taxes_vat=_amount(certificate.get("vat_computed")),
            taxes_currency=str(certificate.get("currency_code") or ""),
        )
        number = str(record.get("invoice_number") or "")
        details = {
            "invoice_number": number,
            "currency_code": str(record.get("currency_code") or ""),
            "amount_subtotal": str(record.get("amount_subtotal") or ""),
            "tax_amount": str(record.get("tax_amount") or ""),
            "certificate_net_amount": str(certificate.get("net_amount") or ""),
            "certificate_vat_computed": str(certificate.get("vat_computed") or ""),
            "differences": problems,
        }
        message = (
            f"Invoice {number} agrees with its payment certificate"
            if not problems
            else f"Invoice {number} does not agree with its payment certificate: " + "; ".join(problems)
        )
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=not problems,
                message=message,
                element_ref=number or None,
                suggestion=(
                    None
                    if not problems
                    else "Correct the invoice to the certified figures, or reopen the certificate and certify again."
                ),
                details=details,
            )
        ]


_FINANCE_RULES: tuple[ValidationRule, ...] = (InvoiceAgreesWithCertificate(),)


def register_finance_rules() -> None:
    """Register the module's validation rules. Idempotent: the registry overwrites by id."""
    for rule in _FINANCE_RULES:
        rule_registry.register(rule, [FINANCE_RULE_SET])
    logger.debug("Registered %d finance validation rules", len(_FINANCE_RULES))


async def evaluate_claim_invoice(record: dict[str, Any], *, record_id: str = "") -> list[RuleResult]:
    """Run the finance rules over one claim invoice record and return the failures.

    Guarded like the other module rule runners: a broken rule degrades to no
    findings and a log line. The export does not rely on this for its own
    refusal; it calls the comparison directly.
    """
    try:
        report = await validation_engine.validate(
            data={**record, "record_type": RECORD_CLAIM_INVOICE},
            rule_sets=[FINANCE_RULE_SET],
            target_type=RECORD_CLAIM_INVOICE,
            target_id=record_id,
        )
    except Exception:  # noqa: BLE001 - validation augments; it never breaks the caller
        logger.warning("finance validation failed for record %s", record_id, exc_info=True)
        return []
    return [result for result in report.results if not result.passed and not result.is_engine_error]
