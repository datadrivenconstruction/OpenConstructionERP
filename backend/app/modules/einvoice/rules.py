# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""EN 16931 business rules, evaluated in Python.

A receiver validates an incoming e-invoice against the EN 16931 Schematron (in
Germany, the KoSIT validator). Every finding it reports carries a rule
identifier such as ``BR-61`` or ``BR-CO-15``, and that identifier, not the
wording, is what the sender has to act on.

This module evaluates the same rules natively. Running a Schematron engine
would mean a JVM or an XSLT processor plus the rule artefacts, which the
platform's 2GB-VPS budget does not have room for; the rules themselves are
small predicates over the semantic model, so they are expressed here directly.
Each one cites the identifier a receiver would report, which keeps our finding
and theirs comparable. This is a well-cited subset, not the full artefact: it
covers the rules an invoice assembled from platform data can actually break.

Identifier namespaces used here:
    * ``BR-*`` / ``BR-CO-*``  EN 16931-1 content and calculation rules
    * ``BR-S-*``, ``BR-Z-*``, ``BR-E-*``, ``BR-AE-*``, ``BR-IC-*``,
      ``BR-G-*``, ``BR-O-*``  the per VAT-category rule families
    * ``BR-DE-*``  XRechnung (KoSIT) national rules
    * ``PEPPOL-EN16931-*``  Peppol BIS Billing 3.0 rules
    * ``OCE-*``  house advisories, warning severity, not part of any standard
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from app.core.money import minor_units
from app.modules.einvoice.profiles import Profile, get_profile

if TYPE_CHECKING:  # pragma: no cover - annotations only, avoids an import cycle
    from app.modules.einvoice.cii import EInvoice

__all__ = [
    "DE_INVOICE_TYPE_CODES",
    "DIRECT_DEBIT_CODES",
    "FATAL",
    "PAYMENT_CARD_CODES",
    "UNTDID_4461_CODES",
    "VAT_CATEGORY_CODES",
    "WARNING",
    "RuleViolation",
    "check",
    "check_profile",
    "fatal_only",
    "money_decimals",
    "violation_ids",
]

FATAL = "fatal"
WARNING = "warning"

# EN 16931 caps document amounts at two decimals (the BR-DEC-* family), so a
# three-decimal currency such as KWD is still written with two here. Currencies
# with no minor unit (JPY, CLP, KRW, XOF, ...) must not show cents at all.
_EN16931_MAX_DECIMALS = 2

# UNTDID 4461 payment means that assert a credit transfer, which is what makes
# the payment account identifier (BT-84) mandatory under BR-61.
CREDIT_TRANSFER_CODES = frozenset({"30", "58"})

# The other two payment-means families XRechnung knows. Each obliges the document
# to carry its own group, and this writer emits neither BG-18 (payment card) nor
# BG-19 (direct debit), so naming one of these codes can only produce a document
# that fails BR-DE-24-a or BR-DE-25-a at the receiver.
PAYMENT_CARD_CODES = frozenset({"48", "54", "55"})
DIRECT_DEBIT_CODES = frozenset({"59"})

# UNTDID 4461 as EN 16931 publishes it (BT-81). Kept whole rather than trimmed to
# the codes this writer emits: the list says which values are a payment means at
# all, and the profile rules below say which of them this writer can express.
UNTDID_4461_CODES: frozenset[str] = frozenset(
    {str(n) for n in range(1, 71)} | {"74", "75", "76", "77", "78", "91", "92", "93", "94", "95", "96", "97", "ZZZ"}
)

# BT-3 document type codes XRechnung expects (UNTDID 1001), with the name each
# carries, so a screen can offer them instead of asking for a number. 875, 876
# and 877 are the German construction sequence (Abschlagsrechnung,
# Teilschlussrechnung, Schlussrechnung) and are the reason this list matters to
# this platform at all: a construction invoice that calls itself 380 is filed as
# an ordinary commercial invoice.
DE_INVOICE_TYPE_CODES: dict[str, str] = {
    "326": "Partial invoice",
    "380": "Commercial invoice",
    "381": "Credit note",
    "384": "Corrected invoice",
    "389": "Self-billed invoice",
    "875": "Partial construction invoice",
    "876": "Partial final construction invoice",
    "877": "Final construction invoice",
}

# VAT category code (BT-151/BT-118, UNTDID 5305) -> its rule family prefix.
_CATEGORY_RULE_PREFIX = {
    "S": "BR-S",  # standard rated
    "Z": "BR-Z",  # zero rated
    "E": "BR-E",  # exempt
    "AE": "BR-AE",  # reverse charge
    "K": "BR-IC",  # intra-community supply
    "G": "BR-G",  # free export
    "O": "BR-O",  # outside the scope of VAT
    "L": "BR-IG",  # Canary Islands
    "M": "BR-IP",  # Ceuta and Melilla
}

# Categories whose VAT rate must be zero, and those whose rate must be positive.
_ZERO_RATE_CATEGORIES = frozenset({"Z", "E", "AE", "K", "G", "O"})
_POSITIVE_RATE_CATEGORIES = frozenset({"S", "L", "M"})

# The exemption-reason obligations of the BR-x-10 slot, straight from the
# EN 16931-1 rule list. A breakdown group in an exempting category must say why
# no VAT is charged (BT-120 reason text or BT-121 reason code), and a standard
# or zero-rated group must not carry a reason at all - zero rated is a
# statement, not an exemption. BR-IG-10 / BR-IP-10 (the Canary Islands and
# Ceuta/Melilla families) are deliberately not carried: their -10 wording is
# not verified against the artefact here, and a wrong obligation is worse than
# a missing one.
_REASON_REQUIRED_CATEGORIES = frozenset({"E", "AE", "K", "G", "O"})
_REASON_FORBIDDEN_CATEGORIES = frozenset({"S", "Z"})

