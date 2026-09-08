# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""EN 16931 Cross Industry Invoice (CII) builder.

Produces the UN/CEFACT CII XML that is the shared syntax behind the German
electronic-invoice formats:

    * ZUGFeRD 2.1 (the CII XML embedded in a PDF/A-3 hybrid invoice)
    * Factur-X 1.0 (the French twin of ZUGFeRD, same CII)
    * XRechnung (the German public-sector CII profile, EN 16931 compliant)

All three share the EN 16931 semantic model; they differ only in the
guideline identifier (BT-24) and a few conditionally mandatory terms
(XRechnung requires the Buyer reference / Leitweg-ID, BT-10).

Design mirrors the existing GAEB writer (``boq.build_gaeb_xml``) and the BCF
codec: a pure, side-effect-free builder over stdlib ``xml.etree`` with all
money kept as ``Decimal``. The inbound counterpart is
``supplier_catalogs.peppol`` (UBL parser); this is the outbound CII writer.

References:
    * EN 16931-1 semantic data model
    * ZUGFeRD 2.1 / Factur-X 1.0 technical spec (CII D16B)
    * XRechnung 3.0 (KoSIT)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from xml.etree import ElementTree as ET  # noqa: N817 - trusted, we build not parse

from app.modules.einvoice.bank import is_bic, is_iban
from app.modules.einvoice.profiles import PROFILES, Profile, get_profile
from app.modules.einvoice.rules import FATAL, RuleViolation, check, check_profile, money_decimals

# --- namespaces -----------------------------------------------------------

RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"

_NS = {"rsm": RSM, "ram": RAM, "udt": UDT}
for _p, _u in _NS.items():
    ET.register_namespace(_p, _u)


def _q(prefix: str, local: str) -> str:
    """Namespace-qualified tag, e.g. ``_q("ram", "ID")``."""
    return f"{{{_NS[prefix]}}}{local}"


# --- profiles -------------------------------------------------------------
# Profiles live in the extensible ``profiles`` registry (imported above) so a
# new country is one entry there, not a change here. ``PROFILES`` /
# ``SUPPORTED_PROFILES`` / ``get_profile`` are re-exported for callers.

# Inverse of peppol._UNIT_MAP: internal unit label -> UNECE Rec-20 code.
# Kept local so the two modules stay decoupled; falls back to piece (C62).
_UNECE_BY_UNIT = {
    "pcs": "C62",
    "pc": "C62",
    "pce": "C62",
    "each": "C62",
    "pair": "PR",
    "m": "MTR",
    "lm": "MTR",
    "rm": "MTR",
    "km": "KMT",
    "cm": "CMT",
    "mm": "MMT",
    "m2": "MTK",
    "sqm": "MTK",
    "m3": "MTQ",
    "cbm": "MTQ",
    "l": "LTR",
    "kg": "KGM",
    "t": "TNE",
    # "ton" keeps the metric code it has always had: rows stored before the
    # BOQ normaliser started reading a typed "ton" as the short ton carry
    # this string meaning the tonne, and an invoice must not restate what
    # was already billed.  New input normalises to "ton_us" (STN) or "t".
    "ton": "TNE",
    "ton_us": "STN",
    "lb": "LBR",
    "lbs": "LBR",
    "g": "GRM",
    "h": "HUR",
    "hr": "HUR",
    "hour": "HUR",
    "day": "DAY",
    "d": "DAY",
    "lsum": "LS",
    "ls": "LS",
    "psch": "LS",
    "%": "P1",
}


def unece_unit(unit: str | None) -> str:
    """Map an internal unit label to a UNECE Rec-20 code (default C62 = piece)."""
    if not unit:
        return "C62"
    return _UNECE_BY_UNIT.get(unit.strip().lower(), "C62")


# --- data model -----------------------------------------------------------


class EInvoiceError(ValueError):
    """Raised when the invoice data cannot produce a valid CII document."""


