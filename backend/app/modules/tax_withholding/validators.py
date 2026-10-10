# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tax withholding validation rules.

Every rule here guards money that has already left the business by the time
anybody notices. A deduction taken on the wrong base is remitted to a tax
authority, and the subcontractor recovers it at the end of their tax year if
they notice at all; an invoice that carries reverse-charge wording *and* a VAT
line has charged VAT that the buyer will also account for.

Rules, all registered under the ``tax_withholding`` rule set:

* ``tax_withholding.taxable_base``          - ERROR.   The base must be the
                                               gross less what the scheme takes
                                               out of it.
* ``tax_withholding.withheld_within_base``  - ERROR.   You cannot withhold more
                                               than the base you computed.
* ``tax_withholding.verification_required`` - ERROR.   A reduced or zero band
                                               needs a verification that holds.
* ``tax_withholding.reverse_charge_invoice``- ERROR.   The wording must be on
                                               the invoice and the VAT must not.
* ``tax_withholding.verification_expiring`` - WARNING. A verification lapsing
                                               inside the period being paid.
* ``tax_withholding.rate_matches_band``     - WARNING. The rate applied should
                                               be the band's rate.

And for the statutory tax lines of one payment document:

* ``tax_withholding.statutory_vat_identity``          - ERROR.   Computed VAT is
                                                         withheld plus payable.
* ``tax_withholding.statutory_override_reason``       - ERROR.   An amount entered
                                                         by hand says why.
* ``tax_withholding.statutory_rate_not_effective``    - ERROR.   The stored rate
                                                         row is in force on the
                                                         document date.
* ``tax_withholding.statutory_rate_unconfirmed``      - WARNING, ERROR at an
                                                         unacknowledged
                                                         confirmation.
* ``tax_withholding.statutory_line_held``             - WARNING, ERROR at
                                                         confirmation.
* ``tax_withholding.statutory_threshold_unevaluated`` - WARNING. A limit that one
                                                         document cannot judge.

The two rules whose severity depends on the action are a warning while the
figures are a draft, because a draft is allowed to be unfinished, and an error
at the moment a person confirms. The service refuses that confirmation on its
own as well: ``evaluate_record`` below degrades to "no findings" when a rule
breaks, and a signature must not depend on a rule having run.

**The payload.** Rules read a plain dict, built by
:mod:`app.modules.tax_withholding.service`, so a figure arriving from an import
can be checked before anything is stored. ``record_type`` says which shape it
is and every rule ignores the other one::

    {"record_type": "deduction",
     "gross_amount", "qualifying_materials", "vat_amount",
     "taxable_base", "tax_withheld", "rate_pct", "band_code",
     "currency_code", "period_start", "period_end",
     "regime": {"scheme_code", "materials_excluded", "vat_excluded",
                "default_band_code", "bands": [...]},
     "party_status": {"band_code", "verification_reference",
                      "valid_from", "valid_to", "status"}}

    {"record_type": "reverse_charge",
     "buyer_accounts_for_vat", "invoice_wording", "legal_reference",
     "vat_amount", "net_amount", "currency_code", "invoice_reference"}

    {"record_type": "statutory_taxes",
     "action": "save" | "confirm", "acknowledged_unconfirmed_rates",
     "currency_code", "document_date", "source_reference",
     "lines": [{"kind", "calc_status", "tax_amount", "base_amount", "code",
                "review_status", "reason_key", "reason_params",
                "rate_effective_from", "rate_effective_to",
                "overridden", "override_amount", "override_reason"}]}

**Which date a verification is judged on.** ``period_start``, not
``period_end``. A payment is made during the period, so a verification that was
valid when the period opened covers it; one that lapses before the period
closes is a warning about the *next* payment, not an error about this one. That
split is what keeps ``verification_required`` and ``verification_expiring``
from both firing on the same certificate and saying different things about it.

**No tolerance on the base.** The base is a subtraction of figures that are
already at two decimal places, so nothing rounds and a cent of difference is a
cent of difference. A tolerance here would hide the exact class of error the
rule exists for: materials left in a base they should have come out of.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
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