# The category codes an invoice may carry, derived from the rule families above
# so a code and the rules that police it can never drift apart. Anything that
# accepts a category from a user validates against this.
VAT_CATEGORY_CODES: frozenset[str] = frozenset(_CATEGORY_RULE_PREFIX)


@dataclass(frozen=True)
class RuleViolation:
    """One rule finding.

    Attributes:
        rule_id: the identifier a receiver's validator reports, e.g. ``BR-61``.
        severity: :data:`FATAL` (the document will be rejected) or
            :data:`WARNING` (it will be accepted but something is missing).
        message: what the user has to do about it, in plain language.
        term: the EN 16931 business term at fault, e.g. ``BT-84``.
        params: the values ``message`` interpolates, under the names a
            translation of this rule uses for them. A screen that renders the
            finding in another language looks the rule id up in its catalogue
            and feeds these in, so the German sentence still names line 3 and
            still quotes the amount the receiver will expect. Without them a
            translated catalogue could only carry rules whose wording is
            constant, which is most of the calculation family gone.
    """

    rule_id: str
    severity: str
    message: str
    term: str | None = None
    params: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.rule_id}: {self.message}"


# ── currency minor units, per code and on purpose ─────────────────────────────
#
# Two registers publish a digit count per currency and they are not the same
# list, because they answer different questions. ISO 4217 states how a currency
# is subdivided. CLDR states how a person in a locale writes it. Measured
# against ISO 4217 (list-one.xml, Pblshd 2026-01-01) and CLDR 49
# (common/supplemental/supplementalData.xml, the ``<fractions>`` block), they
# part company on fourteen of the codes below.
#
# Two codes are routinely miscounted into that set and are not in it:
#
#   IQD  ISO 3, CLDR 0. A different case entirely: ISO gives the Iraqi dinar
#        three minor digits, and ``_EN16931_MAX_DECIMALS`` trims that to two
#        exactly as it trims KWD. Carried below at 3 so that the cap stays the
#        thing which trims it, rather than the trimming being pre-baked here.
#   PKR  ISO 2, CLDR 2 - no disagreement at all. Only CLDR's *cashDigits* is 0,
#        and that governs rounding banknotes at a till, not a written amount.
#        Expect an instrument to contradict this and do not "correct" it on the
#        strength of one: asking a running engine gives 0 for PKR wherever its
#        bundled ICU is a CLDR release behind, because the digits for this one
#        code changed between releases. The check that tells the two apart is
#        CZK, TWD, DKK, SEK and NOK, which all carry a zero cash rule and all
#        still answer 2 - so an engine answering 0 for PKR is reporting older
#        data, not reading *cashDigits*. Nothing turns on it either way: the
#        value layer and this table both hold 2 for PKR, and only a screen ever
#        asks the engine.
#
# EN 16931 does not settle the remaining fourteen, which is why they need a
# decision recorded rather than derived. Checked against the CEN validation
# artefacts v1.3.16 and the XRechnung (KoSIT) schematron v2.5.0:
#
#   * the BR-DEC-* family is 21 rules and every one of them is a MAXIMUM
#     ("at most two decimals"), tested either as
#     ``string-length(substring-after(amount,'.')) <= 2`` or as
#     ``. = round(. * 100) div 100``. None imposes a minimum and none looks at
#     the currency, so ``1000`` and ``1000.00`` both pass every one of them.
#   * BR-CO-17 and the BR-x-08 family carry a tolerance of one whole currency
#     unit, which a half-unit rounding cannot exceed.
#   * the XRechnung CIUS adds no decimals rule of its own.
#
# So both answers produce a document that validates where we file it, and the
# choice is a question about money rather than about conformance.
#
# Every value here is the value this module already returned before the table
# was written, so recording them changed no document. What changed is that each
# one is now a decision with its reason beside it, instead of a lookup that
# happened to miss and land on the default.
_DOCUMENT_MINOR_UNITS: dict[str, int] = {
    # ISO 2, CLDR 0. All twelve already came out as two, but by two different
    # routes: COP and MGA were carried in ``CURRENCIES`` at 2, and the other
    # ten were absent from it and reached 2 only by missing the lookup and
    # landing on the default. Two is also ISO's count, so naming them here
    # turns that coincidence into a decision without moving any value.
    "AFN": 2,
    "ALL": 2,
    "COP": 2,
    "IRR": 2,
    "KPW": 2,
    "LAK": 2,
    "LBP": 2,
    "MGA": 2,
    "MMK": 2,
    "SOS": 2,
    "SYP": 2,
    "YER": 2,
    # ISO 2, CLDR 2 - no disagreement to resolve. Absent from ``CURRENCIES``
    # and so reached 2 by the default; listed anyway, because reading this
    # table should answer the question for every code the dispute is said to
    # cover, including the one that turns out not to be in it.
    "PKR": 2,
    # ISO 3, CLDR 0. Capped to 2 by EN 16931, like KWD and the other Gulf codes.
    "IQD": 3,
    # ISO 2, CLDR 0, and these two are the only codes in the whole 79-entry
    # ``CURRENCIES`` registry whose stored count contradicts ISO 4217: it holds
    # the CLDR zero for them. So a forint invoice is issued without fillér and
    # a rupiah invoice without sen, in every syntax - CII, UBL and the PDF all
    # read this one function.
    #
    # DECIDED, and decided as zero. This pair carried an "undecided" marker for
    # some time on the reading that ISO says two, CLDR says zero and EN 16931
    # breaks no tie. What settles it is not a third standard but the subunit
    # itself: the fillér was withdrawn from circulation in 1999 and the sen is
    # likewise long gone, so neither amount CAN be settled in the subunit ISO
    # still lists. A count of two would not be a more precise forint, it would
    # be two digits that no payment can ever carry.
    #
    # The reading that made it look open was that our resolvers disagreed. They
    # do not. ``app.core.money`` holds zero for both, the screen resolver takes
    # CLDR's zero through the running engine, and this table holds zero: four
    # readers, one answer, and only ISO's own list on the other side. Marking a
    # unanimous position as disputed made every reader of it hesitate over a
    # question the code had already answered.
    "HUF": 0,
    "IDR": 0,
}


