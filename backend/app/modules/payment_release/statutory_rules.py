# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Statutory rules V20 to V23, rule set ``payment_release``: what a country's law says about paying an invoice.

The rules are country-neutral. Each reads the project's country from the
payload and asks a data module what that country's law says; a country
without a row is silent. Poland is the first country with rows.

* V20 ``split_payment``: an invoice that falls under split payment carries the
  annotation the law requires, and every recorded payment of it was made by
  split payment. :mod:`app.core.vat_construction` decides which invoices fall
  under it. An invoice that bills a construction subcontract is taken to list
  construction works unless its metadata says otherwise (``annex_15`` false, or
  goods codes outside the annex); a loose invoice without codes is asked about,
  never convicted. A payment made another way is an error only where the
  invoice declares ``annex_15``; where the annex status is inferred it is a
  warning, because the annex lists named positions an inference cannot prove.
* V21 ``reduced_vat_housing``: an invoice charged at the reduced housing rate
  on the whole price, on a project whose dwelling is above the area limit, of
  a kind that does not qualify, or not recorded at all. The project records
  its dwelling in ``metadata.vat_housing`` (``object_kind``, ``usable_area_m2``).
* V22 ``domestic_reverse_charge``: a reverse charged line on an invoice dated
  after the country ended domestic reverse charge for construction. A warning,
  because a supplier established abroad still reverse charges, and the payload
  does not say where the supplier is established.
* V23 ``statutory_payment_term``: the interim or final payment term agreed with
  a subcontractor is longer than the statutory ceiling between businesses
  (:mod:`app.core.late_payment`).

The invoice metadata keys read: ``split_payment`` (the annotation is on the
invoice), ``annex_15`` (it lists annex goods or services), ``pkwiu_codes``
(their codes). A payment's ``metadata.method`` says how it was paid.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from app.core import late_payment, vat_construction
from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext
from app.modules.payment_release.validators import _date, _dec, _ReleaseRule, _rows

logger = logging.getLogger(__name__)

#: The debtor kind a subcontract payment term is held to: the project's own
#: company pays its subcontractors, so the statute's business-to-business
#: ceiling applies whoever the client is.
SUBCONTRACT_DEBTOR_KIND = "commercial"


def _country(payload: dict[str, Any]) -> str:
    return str(payload.get("country") or "").strip().upper()


def _facts(inv: dict[str, Any]) -> dict[str, Any]:
    facts = inv.get("vat_facts")
    return facts if isinstance(facts, dict) else {}


class _StatutoryRule(_ReleaseRule):
    """A rule that speaks only for a country the data holds."""

    category = RuleCategory.COMPLIANCE


class SplitPaymentRule(_StatutoryRule):
    """V20: split payment annotated on the invoice and used for its payments."""

    rule_id = "payment_release.split_payment"
    name = "Split payment where the law requires it"
    severity = Severity.WARNING
    description = (
        "An invoice listing goods or services of the split payment annex above the threshold carries the "
        "annotation, and every payment of it is made by split payment."
    )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        country = _country(payload)
        if vat_construction.split_payment_rules(country) is None:
            return []
        currency = str(payload.get("currency") or "")
        out: list[RuleResult] = []
        for inv in _rows(payload, "invoices"):
            on = _date(inv.get("on"))
            if on is None:
                continue
            facts = _facts(inv)
            annex: bool | None
            # Declared on the invoice, or inferred. An inferred status can warn
            # and never block: the annex lists named positions, which neither a
            # code's section nor the contract it bills can prove.
            declared = isinstance(facts.get("annex_15"), bool)
            if declared:
                annex = facts["annex_15"]
            else:
                codes = facts.get("pkwiu_codes")
                annex = vat_construction.annex_15_from_codes(country, list(codes) if isinstance(codes, list) else [])
                if annex is None and inv.get("contract"):
                    # A subcontract on a construction project bills construction works.
                    annex = True
            gross = _dec(inv.get("gross"))
            decision = vat_construction.split_payment_decision(country, on, gross, currency, annex_15=annex)
            if decision is None:
                continue
            ref = str(inv.get("id") or "")
            number = inv.get("number") or ""
            if decision.required is None:
                if decision.reason == "annex_15_unknown":
                    out.append(
                        self._result(
                            context,
                            "split_payment_annex_unknown",
                            severity=Severity.INFO,
                            element_ref=ref,
                            money=("threshold",),
                            number=number,
                            threshold=str(decision.threshold),
                        )
                    )
                continue
            if not decision.required:
                continue
            if facts.get("split_payment") is not True:
                out.append(
                    self._result(
                        context,
                        "split_payment_annotation_missing",
                        element_ref=ref,
                        money=("threshold",),
                        number=number,
                        annotation=decision.annotation,
                        threshold=str(decision.threshold),
                    )
                )
            methods = [str(m or "").strip() for m in inv.get("payment_methods") or []]
            if any(m and m != decision.payment_method for m in methods):
                sanction = vat_construction.split_payment_sanction(country, _dec(inv.get("vat")))
                out.append(
                    self._result(
                        context,
                        "split_payment_not_used",
                        severity=Severity.ERROR if declared else Severity.WARNING,
                        element_ref=ref,
                        money=("sanction",),
                        number=number,
                        sanction=str(sanction),
                    )
                )
        return out