# The amount format the built-in rules already use: the decimals the currency
# genuinely has, thousands separators, and the code. Taken from the core rules
# rather than rewritten here, so two findings on one screen cannot disagree
# about what an amount looks like. Importing it registers nothing.
from app.core.validation.rules import _fmt_money
from app.modules.tax_withholding.service import (
    THRESHOLD_UNEVALUATED_REASONS,
    ZERO,
    compute_taxable_base,
    quantise,
    to_decimal,
)

logger = logging.getLogger(__name__)

TAX_WITHHOLDING_RULE_SET = "tax_withholding"

RECORD_DEDUCTION = "deduction"
RECORD_REVERSE_CHARGE = "reverse_charge"
RECORD_STATUTORY = "statutory_taxes"


def _record(context: ValidationContext) -> dict[str, Any]:
    data = context.data
    return data if isinstance(data, dict) else {}


def _is(context: ValidationContext, kind: str) -> bool:
    return str(_record(context).get("record_type") or "") == kind


def _dec(value: Any) -> Decimal:
    return to_decimal(value)


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _currency(record: dict[str, Any]) -> str:
    """The currency this record states, never a default.

    Blank stays blank: the renderer then groups the digits and writes no code.
    A guessed code reads as authoritative and is worse than none, because a
    reader who trusts it reconciles the wrong ledger.
    """
    return _text(record.get("currency_code"))