def money_decimals(currency_code: str) -> int:
    """Decimal places to write for an amount in ``currency_code``.

    The currency's minor unit, capped at the two decimals EN 16931 allows for
    document amounts. A currency with no minor unit yields ``0``, so a yen or
    peso amount is never printed with cents.

    This is the document count, and it is not the same number a screen uses.
    It decides two things at once: how many digits an amount is written with
    in the XML and on the PDF, and - because :func:`_round` quantises to it -
    what the totals are rounded to before they are compared. Both callers must
    see the same value or a document stops agreeing with its own PDF.

    Codes whose two registers disagree are resolved from
    :data:`_DOCUMENT_MINOR_UNITS` one by one, with the reasoning recorded
    beside each; anything else takes its count from :func:`app.core.money.minor_units`,
    and an unknown code falls back to two there. Every code in that table is
    settled; a code added to it without a decision recorded beside it fails its
    own gate.

    Args:
        currency_code: ISO 4217 code, e.g. ``"EUR"`` or ``"JPY"``.

    Returns:
        Number of decimal places, between 0 and 2.
    """
    code = (currency_code or "").strip().upper()
    # The document count is the value count, capped. Anything this table has
    # not explicitly decided is asked of ``app.core.money``, which is the one
    # place a currency's subdivision is recorded, so the two can never hold
    # separate opinions about the same code.
    decimals = _DOCUMENT_MINOR_UNITS.get(code, minor_units(code))
    return min(max(decimals, 0), _EN16931_MAX_DECIMALS)


def _quantum(currency_code: str) -> Decimal:
    return Decimal(1).scaleb(-money_decimals(currency_code))


def _round(value: Decimal, currency_code: str) -> Decimal:
    return value.quantize(_quantum(currency_code), rounding=ROUND_HALF_UP)


def violation_ids(violations: Iterable[RuleViolation]) -> set[str]:
    """The set of rule identifiers present, for assertions and de-duplication."""
    return {v.rule_id for v in violations}


def fatal_only(violations: Iterable[RuleViolation]) -> list[RuleViolation]:
    """Just the findings that would get the document rejected."""
    return [v for v in violations if v.severity == FATAL]


# ── individual rule groups ────────────────────────────────────────────────────


def _check_header(inv: EInvoice) -> list[RuleViolation]:
    """Mandatory header content (BR-2 .. BR-16)."""
    out: list[RuleViolation] = []
    if not inv.invoice_number:
        out.append(RuleViolation("BR-2", FATAL, "Give the invoice a number.", "BT-1"))
    if not inv.issue_date:
        out.append(RuleViolation("BR-3", FATAL, "Set the invoice date.", "BT-2"))
    if not inv.type_code:
        out.append(RuleViolation("BR-4", FATAL, "Set the invoice type, an invoice or a credit note.", "BT-3"))
    if not inv.currency:
        out.append(RuleViolation("BR-5", FATAL, "Set the invoice currency, for example EUR.", "BT-5"))
    if not inv.lines:
        out.append(RuleViolation("BR-16", FATAL, "Add at least one invoice line before sending.", "BG-25"))
    return out


# Where each side is edited. A finding that names a screen holding no such
# field is a dead end, so these follow the editors rather than the document:
# the standing settings hold seller columns only, and the buyer is read from
# the contact the invoice is billed to. The engine sees an assembled document
# and not its direction, so the buyer sentence is written for the receivable
# case, which is the one that maps a contact onto the buyer at all.
# ``_INVOICE_HOME`` is the third editor: fields that identify one document
# (the buyer reference / Leitweg-ID, the VAT declaration) live under
# ``metadata.einvoice`` on the invoice itself and are edited on the invoice
# form, never in the settings - the settings model has no such columns by
# construction (``EInvoiceSettings.as_defaults`` returns seller and payment
# fields only).
_SELLER_PARTY_HOME = "in the e-invoice settings"
_BUYER_PARTY_HOME = "on the contact this invoice bills"
_INVOICE_HOME = "on this invoice"