class ReducedHousingVatRule(_StatutoryRule):
    """V21: the reduced housing rate only within the area limit and only on dwellings."""

    rule_id = "payment_release.reduced_vat_housing"
    name = "Reduced housing VAT within its limits"
    severity = Severity.WARNING
    description = (
        "An invoice charged entirely at the reduced housing rate is on a dwelling of a qualifying kind "
        "within the usable area limit; above it the standard rate is due on the excess share."
    )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        country = _country(payload)
        if not vat_construction.object_kinds(country):
            return []
        housing = payload.get("housing") if isinstance(payload.get("housing"), dict) else {}
        kind = str(housing.get("object_kind") or "") or None
        raw_area = housing.get("usable_area_m2")
        area = _dec(raw_area) if raw_area not in (None, "") else None
        out: list[RuleResult] = []
        for inv in _rows(payload, "invoices"):
            on = _date(inv.get("on"))
            if on is None:
                continue
            rates = {_dec(ln.get("rate")) for ln in _rows(inv, "lines") if ln.get("rate") not in (None, "")}
            rates.discard(Decimal(0))
            if len(rates) != 1:
                # No VAT line, or already split between rates.
                continue
            (rate,) = rates
            for finding in vat_construction.housing_rate_findings(country, kind, area, rate, on):
                out.append(
                    self._result(
                        context,
                        finding.key,
                        element_ref=str(inv.get("id") or ""),
                        number=inv.get("number") or "",
                        **finding.params,
                    )
                )
        return out


class DomesticReverseChargeRule(_StatutoryRule):
    """V22: no domestic reverse charge on construction after the country ended it."""

    rule_id = "payment_release.domestic_reverse_charge"
    name = "Reverse charge only where the law still allows it"
    severity = Severity.WARNING
    description = (
        "A reverse charged line on an invoice dated after domestic reverse charge on construction services "
        "ended is valid only from a supplier established abroad."
    )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        country = _country(payload)
        out: list[RuleResult] = []
        for inv in _rows(payload, "invoices"):
            on = _date(inv.get("on"))
            if on is None or vat_construction.domestic_reverse_charge_allowed(country, on) is not False:
                continue
            reverse = [ln for ln in _rows(inv, "lines") if str(ln.get("category") or "").upper() == "AE"]
            if reverse:
                out.append(
                    self._result(
                        context,
                        "domestic_reverse_charge_ended",
                        element_ref=str(inv.get("id") or ""),
                        number=inv.get("number") or "",
                        count=len(reverse),
                    )
                )
        return out


class StatutoryPaymentTermRule(_StatutoryRule):
    """V23: a subcontract payment term within the statutory ceiling between businesses."""

    rule_id = "payment_release.statutory_payment_term"
    name = "Payment term within the statutory ceiling"
    severity = Severity.WARNING
    description = (
        "The interim and final payment terms agreed with a subcontractor are no longer than the longest "
        "term the country's late payment statute allows between businesses."
    )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        country = _country(payload)
        cap = late_payment.payment_term_cap_days(country, SUBCONTRACT_DEBTOR_KIND)
        if cap is None:
            return []
        out: list[RuleResult] = []
        for c in _rows(payload, "contracts"):
            longest = max(
                (int(d) for d in (c.get("interim_due_days"), c.get("final_due_days")) if d not in (None, "")),
                default=None,
            )
            if longest is not None and longest > cap:
                out.append(
                    self._result(
                        context,
                        "payment_term_over_cap",
                        element_ref=str(c.get("id") or ""),
                        contract=c.get("code") or "",
                        days=longest,
                        cap=cap,
                    )
                )
        return out


STATUTORY_RULES: tuple[type[_StatutoryRule], ...] = (
    SplitPaymentRule,
    ReducedHousingVatRule,
    DomesticReverseChargeRule,
    StatutoryPaymentTermRule,
)

STATUTORY_RULE_NUMBERS: dict[str, str] = {
    SplitPaymentRule.rule_id: "V20",
    ReducedHousingVatRule.rule_id: "V21",
    DomesticReverseChargeRule.rule_id: "V22",
    StatutoryPaymentTermRule.rule_id: "V23",
}