def _as_date(value: Any) -> date | None:
    """Read a date from a ``date``, a ``datetime`` or an ISO string."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _regime(context: ValidationContext) -> dict[str, Any]:
    regime = _record(context).get("regime")
    return regime if isinstance(regime, dict) else {}


def _party_status(context: ValidationContext) -> dict[str, Any] | None:
    status = _record(context).get("party_status")
    return status if isinstance(status, dict) else None


def _bands(context: ValidationContext) -> list[dict[str, Any]]:
    raw = _regime(context).get("bands")
    if not isinstance(raw, list):
        return []
    return [band for band in raw if isinstance(band, dict)]


def _band(context: ValidationContext, code: str) -> dict[str, Any] | None:
    if not code:
        return None
    for band in _bands(context):
        if _text(band.get("code")) == code:
            return band
    return None


def _result(
    rule: ValidationRule,
    passed: bool,
    message: str,
    *,
    element_ref: str | None = None,
    suggestion: str | None = None,
    details: dict[str, Any] | None = None,
    severity: Severity | None = None,
) -> RuleResult:
    """Build a RuleResult carrying the rule's own id / name / severity / category.

    ``severity`` replaces the rule's own for the two statutory rules that are
    a warning on a draft and an error at confirmation.
    """
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=severity or rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=element_ref,
        suggestion=suggestion,
        details=details or {},
    )


class TaxableBaseIsCorrect(ValidationRule):
    rule_id = "tax_withholding.taxable_base"
    name = "Taxable Base Excludes What The Scheme Excludes"
    standard = "tax_withholding"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = (
        "The base a deduction is taken on must be the gross less the materials and the VAT "
        "that the scheme takes out of it."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is(context, RECORD_DEDUCTION):
            return []
        record = _record(context)
        regime = _regime(context)
        gross = _dec(record.get("gross_amount"))
        materials = _dec(record.get("qualifying_materials"))
        vat = _dec(record.get("vat_amount"))
        materials_excluded = bool(regime.get("materials_excluded", True))
        vat_excluded = bool(regime.get("vat_excluded", True))
        expected = compute_taxable_base(
            gross,
            materials,
            vat,
            materials_excluded=materials_excluded,
            vat_excluded=vat_excluded,
        )
        actual = quantise(_dec(record.get("taxable_base")))
        currency = _currency(record)
        details = {
            "gross_amount": str(gross),
            "qualifying_materials": str(materials),
            "vat_amount": str(vat),
            "expected_base": str(expected),
            "recorded_base": str(actual),
            "materials_excluded": materials_excluded,
            "vat_excluded": vat_excluded,
            "currency_code": _text(record.get("currency_code")),
        }
        if actual == expected:
            return [_result(self, True, "OK", details=details)]

        # The specific failure this rule exists for: the materials are still in
        # the base. Say what it costs on this payment rather than only that the
        # arithmetic disagrees - it is the same amount again on every payment.
        if materials_excluded and materials > ZERO and actual == quantise(expected + materials):
            over = quantise(materials * _dec(record.get("rate_pct")) / Decimal("100"))
            return [
                _result(
                    self,
                    False,
                    (
                        f"The base still includes {_fmt_money(materials, currency)} of materials. This scheme "
                        f"deducts on labour, so the base should be {_fmt_money(expected, currency)} and not "
                        f"{_fmt_money(actual, currency)}, and this payment over-withholds by "
                        f"{_fmt_money(over, currency)}."
                    ),
                    suggestion=(
                        "Record the materials the party supplied in 'qualifying materials' and take "
                        "them out of the base before applying the rate."
                    ),
                    details={**details, "over_withheld": str(over)},
                )
            ]
        return [
            _result(
                self,
                False,
                (
                    f"The base is recorded as {_fmt_money(actual, currency)} but the scheme computes "
                    f"{_fmt_money(expected, currency)} from a gross of {_fmt_money(gross, currency)}. "
                    "A deduction is only defensible if the base it was taken on is."
                ),
                suggestion="Recompute the base from the gross, the qualifying materials and the VAT.",
                details=details,
            )
        ]


class WithheldWithinBase(ValidationRule):
    rule_id = "tax_withholding.withheld_within_base"
    name = "Amount Withheld Does Not Exceed The Base"
    standard = "tax_withholding"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "The tax withheld must be a non-negative part of the base it was computed on."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is(context, RECORD_DEDUCTION):
            return []
        record = _record(context)
        base = _dec(record.get("taxable_base"))
        withheld = _dec(record.get("tax_withheld"))
        currency = _currency(record)
        details = {"taxable_base": str(base), "tax_withheld": str(withheld)}
        if withheld < ZERO:
            return [
                _result(
                    self,
                    False,
                    (
                        f"The amount withheld is negative ({_fmt_money(withheld, currency)}). "
                        "A withholding is money kept back, never paid out."
                    ),
                    suggestion="Record a refund of an over-withholding as its own corrective entry, not as a negative deduction.",
                    details=details,
                )
            ]
        if withheld > base:
            return [
                _result(
                    self,
                    False,
                    (
                        f"{_fmt_money(withheld, currency)} is withheld from a base of "
                        f"{_fmt_money(base, currency)}. Withholding more than the base "
                        "leaves the party paid less than the contract allows and the return unfilable."
                    ),
                    suggestion="Check the rate and the base; at 100 percent the two figures are equal, never more.",
                    details=details,
                )
            ]
        return [_result(self, True, "OK", details=details)]


class VerificationSupportsBand(ValidationRule):
    rule_id = "tax_withholding.verification_required"
    name = "Reduced Band Is Backed By A Live Verification"
    standard = "tax_withholding"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = (
        "A band that only a verified party may use requires a verification that is valid when "
        "the payment is made; otherwise the higher band applies."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is(context, RECORD_DEDUCTION):
            return []
        record = _record(context)
        band_code = _text(record.get("band_code"))
        band = _band(context, band_code)
        if band is None or not band.get("requires_verification"):
            # An unverified band, or a scheme this deployment has not described
            # in enough detail to judge. Either way there is nothing to check.
            return [_result(self, True, "OK", details={"band_code": band_code})]

        default_band = _text(_regime(context).get("default_band_code"))
        status = _party_status(context)
        on_date = _as_date(record.get("period_start")) or date.today()
        details = {
            "band_code": band_code,
            "default_band_code": default_band,
            "judged_on": on_date.isoformat(),
        }

        if status is None:
            return [
                _result(
                    self,
                    False,
                    (
                        f"Band '{band_code}' is only available to a verified party and no verification "
                        f"is recorded, so the higher band '{default_band}' applies to this payment."
                    ),
                    suggestion="Verify the party with the authority and record the reference it returns.",
                    details=details,
                )
            ]

        reference = _text(status.get("verification_reference"))
        valid_to = _as_date(status.get("valid_to"))
        valid_from = _as_date(status.get("valid_from"))
        state = _text(status.get("status"))
        details |= {
            "verification_reference": reference,
            "valid_from": valid_from.isoformat() if valid_from else "",
            "valid_to": valid_to.isoformat() if valid_to else "",
            "party_status": state,
        }

        if not reference:
            return [
                _result(
                    self,
                    False,
                    (
                        f"Band '{band_code}' is recorded with no verification reference, so nothing "
                        "evidences the reduced rate if the deduction is questioned."
                    ),
                    suggestion="Record the reference the authority returned, and the certificate behind it.",
                    details=details,
                )
            ]
        if state in {"revoked", "expired"}:
            return [
                _result(
                    self,
                    False,
                    (
                        f"The verification behind band '{band_code}' is marked {state}, so the higher "
                        f"band '{default_band}' applies to this payment."
                    ),
                    suggestion=f"Deduct at '{default_band}' until a new verification is obtained.",
                    details=details,
                )
            ]
        if valid_from is not None and valid_from > on_date:
            return [
                _result(
                    self,
                    False,
                    (
                        f"The verification behind band '{band_code}' does not start until "
                        f"{valid_from.isoformat()}, after this payment on {on_date.isoformat()}."
                    ),
                    suggestion="Deduct at the higher band for payments made before the verification starts.",
                    details=details,
                )
            ]
        if valid_to is not None and valid_to < on_date:
            return [
                _result(
                    self,
                    False,
                    (
                        f"The verification behind band '{band_code}' expired on {valid_to.isoformat()}, "
                        f"before this payment on {on_date.isoformat()}. An expired verification moves the "
                        f"party to '{default_band}' whether or not anyone noticed."
                    ),
                    suggestion="Renew the verification, or deduct at the higher band until it is renewed.",
                    details=details,
                )
            ]
        return [_result(self, True, "OK", details=details)]


class VerificationExpiringInPeriod(ValidationRule):
    rule_id = "tax_withholding.verification_expiring"
    name = "Verification Lapses Inside The Period Being Paid"
    standard = "tax_withholding"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "A verification that runs out inside the period silently moves the party to the higher band."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is(context, RECORD_DEDUCTION):
            return []
        status = _party_status(context)
        if status is None:
            return []
        valid_to = _as_date(status.get("valid_to"))
        if valid_to is None:
            return [_result(self, True, "OK")]
        record = _record(context)
        start = _as_date(record.get("period_start"))
        end = _as_date(record.get("period_end"))
        if start is None or end is None:
            return [_result(self, True, "OK")]
        details = {
            "valid_to": valid_to.isoformat(),
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "band_code": _text(record.get("band_code")),
        }
        if not (start <= valid_to <= end):
            return [_result(self, True, "OK", details=details)]
        return [
            _result(
                self,
                False,
                (
                    f"The verification runs out on {valid_to.isoformat()}, inside the period being paid "
                    f"({start.isoformat()} to {end.isoformat()}). Any payment after that date falls to the "
                    "higher band, and nothing announces it."
                ),
                suggestion="Renew before the period closes, or split the payment either side of the expiry date.",
                details=details,
            )
        ]


class RateMatchesBand(ValidationRule):
    rule_id = "tax_withholding.rate_matches_band"
    name = "Rate Applied Is The Band's Rate"
    standard = "tax_withholding"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "The rate on a deduction should be the rate the scheme publishes for the band it names."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is(context, RECORD_DEDUCTION):
            return []
        record = _record(context)
        band_code = _text(record.get("band_code"))
        band = _band(context, band_code)
        if band is None:
            return []
        published = _dec(band.get("rate_pct"))
        applied = _dec(record.get("rate_pct"))
        details = {"band_code": band_code, "published_rate_pct": str(published), "applied_rate_pct": str(applied)}
        if published == applied:
            return [_result(self, True, "OK", details=details)]
        return [
            _result(
                self,
                False,
                (
                    f"This deduction applies {applied} percent while the scheme publishes {published} "
                    f"percent for band '{band_code}'. A rate that has genuinely changed belongs on the "
                    "scheme, where the next payment will pick it up too."
                ),
                suggestion="Update the band's rate on the scheme, or correct the rate on this deduction.",
                details=details,
            )
        ]


class ReverseChargeInvoiceIsWellFormed(ValidationRule):
    rule_id = "tax_withholding.reverse_charge_invoice"
    name = "Reverse Charge Invoice Carries The Wording And No VAT"
    standard = "tax_withholding"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = (
        "On a reverse-charge supply the invoice must carry the statutory wording and must not carry a VAT amount."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is(context, RECORD_REVERSE_CHARGE):
            return []
        record = _record(context)
        buyer_accounts = bool(record.get("buyer_accounts_for_vat"))
        wording = _text(record.get("invoice_wording"))
        vat = _dec(record.get("vat_amount"))
        reference = _text(record.get("invoice_reference"))
        currency = _currency(record)
        details = {
            "buyer_accounts_for_vat": buyer_accounts,
            "has_wording": bool(wording),
            "vat_amount": str(vat),
            "legal_reference": _text(record.get("legal_reference")),
            "invoice_reference": reference,
        }

        if not buyer_accounts:
            # The mirror-image error: an invoice that charges VAT while telling
            # the buyer to account for it. Whoever reads it will get it wrong,
            # and one of the two will pay the VAT twice.
            if wording:
                return [
                    _result(
                        self,
                        False,
                        (
                            f"Invoice {reference} carries reverse-charge wording, but this determination "
                            "says the seller accounts for the VAT. The document contradicts the decision "
                            "behind it."
                        ),
                        suggestion="Either set the buyer to account for the VAT, or remove the wording from the invoice.",
                        details=details,
                        element_ref=reference or None,
                    )
                ]
            return [_result(self, True, "OK", details=details)]

        failures: list[RuleResult] = []
        if not wording:
            failures.append(
                _result(
                    self,
                    False,
                    (
                        f"Invoice {reference} is reverse charged but carries no statutory wording. Without "
                        "it the buyer has nothing telling them the VAT is theirs to account for."
                    ),
                    suggestion="Copy the wording for this country from the shipped reverse-charge rules onto the invoice.",
                    details=details,
                    element_ref=reference or None,
                )
            )
        if vat != ZERO:
            failures.append(
                _result(
                    self,
                    False,
                    (
                        f"Invoice {reference} is reverse charged and still shows {_fmt_money(vat, currency)} "
                        "of VAT. The buyer accounts for that VAT themselves, so charging it here collects "
                        "it twice."
                    ),
                    suggestion="Show the net amount only and leave the VAT line at zero on a reverse-charge invoice.",
                    details=details,
                    element_ref=reference or None,
                )
            )
        if failures:
            return failures
        return [_result(self, True, "OK", details=details)]


# ── Statutory tax lines ──────────────────────────────────────────────────────
#
# These rules read the five figures of one payment document. They never fill a
# gap: an amount that is missing is reported as missing, and a comparison that
# needs a held figure is skipped instead of being run against zero.


def _lines(context: ValidationContext) -> list[dict[str, Any]]:
    raw = _record(context).get("lines")
    if not isinstance(raw, list):
        return []
    return [line for line in raw if isinstance(line, dict)]


def _line(context: ValidationContext, kind: str) -> dict[str, Any] | None:
    for line in _lines(context):
        if _text(line.get("kind")) == kind:
            return line
    return None


def _amount(value: Any) -> Decimal | None:
    """Read an amount, keeping "not there" apart from zero.

    ``_dec`` above answers zero for anything it cannot read, which is right
    for a scheme deduction and wrong here: a held figure has no amount, and
    comparing it as zero would report an arithmetic error that is not one, or
    hide one that is.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def _confirming(context: ValidationContext) -> bool:
    return _text(_record(context).get("action")) == "confirm"