def _check_parties(inv: EInvoice) -> list[RuleViolation]:
    """Seller and buyer identity and address (BR-6 .. BR-11, BR-CO-9, BR-CO-26)."""
    out: list[RuleViolation] = []
    if not inv.seller.name:
        out.append(RuleViolation("BR-6", FATAL, f"Add the seller name {_SELLER_PARTY_HOME}.", "BT-27"))
    if not inv.buyer.name:
        out.append(RuleViolation("BR-7", FATAL, f"Add the buyer name {_BUYER_PARTY_HOME}.", "BT-44"))
    for rule_id, party, term, where in (
        ("BR-9", inv.seller, "BT-40", f"seller country code, two letters such as DE or FR, {_SELLER_PARTY_HOME}"),
        ("BR-11", inv.buyer, "BT-55", f"buyer country code, two letters such as DE or FR, {_BUYER_PARTY_HOME}"),
    ):
        if not party.country_code:
            out.append(RuleViolation(rule_id, FATAL, f"Add the {where}.", term))
    if not (inv.seller.vat_id or inv.seller.tax_number or inv.seller.legal_id):
        out.append(
            RuleViolation(
                "BR-CO-26",
                FATAL,
                "Add the seller VAT id (BT-31) or, if there is none, a tax number (BT-32) in the e-invoice settings.",
                "BT-31",
            )
        )
    for who, vat_id, term in (("seller", inv.seller.vat_id, "BT-31"), ("buyer", inv.buyer.vat_id, "BT-48")):
        if vat_id and not _has_country_prefix(vat_id):
            out.append(
                RuleViolation(
                    "BR-CO-9",
                    FATAL,
                    f"The {who} VAT identifier must start with its country code, for example DE{vat_id}.",
                    term,
                    # ``party`` is an enumerated value, not prose: a screen
                    # renders it through its own catalogue rather than printing
                    # the English word into a translated sentence.
                    {"party": who, "example": f"DE{vat_id}"},
                )
            )
    return out


def _has_country_prefix(vat_id: str) -> bool:
    """True when a VAT identifier starts with an ISO 3166-1 alpha-2 prefix."""
    cleaned = vat_id.strip().replace(" ", "")
    return len(cleaned) > 2 and cleaned[:2].isalpha()


def _check_lines(inv: EInvoice) -> list[RuleViolation]:
    """Mandatory line content (BR-21 .. BR-27)."""
    out: list[RuleViolation] = []
    for line in inv.lines:
        where = line.line_id or "?"
        if not line.line_id:
            out.append(RuleViolation("BR-21", FATAL, "Every invoice line needs a line number.", "BT-126"))
        if not line.name:
            out.append(
                RuleViolation(
                    "BR-25", FATAL, f"Line {where} needs an item name or description.", "BT-153", {"line": where}
                )
            )
        if not line.unit:
            out.append(
                RuleViolation("BR-23", FATAL, f"Line {where} needs a unit of measure.", "BT-130", {"line": where})
            )
        if line.net_unit_price is None or line.net_unit_price < 0:
            out.append(
                RuleViolation(
                    "BR-27", FATAL, f"The unit price on line {where} cannot be negative.", "BT-146", {"line": where}
                )
            )
    return out


def _check_totals(inv: EInvoice) -> list[RuleViolation]:
    """The calculation chain (BR-CO-10, BR-CO-13, BR-CO-14, BR-CO-15, BR-CO-16).

    Each comparison sums first and rounds once, while a receiver of the emitted
    document rounds every figure first and then sums the strings it was given.
    The two agree only when no amount carries anything below the currency's
    quantum, which is why this is deliberately left as it is rather than
    tightened: it is the writer's job to hand over amounts already at the
    quantum, and ``build_einvoice`` now does. Tightening this instead would
    move the guarantee to whichever caller happened to be checked, and would
    also judge invoices that reached an :class:`EInvoice` by some other route.
    What holds the writer to it is a test that parses the document back and
    adds it up the way its receiver will.
    """
    out: list[RuleViolation] = []
    cur = inv.currency
    line_sum = sum((ln.line_net_amount for ln in inv.lines), Decimal("0"))
    if _round(inv.line_total, cur) != _round(line_sum, cur):
        out.append(RuleViolation("BR-CO-10", FATAL, "The invoice lines do not add up to the net total.", "BT-106"))
    if _round(inv.tax_basis_total, cur) != _round(inv.line_total, cur):
        out.append(
            RuleViolation(
                "BR-CO-13",
                FATAL,
                "The net total to be taxed must equal the sum of the invoice lines.",
                "BT-109",
            )
        )
    breakdown_tax = sum((g.tax_amount for g in inv.tax_subtotals), Decimal("0"))
    if _round(inv.tax_total, cur) != _round(breakdown_tax, cur):
        out.append(RuleViolation("BR-CO-14", FATAL, "The VAT total must equal the sum of the VAT breakdown.", "BT-110"))
    if _round(inv.grand_total, cur) != _round(inv.tax_basis_total + inv.tax_total, cur):
        out.append(RuleViolation("BR-CO-15", FATAL, "The gross total must equal the net total plus VAT.", "BT-112"))
    if _round(inv.due_payable, cur) != _round(inv.grand_total - inv.prepaid_amount, cur):
        out.append(
            RuleViolation(
                "BR-CO-16",
                FATAL,
                "The amount due must be the gross total minus anything already paid or retained.",
                "BT-115",
            )
        )
    return out