@dataclass
class Party:
    """A seller or buyer trade party (EN 16931 BG-4 / BG-7)."""

    name: str
    # BT-40 / BT-55, mandatory under EN 16931 and the term a receiver reads to
    # decide which national rules apply. Empty when nobody configured it, never
    # a guess: an invoice that names a country its seller is not established in
    # is a false statement in a legal document, and a document refused for
    # naming none is the cheaper failure. BR-9 / BR-11 catch it.
    country_code: str = ""
    vat_id: str | None = None  # BT-31 / BT-48 (USt-IdNr., e.g. DE123456789)
    tax_number: str | None = None  # BT-32 (Steuernummer) when no VAT id
    legal_id: str | None = None  # BT-30 / BT-47 registration id
    line1: str | None = None  # BT-35 / BT-50
    postcode: str | None = None  # BT-38 / BT-53
    city: str | None = None  # BT-37 / BT-52
    # BG-6 CONTACT and its three fields. EN 16931 asks for none of them;
    # XRechnung makes the group and all three mandatory on the seller (BR-DE-2,
    # BR-DE-5, BR-DE-6, BR-DE-7), which is why a German invoice needs a person
    # to call and not only a company to address.
    contact_name: str | None = None  # BT-41 / BT-56
    contact_phone: str | None = None  # BT-42 / BT-57
    contact_email: str | None = None  # BT-43 / BT-58
    contact_id_scheme: str | None = None  # e.g. Leitweg endpoint scheme
    electronic_address: str | None = None  # BT-34 / BT-49 (Peppol endpoint)


@dataclass
class EInvoiceLine:
    """A single invoice line (BG-25)."""

    line_id: str
    name: str
    quantity: Decimal
    unit: str | None
    net_unit_price: Decimal  # BT-146
    line_net_amount: Decimal  # BT-131
    vat_rate: Decimal  # BT-152 (percent, e.g. 19)
    vat_category: str = "S"  # BT-151 (S standard, Z zero, AE reverse, E exempt)


@dataclass
class TaxSubtotal:
    """A VAT breakdown group (BG-23), one per rate/category."""

    category: str
    rate: Decimal
    basis: Decimal  # BT-116
    tax_amount: Decimal  # BT-117
    # BT-120 / BT-121: why no VAT is charged. Mandatory for the exempting
    # categories (E, AE, K, G, O) and forbidden for S and Z - the BR-x-10 rule
    # family in ``rules`` polices both directions.
    exemption_reason: str | None = None  # BT-120
    exemption_reason_code: str | None = None  # BT-121


@dataclass
class EInvoice:
    """The full EN 16931 invoice, ready to render as CII."""

    profile: str
    invoice_number: str  # BT-1
    issue_date: str  # BT-2 (ISO YYYY-MM-DD)
    currency: str  # BT-5
    seller: Party
    buyer: Party
    lines: list[EInvoiceLine]
    tax_subtotals: list[TaxSubtotal]
    line_total: Decimal  # BT-106
    tax_basis_total: Decimal  # BT-109
    tax_total: Decimal  # BT-110
    grand_total: Decimal  # BT-112
    due_payable: Decimal  # BT-115
    type_code: str = "380"  # BT-3 (380 invoice, 381 credit note)
    buyer_reference: str | None = None  # BT-10 (Leitweg-ID for XRechnung)
    order_reference: str | None = None  # BT-13 (buyer PO)
    due_date: str | None = None  # BT-9 (ISO)
    payment_terms: str | None = None  # BT-20
    prepaid_amount: Decimal = Decimal("0")  # BT-113
    note: str | None = None  # BT-22
    tax_currency: str | None = None  # BT-6 (VAT accounting currency)
    tax_total_in_tax_currency: Decimal | None = None  # BT-111 (required by BR-53 with BT-6)
    # BT-81. Defaults to 1 ("instrument not defined") rather than 30 ("credit
    # transfer"): claiming a transfer obliges the document to name the account
    # to pay into (BR-61), and an invoice assembled without an IBAN cannot. The
    # mapper raises this to 30 as soon as an account is known.
    payment_means_code: str = "1"
    payee_iban: str | None = None  # BT-84 (payment account identifier)
    payee_account_name: str | None = None  # BT-85
    payee_bic: str | None = None  # BT-86 (payment service provider identifier)
    # Provenance, not document content: False when the builder had no VAT
    # information anywhere (no rate, no category, zero tax amount) and fell
    # back to 0% / category Z. OCE-VAT-01 reads it to say that the zero-rating
    # is an inference rather than a statement. Defaults to True so a
    # hand-assembled invoice is taken at its word.
    vat_declared: bool = True


# --- formatting helpers ---------------------------------------------------

_2P = Decimal("0.01")
_4P = Decimal("0.0001")


