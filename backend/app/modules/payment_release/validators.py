# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Invoice and payment release rules V11 to V14 and V16 to V19, rule set ``payment_release``.

The checks a controller runs before money leaves the project, in the order an
invoice goes through its release. V15 (a supplier invoice belongs to a
contract) lives in the ``cost_chain`` set next to the other chain rules. Each
rule reads one plain-data payload under ``context.data["payment_release"]``
(built by :meth:`PaymentReleaseService.rules_payload`) and is silent on any
other data.

* V11 ``invoice_sequence``: one invoice mode per contract. On a cumulative
  contract an interim never states less than the one before it (a reduction
  is a credit note), nothing in the series follows the final invoice, and an
  invoice raised from a claim (an increment) is pointed out on a cumulative
  contract.
* V12 ``release_recomputed``: the release is recomputed on the server; a
  confirmed release that no longer matches its terms is an error, and a
  rounding amount is never negative and always below the agreed step.
* V13 ``retention_terms``: retention follows the terms. Retention on a final
  invoice only where warranty retention is agreed, never more paid back than
  held, a posting only after its release event (for warranty retention, after
  the defects period), and retention still held on a completed contract is
  pointed out.
* V14 ``early_payment_discount``: a discount only where the contract allows
  one, and only when the rest was paid by the discount date. The previous
  releases the next invoice deducts are always before discount.
* V16 ``invoiced_within_value``: what is invoiced stays within what is
  measured (quantity times rate); a contract without measurement stays within
  its value.
* V17 ``invoice_vat``: every line of an invoice that carries VAT states its
  rate, and a reverse charged invoice carries no VAT.
* V18 ``duplicate_invoice``: the same contractor's invoice number once, and
  the same contractor, amount and date pointed out as a possible duplicate.
* V19 ``release_certificates``: where the pack makes a certificate a
  condition of paying (a social insurance clearance), an interim or final
  invoice is released only while the payee holds one valid on the release
  date (:mod:`app.modules.payment_release.release_certificates`).