def _check_vat_breakdown(inv: EInvoice) -> list[RuleViolation]:
    """The VAT breakdown and its per-category families (BR-45 .. BR-48, BR-CO-17, BR-x-1/5/8)."""
    out: list[RuleViolation] = []
    cur = inv.currency

    for grp in inv.tax_subtotals:
        if not grp.category:
            out.append(RuleViolation("BR-47", FATAL, "Every VAT breakdown group needs a category code.", "BT-118"))
            continue
        if grp.rate is None:
            out.append(RuleViolation("BR-48", FATAL, "Every VAT breakdown group needs a VAT rate.", "BT-119"))
            continue
        expected = _round(grp.basis * grp.rate / Decimal("100"), cur)
        if _round(grp.tax_amount, cur) != expected:
            out.append(
                RuleViolation(
                    "BR-CO-17",
                    FATAL,
                    f"The VAT for the {grp.rate}% group must be {expected}, which is {grp.basis} times {grp.rate}%.",
                    "BT-117",
                    {"rate": str(grp.rate), "expected": str(expected), "basis": str(grp.basis)},
                )
            )

    # Per-category rate rules, on the lines.
    for line in inv.lines:
        prefix = _CATEGORY_RULE_PREFIX.get(line.vat_category)
        if prefix is None:
            out.append(
                RuleViolation(
                    "BR-CL-18",
                    FATAL,
                    f"Line {line.line_id} has VAT category {line.vat_category!r}, which is not a known code.",
                    "BT-151",
                    {"line": str(line.line_id), "category": str(line.vat_category)},
                )
            )
            continue
        if line.vat_category in _ZERO_RATE_CATEGORIES and line.vat_rate != 0:
            out.append(
                RuleViolation(
                    f"{prefix}-5",
                    FATAL,
                    f"Line {line.line_id} is VAT category {line.vat_category}, so its rate must be 0%.",
                    "BT-152",
                )
            )
        if line.vat_category in _POSITIVE_RATE_CATEGORIES and line.vat_rate <= 0:
            out.append(
                RuleViolation(
                    f"{prefix}-5",
                    FATAL,
                    f"Line {line.line_id} is standard rated, so its VAT rate must be above 0%.",
                    "BT-152",
                )
            )

    # Every category used on a line must appear in the breakdown (BR-x-1).
    breakdown_categories = {g.category for g in inv.tax_subtotals}
    for category in {ln.vat_category for ln in inv.lines}:
        prefix = _CATEGORY_RULE_PREFIX.get(category)
        if prefix and category not in breakdown_categories:
            out.append(
                RuleViolation(
                    f"{prefix}-1",
                    FATAL,
                    f"The VAT breakdown is missing a group for category {category}.",
                    "BG-23",
                )
            )

    out += _check_breakdown_basis(inv)
    out += _check_exemption_reasons(inv)
    return out


def _check_exemption_reasons(inv: EInvoice) -> list[RuleViolation]:
    """The BR-x-10 slot: an exemption must be justified, a rating must not be.

    One finding per breakdown group, under the identifier of that group's own
    family, so the sender reads exactly what a receiver's validator would
    report. The reason is invoice data (``metadata.einvoice``), which is why
    the remedy names the invoice and not the settings.
    """
    out: list[RuleViolation] = []
    for grp in inv.tax_subtotals:
        prefix = _CATEGORY_RULE_PREFIX.get(grp.category)
        if prefix is None:
            continue  # unknown category is BR-CL-18 territory, reported above
        has_reason = bool((grp.exemption_reason or "").strip() or (grp.exemption_reason_code or "").strip())
        if grp.category in _REASON_REQUIRED_CATEGORIES and not has_reason:
            out.append(
                RuleViolation(
                    f"{prefix}-10",
                    FATAL,
                    f"The invoice uses VAT category {grp.category}, so it must state the VAT exemption "
                    f"reason (BT-120) or reason code (BT-121) {_INVOICE_HOME}.",
                    "BT-120",
                )
            )
        elif grp.category in _REASON_FORBIDDEN_CATEGORIES and has_reason:
            out.append(
                RuleViolation(
                    f"{prefix}-10",
                    FATAL,
                    f"VAT category {grp.category} must not carry a VAT exemption reason. Remove the "
                    f"reason {_INVOICE_HOME}, or use an exempting category such as E.",
                    "BT-120",
                )
            )
    return out


def _check_vat_declared(inv: EInvoice) -> list[RuleViolation]:
    """OCE-VAT-01: zero-rating that nobody declared is worth a word.

    When an invoice carries no VAT information anywhere - no explicit rate or
    category, no line-level VAT, a zero tax amount - the builder can only fall
    back to a 0% rate and category Z, and every zero-rate rule then holds by
    construction. The document is formally valid and a receiver will accept
    it, which is exactly why this is a warning and not a fatal: blocking it
    would refuse an export the receiver takes. But a document that zero-rates
    real money because a field was left empty is usually a mistake, so the
    check says so instead of staying green and silent.
    """
    if inv.vat_declared or inv.tax_basis_total == 0:
        return []
    if not any(ln.vat_category == "Z" for ln in inv.lines):
        return []
    return [
        RuleViolation(
            "OCE-VAT-01",
            WARNING,
            "This invoice carries no VAT information, so it would be issued as zero rated "
            f"(category Z). Enter the VAT amount or rate {_INVOICE_HOME}, or declare the zero "
            "rating or an exemption explicitly.",
            "BT-118",
        )
    ]


def _check_breakdown_basis(inv: EInvoice) -> list[RuleViolation]:
    """Each (category, rate) group's basis must equal its own lines (BR-x-8)."""
    out: list[RuleViolation] = []
    cur = inv.currency
    line_basis: dict[tuple[str, Decimal], Decimal] = {}
    for line in inv.lines:
        key = (line.vat_category, line.vat_rate)
        line_basis[key] = line_basis.get(key, Decimal("0")) + line.line_net_amount
    group_basis: dict[tuple[str, Decimal], Decimal] = {}
    for grp in inv.tax_subtotals:
        key = (grp.category, grp.rate)
        group_basis[key] = group_basis.get(key, Decimal("0")) + grp.basis

    for key in set(line_basis) | set(group_basis):
        category, rate = key
        prefix = _CATEGORY_RULE_PREFIX.get(category)
        if prefix is None:
            continue
        expected = line_basis.get(key, Decimal("0"))
        actual = group_basis.get(key, Decimal("0"))
        if _round(expected, cur) != _round(actual, cur):
            out.append(
                RuleViolation(
                    f"{prefix}-8",
                    FATAL,
                    f"The VAT group for category {category} at {rate}% says {actual} "
                    f"but its lines add up to {expected}.",
                    "BT-116",
                )
            )
    return out