def _money(value: Decimal, currency: str) -> str:
    """Format a document amount in ``currency``.

    The currency argument carries no default on purpose: an amount and the
    currency it is denominated in have to travel together, and a default is
    how a yen amount ends up printed with cents.
    """
    places = money_decimals(currency)
    return str(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def _price(value: Decimal) -> str:
    # Net unit price may carry up to 4 decimals (BT-146); trim to a tidy string.
    q = value.quantize(_4P, rounding=ROUND_HALF_UP).normalize()
    # normalize() can yield exponent form for integers (e.g. 5E+1); expand it.
    return f"{q:f}"


def _qty(value: Decimal) -> str:
    q = value.quantize(_4P, rounding=ROUND_HALF_UP).normalize()
    return f"{q:f}"


def _pct(value: Decimal) -> str:
    return str(value.quantize(_2P, rounding=ROUND_HALF_UP))


def _cii_date(iso: str) -> str:
    """ISO ``YYYY-MM-DD`` (or longer) -> CII ``YYYYMMDD`` (format 102)."""
    digits = "".join(ch for ch in iso[:10] if ch.isdigit())
    if len(digits) != 8:
        raise EInvoiceError(f"invalid invoice date: {iso!r} (need YYYY-MM-DD)")
    return digits


def _sub(parent: ET.Element, prefix: str, local: str, text: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, _q(prefix, local))
    if text is not None:
        el.text = text
    return el


def _date_el(parent: ET.Element, prefix: str, local: str, iso: str) -> None:
    wrap = _sub(parent, prefix, local)
    ds = _sub(wrap, "udt", "DateTimeString", _cii_date(iso))
    ds.set("format", "102")


# --- validation -----------------------------------------------------------


def validate_rules(inv: EInvoice) -> list[RuleViolation]:
    """Every rule finding, fatal and advisory alike, each with its identifier.

    This is the structured API: a finding carries the rule id a receiver's
    validator would report (``BR-61``), so a caller can act on the rule rather
    than on the wording of a sentence. See :mod:`app.modules.einvoice.rules`.
    """
    return check(inv)


def validate_semantics(inv: EInvoice) -> list[str]:
    """Country-agnostic EN 16931 problems as plain guidance, profile rules aside.

    Kept for callers that want the shared rules only. Prefer
    :func:`validate_rules` when the rule identifier matters.
    """
    profile = get_profile(inv.profile)
    profile_ids = {v.rule_id for v in check_profile(inv, profile)} if profile else set()
    return [v.message for v in check(inv) if v.severity == FATAL and v.rule_id not in profile_ids]


def profile_problems(inv: EInvoice, profile: Profile) -> list[str]:
    """Problems specific to one profile (e.g. XRechnung / Peppol Buyer reference)."""
    return [v.message for v in check_profile(inv, profile) if v.severity == FATAL]


def validate(inv: EInvoice) -> list[str]:
    """Blocking problems as plain guidance: everything that would be rejected.

    Advisory findings are deliberately excluded, so a missing IBAN warns
    without blocking the export. Use :func:`validate_rules` for the full list.
    """
    return [v.message for v in check(inv) if v.severity == FATAL]


# --- party rendering ------------------------------------------------------


def _party(parent: ET.Element, tag_local: str, p: Party) -> None:
    tp = _sub(parent, "ram", tag_local)
    if p.legal_id:
        _sub(tp, "ram", "ID", p.legal_id)
    _sub(tp, "ram", "Name", p.name)
    if p.legal_id:
        org = _sub(tp, "ram", "SpecifiedLegalOrganization")
        _sub(org, "ram", "ID", p.legal_id)
    # BG-6, written exactly when one of its three fields carries a value, which
    # is the condition the BR-DE-2 check in ``rules`` reads. An empty group would
    # turn one honest finding into three misleading ones at the receiver.
    if p.contact_name or p.contact_phone or p.contact_email:
        contact = _sub(tp, "ram", "DefinedTradeContact")
        if p.contact_name:
            _sub(contact, "ram", "PersonName", p.contact_name)
        if p.contact_phone:
            phone = _sub(contact, "ram", "TelephoneUniversalCommunication")
            _sub(phone, "ram", "CompleteNumber", p.contact_phone)
        if p.contact_email:
            mail = _sub(contact, "ram", "EmailURIUniversalCommunication")
            _sub(mail, "ram", "URIID", p.contact_email)
    addr = _sub(tp, "ram", "PostalTradeAddress")
    if p.postcode:
        _sub(addr, "ram", "PostcodeCode", p.postcode)
    if p.line1:
        _sub(addr, "ram", "LineOne", p.line1)
    if p.city:
        _sub(addr, "ram", "CityName", p.city)
    # BT-40 / BT-55. Written only when there is one: an absent element states
    # nothing, whereas a substituted country states something untrue. A strict
    # render never gets here without one, because BR-9 / BR-11 refuse first.
    if p.country_code:
        _sub(addr, "ram", "CountryID", p.country_code.upper())
    # BT-34 / BT-49, and only once. The contact email is BT-43 and now lives in
    # the group above; writing it here as well produced a second
    # URIUniversalCommunication on a party where the term is 0..1.
    if p.electronic_address:
        comm = _sub(tp, "ram", "URIUniversalCommunication")
        uri = _sub(comm, "ram", "URIID", p.electronic_address)
        uri.set("schemeID", p.contact_id_scheme or "EM")
    if p.vat_id:
        reg = _sub(tp, "ram", "SpecifiedTaxRegistration")
        _sub(reg, "ram", "ID", p.vat_id).set("schemeID", "VA")
    elif p.tax_number:
        reg = _sub(tp, "ram", "SpecifiedTaxRegistration")
        _sub(reg, "ram", "ID", p.tax_number).set("schemeID", "FC")


# --- main builder ---------------------------------------------------------


def build_cii_xml(inv: EInvoice, *, strict: bool = True) -> bytes:
    """Render an :class:`EInvoice` as EN 16931 CII XML bytes.

    Args:
        inv: the fully populated invoice.
        strict: when True (default) raise :class:`EInvoiceError` if the
            invoice fails :func:`validate`. Set False to emit a best-effort
            document for inspection/debugging.
    """
    profile = get_profile(inv.profile)
    if profile is None or profile.syntax != "cii":
        raise EInvoiceError(
            f"profile {inv.profile!r} is not a CII profile "
            f"(supported CII: {', '.join(n for n, p in PROFILES.items() if p.syntax == 'cii')})"
        )
    if strict:
        problems = validate(inv)
        if problems:
            raise EInvoiceError("; ".join(problems))

    root = ET.Element(_q("rsm", "CrossIndustryInvoice"))

    # 1. ExchangedDocumentContext (guideline / profile)
    ctx = _sub(root, "rsm", "ExchangedDocumentContext")
    gp = _sub(ctx, "ram", "GuidelineSpecifiedDocumentContextParameter")
    _sub(gp, "ram", "ID", profile.guideline)

    # 2. ExchangedDocument (header)
    doc = _sub(root, "rsm", "ExchangedDocument")
    _sub(doc, "ram", "ID", inv.invoice_number)
    _sub(doc, "ram", "TypeCode", inv.type_code)
    _date_el(doc, "ram", "IssueDateTime", inv.issue_date)
    if inv.note:
        note = _sub(doc, "ram", "IncludedNote")
        _sub(note, "ram", "Content", inv.note)

    # 3. SupplyChainTradeTransaction
    tx = _sub(root, "rsm", "SupplyChainTradeTransaction")

    # 3a. Lines
    for line in inv.lines:
        li = _sub(tx, "ram", "IncludedSupplyChainTradeLineItem")
        doc_line = _sub(li, "ram", "AssociatedDocumentLineDocument")
        _sub(doc_line, "ram", "LineID", line.line_id)
        prod = _sub(li, "ram", "SpecifiedTradeProduct")
        _sub(prod, "ram", "Name", line.name or "-")
        agr = _sub(li, "ram", "SpecifiedLineTradeAgreement")
        price = _sub(agr, "ram", "NetPriceProductTradePrice")
        _sub(price, "ram", "ChargeAmount", _price(line.net_unit_price))
        dlv = _sub(li, "ram", "SpecifiedLineTradeDelivery")
        _sub(dlv, "ram", "BilledQuantity", _qty(line.quantity)).set("unitCode", unece_unit(line.unit))
        stl = _sub(li, "ram", "SpecifiedLineTradeSettlement")
        tax = _sub(stl, "ram", "ApplicableTradeTax")
        _sub(tax, "ram", "TypeCode", "VAT")
        _sub(tax, "ram", "CategoryCode", line.vat_category)
        _sub(tax, "ram", "RateApplicablePercent", _pct(line.vat_rate))
        summ = _sub(stl, "ram", "SpecifiedTradeSettlementLineMonetarySummation")
        _sub(summ, "ram", "LineTotalAmount", _money(line.line_net_amount, inv.currency))

    # 3b. Header agreement (buyer ref, seller, buyer, order ref)
    agr = _sub(tx, "ram", "ApplicableHeaderTradeAgreement")
    if inv.buyer_reference:
        _sub(agr, "ram", "BuyerReference", inv.buyer_reference)
    _party(agr, "SellerTradeParty", inv.seller)
    _party(agr, "BuyerTradeParty", inv.buyer)
    if inv.order_reference:
        ref = _sub(agr, "ram", "BuyerOrderReferencedDocument")
        _sub(ref, "ram", "IssuerAssignedID", inv.order_reference)

    # 3c. Header delivery (mandatory container, may be empty)
    _sub(tx, "ram", "ApplicableHeaderTradeDelivery")

    # 3d. Header settlement (currency, tax breakdown, payment, totals)
    stl = _sub(tx, "ram", "ApplicableHeaderTradeSettlement")
    _sub(stl, "ram", "InvoiceCurrencyCode", inv.currency)
    if inv.tax_currency:
        _sub(stl, "ram", "TaxCurrencyCode", inv.tax_currency)

    if inv.payment_means_code:
        pm = _sub(stl, "ram", "SpecifiedTradeSettlementPaymentMeans")
        _sub(pm, "ram", "TypeCode", inv.payment_means_code)
        # BG-17 credit transfer: the account the buyer pays into (BT-84/BT-85),
        # without which a credit transfer instruction fails BR-61.
        if inv.payee_iban:
            acct = _sub(pm, "ram", "PayeePartyCreditAccountID")
            # BT-84 is an account identifier, not an IBAN, and D16B gives it two
            # homes accordingly. Writing a domestic account number into IBANID
            # would produce a document that passes every check we can run here
            # and is refused by the receiving platform, which is the worst shape
            # a defect can take: the sender is told nothing. The element order
            # is fixed by CreditorFinancialAccountType, IBANID then AccountName
            # then ProprietaryID, so the domestic branch writes last.
            if is_iban(inv.payee_iban):
                _sub(acct, "ram", "IBANID", inv.payee_iban)
                if inv.payee_account_name:
                    _sub(acct, "ram", "AccountName", inv.payee_account_name)
            else:
                if inv.payee_account_name:
                    _sub(acct, "ram", "AccountName", inv.payee_account_name)
                _sub(acct, "ram", "ProprietaryID", inv.payee_iban)
        # BT-86 has only the one home in D16B, so a national bank code has
        # nowhere truthful to go and is left out rather than misdeclared. The
        # term is optional and no rule requires it; the account above is what
        # BR-61 asks for, and the PDF still shows the code to the person paying.
        if inv.payee_bic and is_bic(inv.payee_bic):
            inst = _sub(pm, "ram", "PayeeSpecifiedCreditorFinancialInstitution")
            _sub(inst, "ram", "BICID", inv.payee_bic)

    for grp in inv.tax_subtotals:
        tax = _sub(stl, "ram", "ApplicableTradeTax")
        _sub(tax, "ram", "CalculatedAmount", _money(grp.tax_amount, inv.currency))
        _sub(tax, "ram", "TypeCode", "VAT")
        # BT-120 / BT-121, in the D16B element order: ExemptionReason precedes
        # BasisAmount and ExemptionReasonCode follows CategoryCode.
        if grp.exemption_reason:
            _sub(tax, "ram", "ExemptionReason", grp.exemption_reason)
        _sub(tax, "ram", "BasisAmount", _money(grp.basis, inv.currency))
        _sub(tax, "ram", "CategoryCode", grp.category)
        if grp.exemption_reason_code:
            _sub(tax, "ram", "ExemptionReasonCode", grp.exemption_reason_code)
        _sub(tax, "ram", "RateApplicablePercent", _pct(grp.rate))

    if inv.due_date or inv.payment_terms:
        terms = _sub(stl, "ram", "SpecifiedTradePaymentTerms")
        if inv.payment_terms:
            _sub(terms, "ram", "Description", inv.payment_terms)
        if inv.due_date:
            _date_el(terms, "ram", "DueDateDateTime", inv.due_date)

    summ = _sub(stl, "ram", "SpecifiedTradeSettlementHeaderMonetarySummation")
    _sub(summ, "ram", "LineTotalAmount", _money(inv.line_total, inv.currency))
    _sub(summ, "ram", "TaxBasisTotalAmount", _money(inv.tax_basis_total, inv.currency))
    _sub(summ, "ram", "TaxTotalAmount", _money(inv.tax_total, inv.currency)).set("currencyID", inv.currency)
    # BT-111: when VAT is accounted for in another currency (BT-6), the VAT
    # total has to be stated in that currency too, each amount carrying its own
    # currencyID. BR-53 makes this mandatory, never inferred from a rate.
    if inv.tax_currency and inv.tax_total_in_tax_currency is not None:
        _sub(summ, "ram", "TaxTotalAmount", _money(inv.tax_total_in_tax_currency, inv.tax_currency)).set(
            "currencyID", inv.tax_currency
        )
    _sub(summ, "ram", "GrandTotalAmount", _money(inv.grand_total, inv.currency))
    if inv.prepaid_amount:
        _sub(summ, "ram", "TotalPrepaidAmount", _money(inv.prepaid_amount, inv.currency))
    _sub(summ, "ram", "DuePayableAmount", _money(inv.due_payable, inv.currency))

    ET.indent(root, space="  ")
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")