Messages come from the validation message bundle in the caller's locale.
"""

from __future__ import annotations

import calendar
import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.currency_registry import sentence_amount
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.core.validation.messages import DEFAULT_LOCALE, translate

logger = logging.getLogger(__name__)

RULE_SET = "payment_release"
PAYLOAD_KEY = "payment_release"

#: Money the comparisons let pass as rounding.
MONEY_TOLERANCE = Decimal("0.01")
#: The VAT category of a reverse charged line (EN 16931 code AE).
REVERSE_CHARGE_CATEGORY = "AE"


def _payload(context: ValidationContext) -> dict[str, Any] | None:
    data = context.data
    if isinstance(data, dict) and isinstance(data.get(PAYLOAD_KEY), dict):
        return data[PAYLOAD_KEY]
    return None


def _locale(context: ValidationContext) -> str:
    metadata = getattr(context, "metadata", None)
    if isinstance(metadata, dict):
        locale = metadata.get("locale")
        if isinstance(locale, str) and locale.strip():
            return locale.strip()
    return DEFAULT_LOCALE


def _dec(raw: object) -> Decimal:
    try:
        value = Decimal(str(raw if raw not in (None, "") else "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")
    return value if value.is_finite() else Decimal("0")


def _date(raw: object) -> date | None:
    text = str(raw or "").strip()[:10]
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def _rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [r for r in payload.get(key) or [] if isinstance(r, dict)]


def _add_months(start: date, months: int) -> date:
    month = start.month - 1 + months
    year = start.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


class _ReleaseRule(ValidationRule):
    """Shared plumbing: payload lookup and translated results."""

    standard = "universal"
    category = RuleCategory.CONSISTENCY

    def _result(
        self,
        context: ValidationContext,
        message_key: str,
        *,
        severity: Severity | None = None,
        element_ref: str | None = None,
        money: tuple[str, ...] = (),
        **params: Any,
    ) -> RuleResult:
        """A failed result. Params named in ``money`` are spelled as amounts in the payload currency."""
        locale = _locale(context)
        currency = str((_payload(context) or {}).get("currency") or "")
        shown = {k: (sentence_amount(_dec(v), currency) if k in money else v) for k, v in params.items()}
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=severity or self.severity,
            category=self.category,
            passed=False,
            message=translate(f"payment_release.{message_key}.fail", locale, **shown),
            element_ref=element_ref,
            details={"problem": message_key, **{k: str(v) for k, v in params.items()}},
            suggestion=translate(f"payment_release.{message_key}.suggestion", locale, **shown),
        )

    def _passed(self) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=True,
            message="",
        )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        if payload is None:
            return []
        found = self.check(context, payload)
        return found or [self._passed()]


class InvoiceSequenceRule(_ReleaseRule):
    """V11: one invoice mode per contract, and a series that only grows up to its final invoice."""

    rule_id = "payment_release.invoice_sequence"
    name = "Invoice sequence follows the invoice mode"
    severity = Severity.ERROR
    description = (
        "On a cumulative contract each interim states at least the total of the one before; nothing in the "
        "series follows the final invoice; claim increments are pointed out on a cumulative contract."
    )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        out: list[RuleResult] = []
        for c in _rows(payload, "contracts"):
            cumulative = c.get("invoice_mode") == "cumulative"
            last_net: Decimal | None = None
            last_number = ""
            final_seen = ""
            for inv in _rows(c, "invoices"):
                kind = str(inv.get("kind") or "")
                if kind not in ("interim", "final"):
                    continue
                number = str(inv.get("number") or "")
                if final_seen:
                    out.append(
                        self._result(
                            context,
                            "invoice_after_final",
                            element_ref=str(inv.get("id") or ""),
                            number=number,
                            final=final_seen,
                            contract=c.get("code") or "",
                        )
                    )
                if kind == "final":
                    final_seen = final_seen or number
                if inv.get("claim"):
                    if cumulative:
                        out.append(
                            self._result(
                                context,
                                "claim_invoice_in_cumulative",
                                severity=Severity.WARNING,
                                element_ref=str(inv.get("id") or ""),
                                number=number,
                                contract=c.get("code") or "",
                            )
                        )
                    continue
                net = _dec(inv.get("net_after"))
                if cumulative and kind == "interim" and last_net is not None and net + MONEY_TOLERANCE < last_net:
                    out.append(
                        self._result(
                            context,
                            "cumulative_total_fell",
                            element_ref=str(inv.get("id") or ""),
                            money=("net", "previous"),
                            number=number,
                            previous_number=last_number,
                            net=str(net),
                            previous=str(last_net),
                            contract=c.get("code") or "",
                        )
                    )
                last_net, last_number = net, number
        return out


class ReleaseRecomputedRule(_ReleaseRule):
    """V12: the release follows the formula; a confirmed release that no longer does is pointed out."""

    rule_id = "payment_release.release_recomputed"
    name = "Release matches its terms"
    severity = Severity.ERROR
    description = (
        "A confirmed release equals the release recomputed from the contract's terms today; a rounding amount is "
        "never negative and stays below the agreed step."
    )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        out: list[RuleResult] = []
        for c in _rows(payload, "contracts"):
            step = _dec(c.get("rounding_step"))
            rounding_on = bool(c.get("rounding_enabled"))
            for inv in _rows(c, "invoices"):
                ref = str(inv.get("id") or "")
                number = str(inv.get("number") or "")
                if inv.get("released"):
                    stored = _dec(inv.get("release"))
                    computed = _dec(inv.get("release_computed"))
                    if abs(stored - computed) > MONEY_TOLERANCE:
                        out.append(
                            self._result(
                                context,
                                "release_differs",
                                element_ref=ref,
                                money=("stored", "computed"),
                                number=number,
                                stored=str(stored),
                                computed=str(computed),
                                contract=c.get("code") or "",
                            )
                        )
                rounding = _dec(inv.get("rounding"))
                if rounding == 0:
                    continue
                if rounding < 0 or not rounding_on or step <= 0 or rounding >= step:
                    out.append(
                        self._result(
                            context,
                            "rounding_out_of_range",
                            element_ref=ref,
                            money=("rounding", "step"),
                            number=number,
                            rounding=str(rounding),
                            step=str(step),
                        )
                    )
        return out


class RetentionTermsRule(_ReleaseRule):
    """V13: retention per the terms, released only after its event and never beyond what is held."""

    rule_id = "payment_release.retention_terms"
    name = "Retention follows the contract"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = (
        "Retention on a final invoice only with agreed warranty retention; no more paid back than held; a release "
        "only after its event; retention left on a completed contract is pointed out."
    )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        out: list[RuleResult] = []
        for c in _rows(payload, "contracts"):
            code = c.get("code") or ""
            for inv in _rows(c, "invoices"):
                if (
                    inv.get("kind") == "final"
                    and inv.get("retention_source") == "terms"
                    and _dec(inv.get("retention")) > 0
                    and not c.get("warranty_enabled")
                ):
                    out.append(
                        self._result(
                            context,
                            "final_retention_without_warranty",
                            element_ref=str(inv.get("id") or ""),
                            money=("amount",),
                            number=inv.get("number") or "",
                            amount=str(_dec(inv.get("retention"))),
                            contract=code,
                        )
                    )
            held = _dec(c.get("retention_held"))
            if held < -MONEY_TOLERANCE:
                out.append(
                    self._result(
                        context,
                        "posting_exceeds_held",
                        element_ref=str(c.get("id") or ""),
                        money=("amount",),
                        contract=code,
                        amount=str(-held),
                    )
                )
            months = int(c.get("warranty_period_months") or 0)
            for p in _rows(c, "postings"):
                event_on = _date(p.get("event_on"))
                posted_on = _date(p.get("posted_on"))
                ref = str(p.get("id") or "")
                due = event_on
                if event_on is not None and p.get("retention_kind") == "warranty" and months > 0:
                    due = _add_months(event_on, months)
                if due is None:
                    out.append(
                        self._result(
                            context,
                            "posting_without_event_date",
                            severity=Severity.WARNING,
                            element_ref=ref,
                            money=("amount",),
                            contract=code,
                            amount=str(_dec(p.get("amount"))),
                        )
                    )
                elif posted_on is not None and posted_on < due:
                    out.append(
                        self._result(
                            context,
                            "posting_before_event",
                            severity=Severity.WARNING,
                            element_ref=ref,
                            money=("amount",),
                            contract=code,
                            amount=str(_dec(p.get("amount"))),
                            posted=posted_on.isoformat(),
                            due=due.isoformat(),
                        )
                    )
            if str(c.get("status") or "") == "completed" and held > MONEY_TOLERANCE:
                out.append(
                    self._result(
                        context,
                        "retention_still_held",
                        severity=Severity.INFO,
                        element_ref=str(c.get("id") or ""),
                        money=("amount",),
                        contract=code,
                        amount=str(held),
                    )
                )
        return out


class EarlyPaymentDiscountRule(_ReleaseRule):
    """V14: a discount only where agreed, and only when the rest was paid by the discount date."""

    rule_id = "payment_release.early_payment_discount"
    name = "Early payment discount is earned"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = (
        "A confirmed release carries a discount only where the contract allows one; a discount kept back on a "
        "payment made after the discount date is pointed out."
    )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        out: list[RuleResult] = []
        for c in _rows(payload, "contracts"):
            for inv in _rows(c, "invoices"):
                ref = str(inv.get("id") or "")
                discount = _dec(inv.get("discount"))
                if discount <= 0:
                    continue
                if not c.get("discount_enabled"):
                    out.append(
                        self._result(
                            context,
                            "discount_not_agreed",
                            element_ref=ref,
                            money=("amount",),
                            number=inv.get("number") or "",
                            amount=str(discount),
                            contract=c.get("code") or "",
                        )
                    )
                    continue
                paid = _dec(inv.get("paid_cash"))
                payable = _dec(inv.get("payable"))
                release = _dec(inv.get("release"))
                last = _date(inv.get("last_payment_on"))
                until = _date(inv.get("discount_until"))
                kept_back = paid + MONEY_TOLERANCE >= payable and paid + MONEY_TOLERANCE < release
                if kept_back and last is not None and until is not None and last > until:
                    out.append(
                        self._result(
                            context,
                            "discount_after_deadline",
                            severity=Severity.WARNING,
                            element_ref=ref,
                            money=("amount",),
                            number=inv.get("number") or "",
                            amount=str(discount),
                            paid_on=last.isoformat(),
                            until=until.isoformat(),
                        )
                    )
        return out


class InvoicedWithinValueRule(_ReleaseRule):
    """V16: invoiced within what is measured, or within the contract where nothing is measured."""

    rule_id = "payment_release.invoiced_within_value"
    name = "Invoiced within the value of the work"
    severity = Severity.WARNING
    description = (
        "Net invoiced on a contract stays within its measured value (quantity times rate); without measurement, "
        "within the contract value including changes."
    )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        out: list[RuleResult] = []
        for c in _rows(payload, "contracts"):
            invoiced = _dec(c.get("invoiced_series"))
            if invoiced <= 0:
                continue
            if c.get("has_measurement"):
                measured = _dec(c.get("measured"))
                if invoiced > measured + MONEY_TOLERANCE:
                    out.append(
                        self._result(
                            context,
                            "invoiced_over_measured",
                            element_ref=str(c.get("id") or ""),
                            money=("invoiced", "measured", "difference"),
                            contract=c.get("code") or "",
                            invoiced=str(invoiced),
                            measured=str(measured),
                            difference=str(invoiced - measured),
                        )
                    )
                continue
            value = _dec(c.get("current_value"))
            if value > 0 and invoiced > value + MONEY_TOLERANCE:
                out.append(
                    self._result(
                        context,
                        "invoiced_over_contract",
                        element_ref=str(c.get("id") or ""),
                        money=("invoiced", "value", "difference"),
                        contract=c.get("code") or "",
                        invoiced=str(invoiced),
                        value=str(value),
                        difference=str(invoiced - value),
                    )
                )
        return out


class InvoiceVatRule(_ReleaseRule):
    """V17: VAT stated per line; a reverse charged invoice carries none."""

    rule_id = "payment_release.invoice_vat"
    name = "Invoice VAT is stated per line"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = (
        "Each line of an invoice with several lines and VAT states its rate; reverse charged lines carry rate "
        "zero and a reverse charged invoice no VAT amount."
    )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        out: list[RuleResult] = []
        for inv in _rows(payload, "invoices"):
            lines = _rows(inv, "lines")
            vat = _dec(inv.get("vat"))
            ref = str(inv.get("id") or "")
            number = inv.get("number") or ""
            reverse = [ln for ln in lines if str(ln.get("category") or "").upper() == REVERSE_CHARGE_CATEGORY]
            bad_reverse = [ln for ln in reverse if ln.get("rate") not in (None, "") and _dec(ln.get("rate")) != 0]
            if bad_reverse or (reverse and len(reverse) == len(lines) and vat != 0):
                out.append(
                    self._result(
                        context,
                        "reverse_charge_with_vat",
                        severity=Severity.ERROR,
                        element_ref=ref,
                        money=("vat",),
                        number=number,
                        vat=str(vat),
                    )
                )
                continue
            if vat != 0 and len(lines) > 1:
                missing = sum(1 for ln in lines if ln.get("rate") in (None, ""))
                if missing:
                    out.append(
                        self._result(
                            context,
                            "line_without_vat_rate",
                            element_ref=ref,
                            number=number,
                            count=missing,
                        )
                    )
        return out


def _number_key(raw: object) -> str:
    return "".join(ch for ch in str(raw or "").casefold() if ch.isalnum())


class DuplicateInvoiceRule(_ReleaseRule):
    """V18: one invoice number per contractor; same contractor, amount and date pointed out."""

    rule_id = "payment_release.duplicate_invoice"
    name = "No invoice entered twice"
    severity = Severity.ERROR
    description = (
        "A contractor's invoice number appears once in the project; two invoices from one contractor with the "
        "same amount on the same day are pointed out as a possible duplicate."
    )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        out: list[RuleResult] = []
        by_number: dict[tuple[str, str], list[dict[str, Any]]] = {}
        by_amount: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for inv in _rows(payload, "invoices"):
            party = str(inv.get("contact") or "") or f"contract:{inv.get('contract') or ''}"
            if party == "contract:":
                continue
            key = _number_key(inv.get("number"))
            if key:
                by_number.setdefault((party, key), []).append(inv)
            gross = _dec(inv.get("gross"))
            on = str(inv.get("on") or "")
            if gross != 0 and on:
                by_amount.setdefault((party, str(gross), on), []).append(inv)
        flagged: set[str] = set()
        for group in by_number.values():
            if len(group) < 2:
                continue
            for inv in group[1:]:
                flagged.add(str(inv.get("id")))
                out.append(
                    self._result(
                        context,
                        "duplicate_number",
                        element_ref=str(inv.get("id") or ""),
                        number=inv.get("number") or "",
                        count=len(group),
                    )
                )
        for group in by_amount.values():
            if len(group) < 2 or len({_number_key(i.get("number")) for i in group}) < 2:
                continue
            first = group[0]
            for inv in group[1:]:
                if str(inv.get("id")) in flagged:
                    continue
                out.append(
                    self._result(
                        context,
                        "possible_duplicate",
                        severity=Severity.WARNING,
                        element_ref=str(inv.get("id") or ""),
                        money=("amount",),
                        number=inv.get("number") or "",
                        other=first.get("number") or "",
                        amount=str(_dec(inv.get("gross"))),
                        on=str(inv.get("on") or ""),
                    )
                )
        return out


class ReleaseCertificatesRule(_ReleaseRule):
    """V19: the payee holds the certificates the law asks for before a payment is released.

    Reads ``contract["release_certificates"]`` (built by the service from the
    project's pack and the counterparty's subcontractor record)::

        {"enforcement": "pack" | "block" | "warn" | "off",
         "requirements": [{"code", "cert_type", "release_effect", "applies_to_kinds",
                           "statute_reference", "needs_expert_review"}],
         "certificates": [{"cert_type", "issue_date", "valid_until", "status", "revoked"}]}

    and ``payload["as_of"]``, the release date. Only invoices not yet
    released are checked: a confirmed release is history, and a certificate
    that lapsed afterwards says nothing about the day it was paid.
    """

    rule_id = "payment_release.release_certificates"
    name = "Payee holds the certificates required before payment"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = (
        "Where the pack makes a certificate (for example a social insurance clearance) a condition of paying, "
        "each interim or final invoice is released only while the payee holds one valid on the release date."
    )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        from app.modules.payment_release.release_certificates import (  # noqa: PLC0415
            effective_severity,
            normalise_enforcement,
        )

        as_of = _date(payload.get("as_of"))
        if as_of is None:
            return []
        locale = _locale(context)
        out: list[RuleResult] = []
        for c in _rows(payload, "contracts"):
            gate = c.get("release_certificates")
            if not isinstance(gate, dict):
                continue
            enforcement = normalise_enforcement(gate.get("enforcement"))
            held = [
                cert
                for cert in _rows(gate, "certificates")
                if not cert.get("revoked")
                and str(cert.get("status") or "") != "revoked"
                and (_date(cert.get("issue_date")) or as_of) <= as_of
                and (_date(cert.get("valid_until")) is None or _date(cert.get("valid_until")) >= as_of)  # type: ignore[operator]
            ]
            for requirement in _rows(gate, "requirements"):
                level = effective_severity(requirement, enforcement)
                if level is None:
                    continue
                cert_type = str(requirement.get("cert_type") or "")
                if any(cert.get("cert_type") == cert_type for cert in held):
                    continue
                type_key = f"payment_release_certificate_types.{cert_type}"
                label = translate(type_key, locale)
                kinds = requirement.get("applies_to_kinds") or []
                for inv in _rows(c, "invoices"):
                    if inv.get("released") or str(inv.get("kind") or "") not in kinds:
                        continue
                    out.append(
                        self._result(
                            context,
                            "certificate_missing",
                            severity=Severity.ERROR if level == "error" else Severity.WARNING,
                            element_ref=str(inv.get("id") or ""),
                            number=inv.get("number") or "",
                            contract=c.get("code") or "",
                            certificate=cert_type if label == type_key else label,
                            on=as_of.isoformat(),
                            reference=str(requirement.get("statute_reference") or ""),
                        )
                    )
        return out


PAYMENT_RELEASE_RULES: tuple[type[_ReleaseRule], ...] = (
    InvoiceSequenceRule,
    ReleaseRecomputedRule,
    RetentionTermsRule,
    EarlyPaymentDiscountRule,
    InvoicedWithinValueRule,
    InvoiceVatRule,
    DuplicateInvoiceRule,
    ReleaseCertificatesRule,
)

#: The spec's numbering of each rule (V15 is ``cost_chain.invoice_has_contract``).
RULE_NUMBERS: dict[str, str] = {
    InvoiceSequenceRule.rule_id: "V11",
    ReleaseRecomputedRule.rule_id: "V12",
    RetentionTermsRule.rule_id: "V13",
    EarlyPaymentDiscountRule.rule_id: "V14",
    InvoicedWithinValueRule.rule_id: "V16",
    InvoiceVatRule.rule_id: "V17",
    DuplicateInvoiceRule.rule_id: "V18",
    ReleaseCertificatesRule.rule_id: "V19",
}


def register_payment_release_rules() -> None:
    """Register V11 to V14 and V16 to V19 into the ``payment_release`` rule set.

    The statutory rules V20 to V23 join the same set; they live in
    ``statutory_rules`` because they read country data rather than the terms.
    """
    from app.modules.payment_release.statutory_rules import STATUTORY_RULES

    for rule_cls in (*PAYMENT_RELEASE_RULES, *STATUTORY_RULES):
        rule_registry.register(rule_cls(), [RULE_SET])
    logger.debug("Registered payment release validation rules")