def _check_payment(inv: EInvoice) -> list[RuleViolation]:
    """Payment instructions (BR-61, plus a house advisory)."""
    out: list[RuleViolation] = []
    code = (inv.payment_means_code or "").strip()
    if code in CREDIT_TRANSFER_CODES and not (inv.payee_iban or "").strip():
        out.append(
            RuleViolation(
                "BR-61",
                FATAL,
                "This invoice says it is paid by bank transfer, so it must carry the account "
                "to pay into. Add the account number in the e-invoice settings.",
                "BT-84",
            )
        )
    if not (inv.payee_iban or "").strip():
        out.append(
            RuleViolation(
                "OCE-PAY-01",
                WARNING,
                "No bank account is given, so the buyer cannot pay this invoice automatically. "
                "Add the account number in the e-invoice settings.",
                "BT-84",
            )
        )
    return out


def _check_tax_currency(inv: EInvoice) -> list[RuleViolation]:
    """BR-53: a VAT accounting currency needs its VAT total in that currency."""
    tax_currency = (inv.tax_currency or "").strip().upper()
    if not tax_currency or tax_currency == (inv.currency or "").strip().upper():
        return []
    if inv.tax_total_in_tax_currency is None:
        return [
            RuleViolation(
                "BR-53",
                FATAL,
                f"The invoice accounts for VAT in {tax_currency}, so it must also state the VAT "
                f"total in {tax_currency}.",
                "BT-111",
                {"currency": tax_currency},
            )
        ]
    return []


# BR-DE-3, BR-DE-4, BR-DE-8, BR-DE-9: the postal address content XRechnung
# requires beyond EN 16931, as (rule id, business term, Party attribute, label).
# Verified against itplr-kosit/xrechnung-schematron v2.5.0 (XRechnung 3.0.2),
# src/validation/schematron/cii/XRechnung-CII-validation.sch, where each is a
# fatal assert on a non-blank value in the party's PostalTradeAddress.
_DE_SELLER_ADDRESS_RULES = (
    ("BR-DE-3", "BT-37", "city", "seller city"),
    ("BR-DE-4", "BT-38", "postcode", "seller post code"),
)
_DE_BUYER_ADDRESS_RULES = (
    ("BR-DE-8", "BT-52", "city", "buyer city"),
    ("BR-DE-9", "BT-53", "postcode", "buyer post code"),
)

# BR-DE-5, BR-DE-6, BR-DE-7: the seller contact XRechnung requires inside the
# SELLER CONTACT group (BG-6), same shape as the address rules above. In the
# schematron these three sit on the context
# ``SellerTradeParty/ram:DefinedTradeContact``, so they fire only once that group
# exists; a seller with no contact at all is BR-DE-2 and nothing else, which is
# what :func:`_check_de_seller_contact` reproduces.
_DE_SELLER_CONTACT_RULES = (
    ("BR-DE-5", "BT-41", "contact_name", "seller contact point"),
    ("BR-DE-6", "BT-42", "contact_phone", "seller contact telephone number"),
    ("BR-DE-7", "BT-43", "contact_email", "seller contact email address"),
)

# BR-DE-16 applies to an invoice using any of these VAT categories, which is
# every category except O (outside the scope of VAT).
_DE_TAX_REGISTRATION_CATEGORIES = frozenset({"S", "Z", "E", "AE", "K", "G", "L", "M"})


def _check_de_postal_address(inv: EInvoice) -> list[RuleViolation]:
    """City and post code on both parties, which XRechnung requires.

    EN 16931 is satisfied by a postal address that names only its country, so a
    document can be EN 16931 complete and still be rejected in Germany. KoSIT
    asserts these against a non-blank value, which is why a field holding only
    spaces fails exactly as an absent one does.

    Args:
        inv: the assembled invoice.

    Returns:
        One fatal finding per missing field, seller before buyer.
    """
    out: list[RuleViolation] = []
    for address_rules, party, where in (
        (_DE_SELLER_ADDRESS_RULES, inv.seller, _SELLER_PARTY_HOME),
        (_DE_BUYER_ADDRESS_RULES, inv.buyer, _BUYER_PARTY_HOME),
    ):
        for rule_id, term, attribute, label in address_rules:
            if not (getattr(party, attribute) or "").strip():
                out.append(
                    RuleViolation(
                        rule_id,
                        FATAL,
                        f"Add the {label} ({term}) {where}; XRechnung requires it.",
                        term,
                    )
                )
    return out