class StatutoryRateIsConfirmed(ValidationRule):
    rule_id = "tax_withholding.statutory_rate_unconfirmed"
    name = "Rate Row Has Been Confirmed Against Its Source"
    standard = "tax_withholding"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = (
        "A figure computed from a rate that nobody has confirmed against the primary source may be "
        "confirmed only by a person who states that they have checked it."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is(context, RECORD_STATUTORY):
            return []
        record = _record(context)
        acknowledged = bool(record.get("acknowledged_unconfirmed_rates"))
        blocking = _confirming(context) and not acknowledged
        failures: list[RuleResult] = []
        seen: set[str] = set()
        for line in _lines(context):
            code = _text(line.get("code"))
            if _text(line.get("review_status")) != "unconfirmed" or code in seen:
                continue
            seen.add(code)
            details = {
                "kind": _text(line.get("kind")),
                "code": code,
                "legal_reference": _text(line.get("legal_reference")),
                "source_url": _text(line.get("source_url")),
                "acknowledged": acknowledged,
            }
            failures.append(
                _result(
                    self,
                    False,
                    (
                        f"The rate for category '{code}' has not been confirmed against its primary source. "
                        "The figure is computed from it all the same."
                    ),
                    severity=Severity.ERROR if blocking else Severity.WARNING,
                    element_ref=_text(line.get("kind")) or None,
                    suggestion=(
                        "Check the rate against the cited source. Confirm the figures only with the "
                        "acknowledgement that you have done so."
                    ),
                    details=details,
                )
            )
        return failures or [_result(self, True, "OK")]


class StatutoryLineIsNotHeld(ValidationRule):
    rule_id = "tax_withholding.statutory_line_held"
    name = "No Figure Is Held At Confirmation"
    standard = "tax_withholding"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A figure that cannot be known yet has no amount, and a document with one cannot be confirmed."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is(context, RECORD_STATUTORY):
            return []
        blocking = _confirming(context)
        failures: list[RuleResult] = []
        for line in _lines(context):
            if _text(line.get("calc_status")) != "held":
                continue
            kind = _text(line.get("kind"))
            reason_key = _text(line.get("reason_key"))
            failures.append(
                _result(
                    self,
                    False,
                    (
                        f"The figure '{kind}' is held ({reason_key or 'no reason recorded'}). It has no amount, "
                        "and it is not zero."
                    ),
                    severity=Severity.ERROR if blocking else Severity.WARNING,
                    element_ref=kind or None,
                    suggestion="Supply what the figure is waiting for, or mark the tax as not applicable with a reason.",
                    details={"kind": kind, "reason_key": reason_key, "reason_params": line.get("reason_params") or {}},
                )
            )
        return failures or [_result(self, True, "OK")]


class StatutoryVatAddsUp(ValidationRule):
    rule_id = "tax_withholding.statutory_vat_identity"
    name = "Computed VAT Equals Withheld Plus Payable"
    standard = "tax_withholding"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = (
        "The VAT computed on a document is declared in two parts, by the buyer and by the seller, "
        "and the two parts must add up to it exactly."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is(context, RECORD_STATUTORY):
            return []
        computed = _line(context, "vat_computed")
        withheld = _line(context, "vat_withheld")
        payable = _line(context, "vat_payable")
        if computed is None or withheld is None or payable is None:
            return []
        statuses = {
            "vat_computed": _text(computed.get("calc_status")),
            "vat_withheld": _text(withheld.get("calc_status")),
            "vat_payable": _text(payable.get("calc_status")),
        }
        # A held figure has no amount to add. The held rule reports it; this
        # one has nothing to compare until all three are known.
        if "held" in statuses.values():
            return [_result(self, True, "OK", details=statuses)]
        if statuses["vat_computed"] != "value" or statuses["vat_payable"] != "value":
            return [_result(self, True, "OK", details=statuses)]

        currency = _currency(_record(context))
        computed_amount = _amount(computed.get("tax_amount"))
        payable_amount = _amount(payable.get("tax_amount"))
        # "Not applicable" is a decision that nothing is withheld, so the
        # whole VAT is payable. It is the only case with no withheld amount.
        nothing_withheld = statuses["vat_withheld"] == "not_applicable"
        withheld_amount = None if nothing_withheld else _amount(withheld.get("tax_amount"))
        details: dict[str, Any] = {
            **statuses,
            "computed": str(computed_amount) if computed_amount is not None else None,
            "withheld": str(withheld_amount) if withheld_amount is not None else None,
            "payable": str(payable_amount) if payable_amount is not None else None,
            "currency_code": currency,
        }
        if computed_amount is None or payable_amount is None or (withheld_amount is None and not nothing_withheld):
            return [
                _result(
                    self,
                    False,
                    "A VAT figure is recorded as a value but carries no readable amount, so the three cannot be added up.",
                    suggestion="Recalculate the document's taxes.",
                    details=details,
                )
            ]
        parts = payable_amount if withheld_amount is None else withheld_amount + payable_amount
        if parts == computed_amount:
            return [_result(self, True, "OK", details=details)]
        if withheld_amount is None:
            message = (
                f"No VAT is withheld, yet the payable VAT is {_fmt_money(payable_amount, currency)} "
                f"and the computed VAT is {_fmt_money(computed_amount, currency)}."
            )
        else:
            message = (
                f"The computed VAT is {_fmt_money(computed_amount, currency)}, but the withheld "
                f"{_fmt_money(withheld_amount, currency)} and the payable {_fmt_money(payable_amount, currency)} "
                f"add up to {_fmt_money(withheld_amount + payable_amount, currency)}."
            )
        return [
            _result(
                self,
                False,
                message + " The buyer's return and the seller's return would not add up to the document.",
                suggestion="Recalculate the document's taxes; the payable VAT is always the computed VAT less the withheld VAT.",
                details=details,
            )
        ]


class StatutoryOverrideHasReason(ValidationRule):
    rule_id = "tax_withholding.statutory_override_reason"
    name = "Overridden Amount Carries A Reason"
    standard = "tax_withholding"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "An amount a person entered in place of the computed one must say why."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is(context, RECORD_STATUTORY):
            return []
        failures: list[RuleResult] = []
        for line in _lines(context):
            has_override = bool(line.get("overridden")) or line.get("override_amount") is not None
            if not has_override or _text(line.get("override_reason")):
                continue
            kind = _text(line.get("kind"))
            failures.append(
                _result(
                    self,
                    False,
                    (
                        f"The amount of '{kind}' was entered by hand with no reason. An unexplained number "
                        "on a tax line cannot be audited."
                    ),
                    element_ref=kind or None,
                    suggestion="Record why the computed amount was replaced, or remove the override.",
                    details={"kind": kind},
                )
            )
        return failures or [_result(self, True, "OK")]


class StatutoryRateIsEffective(ValidationRule):
    rule_id = "tax_withholding.statutory_rate_not_effective"
    name = "Stored Rate Row Is In Force On The Document Date"
    standard = "tax_withholding"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "A figure must be computed from the rate row in force on the date the document is taxed on."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is(context, RECORD_STATUTORY):
            return []
        on_date = _as_date(_record(context).get("document_date"))
        if on_date is None:
            return []
        failures: list[RuleResult] = []
        for line in _lines(context):
            starts = _as_date(line.get("rate_effective_from"))
            ends = _as_date(line.get("rate_effective_to"))
            if starts is None:
                # No rate row stands behind this figure.
                continue
            if starts <= on_date and (ends is None or on_date <= ends):
                continue
            kind = _text(line.get("kind"))
            code = _text(line.get("code"))
            window = f"from {starts.isoformat()}" + (f" to {ends.isoformat()}" if ends else "")
            failures.append(
                _result(
                    self,
                    False,
                    (
                        f"The figure '{kind}' was computed from the rate for category '{code}', which is in "
                        f"force {window}. The document is dated {on_date.isoformat()}."
                    ),
                    element_ref=kind or None,
                    suggestion="Recalculate the document's taxes so the rate in force on its date is used.",
                    details={
                        "kind": kind,
                        "code": code,
                        "document_date": on_date.isoformat(),
                        "rate_effective_from": starts.isoformat(),
                        "rate_effective_to": ends.isoformat() if ends else "",
                    },
                )
            )
        return failures or [_result(self, True, "OK")]


class StatutoryThresholdWasEvaluated(ValidationRule):
    rule_id = "tax_withholding.statutory_threshold_unevaluated"
    name = "Threshold Could Be Judged From This Document"
    standard = "tax_withholding"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = (
        "A threshold stated in another currency, or one that applies to a payee's whole year, "
        "cannot be judged from one document."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _is(context, RECORD_STATUTORY):
            return []
        failures: list[RuleResult] = []
        for line in _lines(context):
            reason_key = _text(line.get("reason_key"))
            if reason_key not in THRESHOLD_UNEVALUATED_REASONS:
                continue
            kind = _text(line.get("kind"))
            if kind == "vat_payable":
                # Repeats the reason of the withheld VAT it is derived from.
                continue
            if reason_key == "threshold_needs_year_total":
                why = "the limit applies to the payee's total for the year, which one document cannot show"
                advice = "Check the payee's year to date, then enter the amount with a reason or mark the tax as not applicable."
            else:
                why = "the limit is stated in a currency other than the document's"
                advice = "Convert at the rate for the document date, then enter the amount with a reason or mark the tax as not applicable."
            failures.append(
                _result(
                    self,
                    False,
                    f"The limit for '{kind}' has not been applied: {why}.",
                    element_ref=kind or None,
                    suggestion=advice,
                    details={"kind": kind, "reason_key": reason_key, "reason_params": line.get("reason_params") or {}},
                )
            )
        return failures or [_result(self, True, "OK")]


_TAX_WITHHOLDING_RULES: tuple[ValidationRule, ...] = (
    TaxableBaseIsCorrect(),
    WithheldWithinBase(),
    VerificationSupportsBand(),
    VerificationExpiringInPeriod(),
    RateMatchesBand(),
    ReverseChargeInvoiceIsWellFormed(),
    StatutoryRateIsConfirmed(),
    StatutoryLineIsNotHeld(),
    StatutoryVatAddsUp(),
    StatutoryOverrideHasReason(),
    StatutoryRateIsEffective(),
    StatutoryThresholdWasEvaluated(),
)


def register_tax_withholding_rules() -> None:
    """Register the module's validation rules with the core rule registry.

    Idempotent - the registry overwrites a rule by id, so a re-import or hot
    reload re-registers cleanly. Called from the module ``on_startup`` hook.
    """
    for rule in _TAX_WITHHOLDING_RULES:
        rule_registry.register(rule, [TAX_WITHHOLDING_RULE_SET])
    logger.debug("Registered %d tax withholding validation rules", len(_TAX_WITHHOLDING_RULES))


async def evaluate_record(record: dict[str, Any], *, record_id: str = "") -> list[RuleResult]:
    """Run the rules over one record and return every finding, passing ones dropped.

    Guarded: a broken rule degrades to "no findings" and a log line rather than
    a 500, because losing somebody's saved work to a validation bug is a worse
    outcome than missing a finding on one save.
    """
    try:
        report = await validation_engine.validate(
            data=record,
            rule_sets=[TAX_WITHHOLDING_RULE_SET],
            target_type=str(record.get("record_type") or "tax_withholding"),
            target_id=record_id,
        )
    except Exception:  # noqa: BLE001 - validation augments the save; never break it
        logger.warning("tax withholding validation failed for record %s", record_id, exc_info=True)
        return []
    return [result for result in report.results if not result.passed and not result.is_engine_error]


def blocking_findings(results: list[RuleResult]) -> list[RuleResult]:
    """The subset that must be fixed before a record may leave draft."""
    return [result for result in results if result.severity == Severity.ERROR]


__all__ = [
    "RECORD_DEDUCTION",
    "RECORD_REVERSE_CHARGE",
    "RECORD_STATUTORY",
    "TAX_WITHHOLDING_RULE_SET",
    "blocking_findings",
    "evaluate_record",
    "register_tax_withholding_rules",
]