def _check_de_seller_contact(inv: EInvoice) -> list[RuleViolation]:
    """The SELLER CONTACT group (BG-6) and its three fields.

    KoSIT asserts the group on the seller party (BR-DE-2) and each field on the
    group itself (BR-DE-5, BR-DE-6, BR-DE-7). A schematron rule whose context is
    absent does not fire, so a seller carrying no contact detail at all produces
    one finding and not four. That is reproduced here rather than smoothed over:
    the writer emits ``DefinedTradeContact`` exactly when one of the three fields
    has a value, so the engine and the document agree on when the group exists.

    BR-DE-5 accepts either a person name or a department name. This platform
    stores one contact point and writes it as the person name, which satisfies
    the assert; a department-only contact is simply not expressible here, and
    that is a gap in what a user can say rather than a stricter reading.

    Args:
        inv: the assembled invoice.

    Returns:
        BR-DE-2 alone when the group is empty, otherwise one fatal finding per
        missing field.
    """
    values = {
        attribute: (getattr(inv.seller, attribute) or "").strip() for _, _, attribute, _ in _DE_SELLER_CONTACT_RULES
    }
    if not any(values.values()):
        return [
            RuleViolation(
                "BR-DE-2",
                FATAL,
                f"Add the seller contact, a name, a telephone number and an email address, "
                f"{_SELLER_PARTY_HOME}; XRechnung requires it.",
                "BG-6",
            )
        ]
    return [
        RuleViolation(
            rule_id,
            FATAL,
            f"Add the {label} ({term}) {_SELLER_PARTY_HOME}; XRechnung requires it.",
            term,
        )
        for rule_id, term, attribute, label in _DE_SELLER_CONTACT_RULES
        if not values[attribute]
    ]


def _check_de_seller_tax_registration(inv: EInvoice) -> list[RuleViolation]:
    """BR-DE-16: the seller's tax registration, on stricter terms than EN 16931.

    BR-CO-26 is satisfied by a seller registration identifier (BT-30), so a
    company that configured only its commercial-register number passes the
    European rule. KoSIT asserts a tax registration carrying scheme ``VA``
    (BT-31) or ``FC`` (BT-32), or a tax representative party (BG-11), and a
    register number is none of those. Checking the same two fields the writer
    turns into those scheme identifiers keeps this a statement about the
    document rather than about our storage.

    Applies only when the invoice uses a VAT category other than O.
    """
    categories = {ln.vat_category for ln in inv.lines} | {g.category for g in inv.tax_subtotals}
    if not (categories & _DE_TAX_REGISTRATION_CATEGORIES):
        return []
    if (inv.seller.vat_id or "").strip() or (inv.seller.tax_number or "").strip():
        return []
    return [
        RuleViolation(
            "BR-DE-16",
            FATAL,
            "Add the seller VAT identifier (BT-31) or, if there is none, the seller tax number (BT-32) "
            f"{_SELLER_PARTY_HOME}. XRechnung does not accept a company registration number here.",
            "BT-31",
        )
    ]


def _check_de_payment_means(inv: EInvoice) -> list[RuleViolation]:
    """BR-DE-23-a, BR-DE-24-a, BR-DE-25-a: the code and its group must agree.

    Each payment-means family obliges the document to carry its own group. This
    writer emits BG-17 (credit transfer) and neither BG-18 nor BG-19, so a card
    or direct-debit code cannot produce a document a receiver will take. Saying
    so here, with the identifier that receiver would report, is the whole point:
    the alternative is an export that succeeds and is rejected on arrival.
    """
    code = (inv.payment_means_code or "").strip()
    if code in CREDIT_TRANSFER_CODES and not (inv.payee_iban or "").strip():
        return [
            RuleViolation(
                "BR-DE-23-a",
                FATAL,
                "This invoice is paid by credit transfer, so it must carry the account to pay into "
                f"(BG-17). Add the IBAN {_SELLER_PARTY_HOME}.",
                "BT-84",
            )
        ]
    if code in PAYMENT_CARD_CODES:
        return [
            RuleViolation(
                "BR-DE-24-a",
                FATAL,
                f"Payment means {code} is a card payment, which has to carry the card details (BG-18). "
                "This platform cannot write that group, so choose a credit transfer code (30 or 58) "
                f"{_SELLER_PARTY_HOME}.",
                "BT-81",
                {"code": code},
            )
        ]
    if code in DIRECT_DEBIT_CODES:
        return [
            RuleViolation(
                "BR-DE-25-a",
                FATAL,
                f"Payment means {code} is a direct debit, which has to carry the mandate details (BG-19). "
                "This platform cannot write that group, so choose a credit transfer code (30 or 58) "
                f"{_SELLER_PARTY_HOME}.",
                "BT-81",
                {"code": code},
            )
        ]
    return []


def _digits(value: str) -> int:
    return sum(1 for ch in value if ch.isdigit())


def _email_shape_is_plausible(value: str) -> bool:
    """BR-DE-28's reading of an email address, which is not a full grammar.

    Exactly one ``@``, at least two characters either side of it, neither side
    touching the ``@`` with a space or a dot, and no leading or trailing dot.
    """
    if value.count("@") != 1:
        return False
    local, _, domain = value.partition("@")
    if len(local) < 2 or len(domain) < 2:
        return False
    if local[-1] in " ." or domain[0] in " .":
        return False
    return not (value.startswith(".") or value.endswith("."))


def _check_de_contact_shape(inv: EInvoice) -> list[RuleViolation]:
    """BR-DE-27 and BR-DE-28, both advisory in the CIUS ("sollen").

    Warnings on purpose. A receiver accepts a document that trips these, so
    raising them to fatal would block an export KoSIT would have taken, which is
    as much a departure from the rule text as ignoring it.
    """
    out: list[RuleViolation] = []
    phone = (inv.seller.contact_phone or "").strip()
    if phone and _digits(phone) < 3:
        out.append(
            RuleViolation(
                "BR-DE-27",
                WARNING,
                f"The seller telephone number (BT-42) should hold at least three digits, and {phone!r} does not.",
                "BT-42",
                {"phone": phone},
            )
        )
    email = (inv.seller.contact_email or "").strip()
    if email and not _email_shape_is_plausible(email):
        out.append(
            RuleViolation(
                "BR-DE-28",
                WARNING,
                f"The seller email address (BT-43) should hold exactly one @ with at least two characters "
                f"either side of it, and {email!r} does not.",
                "BT-43",
                {"email": email},
            )
        )
    return out


def _check_de_type_code(inv: EInvoice) -> list[RuleViolation]:
    """BR-DE-17: the document type code, advisory in the CIUS ("sollen")."""
    code = (inv.type_code or "").strip()
    if not code or code in DE_INVOICE_TYPE_CODES:
        return []
    known = ", ".join(f"{c} ({name})" for c, name in DE_INVOICE_TYPE_CODES.items())
    return [
        RuleViolation(
            "BR-DE-17",
            WARNING,
            f"XRechnung expects the invoice type code (BT-3) to be one of {known}, and this document says {code}.",
            "BT-3",
            # The bare codes travel beside the annotated list because the names
            # in ``known`` are English: a translated sentence can name the
            # permitted codes without importing that English into itself.
            {"code": code, "codes": ", ".join(DE_INVOICE_TYPE_CODES)},
        )
    ]


# Rules of the BR-DE family this evaluator deliberately does not carry, because
# the document shapes they judge are ones the writer never produces. Recorded so
# that a later change adding one of those shapes knows it also owes a rule, and
# so that nobody reads the silence as coverage:
#
#   BR-DE-1     BG-16 is always written; ``build_einvoice`` never leaves the
#               payment means code empty, so the group cannot be absent.
#   BR-DE-10/11 deliver-to city and post code, conditional on BG-15, which this
#               writer does not emit.
#   BR-DE-14    BT-119 in every VAT breakdown group, already fatal here as the
#               EN 16931 rule BR-48; a German receiver reports the same defect
#               under this identifier.
#   BR-DE-21    the CustomizationID is a constant in ``profiles.py`` and is the
#               value this rule asks for.
#   BR-DE-22    unique attachment filenames; no attachments are embedded.
#   BR-DE-23-b  BG-18 and BG-19 must be absent under a credit transfer, and
#   BR-DE-24-b  neither group is ever written, so each of these holds by
#   BR-DE-25-b  construction rather than by a check.
#   BR-DE-30/31 direct-debit creditor and debited account, inside BG-19.
#
# Out of scope for a different reason: BR-DE-CVD-* apply only to a document
# whose CustomizationID is the Clean Vehicles Directive one, which this platform
# does not issue. BR-DE-12, BR-DE-13 and BR-DE-29 no longer exist in the
# artefact. BR-DE-18 (Skonto notation in BT-20), BR-DE-19/20 (IBAN check digits),
# BR-DE-26 (BG-3 behind a corrected invoice) and BR-DE-TMP-32 (delivery date)
# are real gaps, not vacuous ones, and are tracked separately.


def check_profile(inv: EInvoice, profile: Profile) -> list[RuleViolation]:
    """Rules a country or network flavour adds on top of EN 16931."""
    out: list[RuleViolation] = []
    # The BR-DE family is the German national CIUS, so it applies to the German
    # profile and to nothing else: a receiver in another country validates
    # against its own specification and would never cite these identifiers.
    if profile.name == "xrechnung":
        out += _check_de_postal_address(inv)
        out += _check_de_seller_contact(inv)
        out += _check_de_seller_tax_registration(inv)
        out += _check_de_payment_means(inv)
        out += _check_de_type_code(inv)
        out += _check_de_contact_shape(inv)
    if not profile.buyer_ref_required:
        return out
    has_buyer_ref = bool((inv.buyer_reference or "").strip())
    has_order_ref = bool((inv.order_reference or "").strip())
    if has_buyer_ref or (profile.order_ref_alternative and has_order_ref):
        return out
    label = profile.label or profile.name
    if profile.name == "xrechnung":
        out.append(
            RuleViolation(
                "BR-DE-15",
                FATAL,
                f"Add the Buyer reference / Leitweg-ID (BT-10) {_INVOICE_HOME}; XRechnung requires it.",
                "BT-10",
            )
        )
    elif profile.order_ref_alternative:
        out.append(
            RuleViolation(
                "PEPPOL-EN16931-R003",
                FATAL,
                f"Add a Buyer reference (BT-10) or an Order reference (BT-13) {_INVOICE_HOME}; "
                f"{label} requires one of them.",
                "BT-10",
            )
        )
    else:
        out.append(
            RuleViolation(
                "BR-DE-15",
                FATAL,
                f"Add a Buyer reference (BT-10) {_INVOICE_HOME}; {label} requires it.",
                "BT-10",
            )
        )
    return out


# ── entry point ───────────────────────────────────────────────────────────────


def check(inv: EInvoice) -> list[RuleViolation]:
    """Evaluate every rule against an invoice.

    Args:
        inv: the assembled EN 16931 invoice.

    Returns:
        Every finding, fatal and warning alike, in a stable order. An empty
        list means the invoice passes the subset implemented here.
    """
    out: list[RuleViolation] = []
    out += _check_header(inv)
    out += _check_parties(inv)
    out += _check_lines(inv)
    out += _check_totals(inv)
    out += _check_vat_breakdown(inv)
    out += _check_vat_declared(inv)
    out += _check_payment(inv)
    out += _check_tax_currency(inv)

    profile = get_profile(inv.profile)
    if profile is None:
        out.append(
            RuleViolation(
                "BR-1",
                FATAL,
                f"Unknown e-invoice format {inv.profile!r}.",
                "BT-24",
                {"profile": str(inv.profile)},
            )
        )
    else:
        out += check_profile(inv, profile)
    return out
