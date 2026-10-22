# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SUNAT UBL 2.1 invoice writer: the electronic factura of Peru, unsigned.

SUNAT's electronic invoice is OASIS UBL 2.1 with its own customisation
(``CustomizationID`` 2.0): the seller and buyer are identified by RUC under
scheme 6, the tax scheme is IGV (code 1000), every line states its tax
affectation, and a construction invoice carries the detraction as a payment
term. Like the Turkish writer next to it this one produces an UNSIGNED document
for an OSE or PSE (the authorised provider that signs and sends it to SUNAT);
the signature container is written as the same placeholder.

It reuses the platform's EN 16931 invoice model (:class:`EInvoice`) for the
parties, lines and totals, and the UBL namespaces and serialiser of the UBL
writer; only the SUNAT layout and rules are written here.

**What was and was not checked.** The element order follows the UBL 2.1 schema.
The SUNAT code lists (affectation 10, detraction means 003, scheme 6, service
code 030) are from SUNAT's published invoice guide as remembered, and were not
validated against the current XSD or the schematron of an OSE. Treat the file as
a draft for the provider's validator, not as accepted by SUNAT.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from xml.etree import ElementTree as ET  # noqa: N817 - trusted, we build not parse

from app.modules.einvoice.cii import EInvoice, EInvoiceError, Party, _money, _price, _qty, unece_unit
from app.modules.einvoice.rules import FATAL, WARNING, RuleViolation
from app.modules.einvoice.ubl import CAC, CBC, INV, _amt, _iso_date, _tostring
from app.modules.einvoice.ubl_tr import EXT, UNSIGNED

__all__ = [
    "CONSTRUCTION_DETRACTION_CODE",
    "CONSTRUCTION_DETRACTION_PERCENT",
    "DETRACTION_THRESHOLD",
    "PeDetraction",
    "build_ubl_pe_xml",
    "check_pe",
    "detraction_amount",
    "ruc_is_valid",
]

UBL_VERSION = "2.1"
CUSTOMIZATION = "2.0"
#: Catalogue 06, identity document type: 6 is the RUC, 1 the DNI.
SCHEME_RUC = "6"
SCHEME_DNI = "1"
#: IGV, the VAT of Peru, in SUNAT's tax scheme list.
IGV_SCHEME_ID = "1000"
#: Catalogue 07, affectation of IGV: 10 is taxed, onerous operation.
AFFECTATION_TAXED = "10"
#: Catalogue 59, payment means: 003 is a deposit into the detraction account.
DETRACTION_MEANS = "003"
CONSTRUCTION_DETRACTION_CODE = "030"
CONSTRUCTION_DETRACTION_PERCENT = Decimal("4")
DETRACTION_THRESHOLD = Decimal("700")

_SERIES = re.compile(r"^[FB][A-Z0-9]{3}-\d{1,8}$")
_RUC_WEIGHTS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
_2P = Decimal("0.01")

ET.register_namespace("ext", EXT)
ET.register_namespace("oce", UNSIGNED)

_PREFIXES = {"cac": CAC, "cbc": CBC, "ext": EXT, "oce": UNSIGNED}


def _sub(parent: ET.Element, prefix: str, local: str, text: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, f"{{{_PREFIXES[prefix]}}}{local}")
    if text is not None:
        el.text = text
    return el


@dataclass(frozen=True)
class PeDetraction:
    """The detraction the invoice states: the service code, the rate and the account.

    Attributes:
        code: Catalogue 54 service code, 030 for construction contracts.
        percent: Rate as a percent of the invoice total.
        account: The seller's detraction account number at the Banco de la Nacion.
    """

    code: str = CONSTRUCTION_DETRACTION_CODE
    percent: Decimal = CONSTRUCTION_DETRACTION_PERCENT
    account: str = ""


def ruc_is_valid(ruc: str | None) -> bool:
    """Whether ``ruc`` is 11 digits with a correct check digit (modulus 11, weights 5432765432)."""
    text = (ruc or "").strip()
    if not re.fullmatch(r"\d{11}", text):
        return False
    total = sum(int(d) * w for d, w in zip(text[:10], _RUC_WEIGHTS, strict=True))
    return (11 - total % 11) % 10 == int(text[10])


def detraction_amount(grand_total: Decimal, percent: Decimal) -> Decimal:
    """The deposit: ``percent`` of the invoice total, rounded to whole soles (unconfirmed)."""
    return (grand_total * percent / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _ruc(party: Party) -> str:
    return (party.vat_id or party.legal_id or party.tax_number or "").strip()


def check_pe(inv: EInvoice, detraction: PeDetraction | None = None) -> list[RuleViolation]:
    """Findings that would stop an OSE from accepting the document, and advisories.

    Args:
        inv: The invoice model.
        detraction: The detraction block, ``None`` when the invoice carries none.

    Returns:
        The findings; fatal ones block :func:`build_ubl_pe_xml` in strict mode.
    """
    found: list[RuleViolation] = []

    def add(rule: str, severity: str, message: str, term: str = "") -> None:
        found.append(RuleViolation(rule, severity, message, term))

    if not ruc_is_valid(_ruc(inv.seller)):
        add("PE-01", FATAL, "The seller needs an 11-digit RUC with a valid check digit.", "BT-31")
    if inv.type_code == "380" and not ruc_is_valid(_ruc(inv.buyer)):
        add("PE-02", FATAL, "A factura needs the buyer's RUC; use a boleta for a buyer without one.", "BT-48")
    if not _SERIES.match(inv.invoice_number or ""):
        add("PE-03", FATAL, "The number must be a series and a correlative such as F001-00000123.", "BT-1")
    if inv.currency not in ("PEN", "USD"):
        add("PE-04", WARNING, f"SUNAT accepts PEN and USD in the common case, not {inv.currency}.", "BT-5")
    for group in inv.tax_subtotals:
        if group.category == "S" and group.rate != Decimal("18"):
            add("PE-05", WARNING, f"IGV is 18 percent, the document charges {group.rate}.", "BT-119")
    if detraction is not None:
        if not detraction.account.strip():
            add("PE-06", FATAL, "A detraction needs the seller's detraction account at the Banco de la Nacion.")
    elif inv.grand_total > DETRACTION_THRESHOLD and inv.currency == "PEN":
        add(
            "PE-07",
            WARNING,
            "A construction invoice above S/ 700 is subject to the detraction; state it or confirm it does not apply.",
        )
    return found


def _party(parent: ET.Element, wrapper: str, party: Party) -> None:
    wrap = _sub(parent, "cac", wrapper)
    node = _sub(wrap, "cac", "Party")
    ident = _sub(node, "cac", "PartyIdentification")
    scheme = SCHEME_RUC if len(_ruc(party)) == 11 else SCHEME_DNI
    _sub(ident, "cbc", "ID", _ruc(party)).set("schemeID", scheme)
    name = _sub(node, "cac", "PartyName")
    _sub(name, "cbc", "Name", party.name)
    legal = _sub(node, "cac", "PartyLegalEntity")
    _sub(legal, "cbc", "RegistrationName", party.name)
    addr = _sub(legal, "cac", "RegistrationAddress")
    if party.city:
        _sub(addr, "cbc", "CityName", party.city)
    if party.line1:
        line = _sub(addr, "cac", "AddressLine")
        _sub(line, "cbc", "Line", party.line1)
    country = _sub(addr, "cac", "Country")
    _sub(country, "cbc", "IdentificationCode", (party.country_code or "PE").upper())


def _igv_scheme(parent: ET.Element) -> None:
    scheme = _sub(parent, "cac", "TaxScheme")
    _sub(scheme, "cbc", "ID", IGV_SCHEME_ID)
    _sub(scheme, "cbc", "Name", "IGV")
    _sub(scheme, "cbc", "TaxTypeCode", "VAT")


def build_ubl_pe_xml(inv: EInvoice, detraction: PeDetraction | None = None, *, strict: bool = True) -> bytes:
    """Render an :class:`EInvoice` as an unsigned SUNAT UBL 2.1 factura.

    Args:
        inv: The invoice model, built with the plain UBL profile.
        detraction: The detraction block for a construction invoice, or ``None``.
        strict: Refuse the document when a fatal finding of :func:`check_pe` stands.

    Returns:
        The XML bytes.

    Raises:
        EInvoiceError: ``strict`` and a fatal finding, or a malformed date.
    """
    if strict:
        fatal = [v for v in check_pe(inv, detraction) if v.severity == FATAL]
        if fatal:
            raise EInvoiceError("; ".join(f"{v.rule_id}: {v.message}" for v in fatal))
    cur = inv.currency
    root = ET.Element(f"{{{INV}}}Invoice")

    ext = _sub(_sub(root, "ext", "UBLExtensions"), "ext", "UBLExtension")
    _sub(_sub(ext, "ext", "ExtensionContent"), "oce", "Unsigned")
    _sub(root, "cbc", "UBLVersionID", UBL_VERSION)
    _sub(root, "cbc", "CustomizationID", CUSTOMIZATION)
    _sub(root, "cbc", "ID", inv.invoice_number)
    _sub(root, "cbc", "IssueDate", _iso_date(inv.issue_date))
    if inv.due_date:
        _sub(root, "cbc", "DueDate", _iso_date(inv.due_date))
    code = _sub(root, "cbc", "InvoiceTypeCode", "01")
    code.set("listID", "0101")
    if inv.note:
        _sub(root, "cbc", "Note", inv.note)
    _sub(root, "cbc", "DocumentCurrencyCode", cur)
    _sub(root, "cbc", "LineCountNumeric", str(len(inv.lines)))
    if inv.order_reference:
        _sub(_sub(root, "cac", "OrderReference"), "cbc", "ID", inv.order_reference)

    sig = _sub(root, "cac", "Signature")
    _sub(sig, "cbc", "ID", "SignatureSP")
    signatory = _sub(sig, "cac", "SignatoryParty")
    _sub(_sub(signatory, "cac", "PartyIdentification"), "cbc", "ID", _ruc(inv.seller))
    _sub(_sub(signatory, "cac", "PartyName"), "cbc", "Name", inv.seller.name)
    ref = _sub(_sub(sig, "cac", "DigitalSignatureAttachment"), "cac", "ExternalReference")
    _sub(ref, "cbc", "URI", "#SignatureSP")

    _party(root, "AccountingSupplierParty", inv.seller)
    _party(root, "AccountingCustomerParty", inv.buyer)

    if detraction is not None:
        means = _sub(root, "cac", "PaymentMeans")
        _sub(means, "cbc", "ID", "Detraccion")
        _sub(means, "cbc", "PaymentMeansCode", DETRACTION_MEANS)
        _sub(_sub(means, "cac", "PayeeFinancialAccount"), "cbc", "ID", detraction.account.strip())
        terms = _sub(root, "cac", "PaymentTerms")
        _sub(terms, "cbc", "ID", "Detraccion")
        _sub(terms, "cbc", "PaymentMeansID", detraction.code)
        _sub(terms, "cbc", "PaymentPercent", str(detraction.percent.quantize(_2P)))
        _amt(terms, "Amount", _money(detraction_amount(inv.grand_total, detraction.percent), cur), cur)
    pay = _sub(root, "cac", "PaymentTerms")
    _sub(pay, "cbc", "ID", "FormaPago")
    _sub(pay, "cbc", "PaymentMeansID", "Credito" if inv.due_date else "Contado")

    total = _sub(root, "cac", "TaxTotal")
    _amt(total, "TaxAmount", _money(inv.tax_total, cur), cur)
    for group in inv.tax_subtotals:
        sub = _sub(total, "cac", "TaxSubtotal")
        _amt(sub, "TaxableAmount", _money(group.basis, cur), cur)
        _amt(sub, "TaxAmount", _money(group.tax_amount, cur), cur)
        _igv_scheme(_sub(sub, "cac", "TaxCategory"))

    lmt = _sub(root, "cac", "LegalMonetaryTotal")
    _amt(lmt, "LineExtensionAmount", _money(inv.line_total, cur), cur)
    _amt(lmt, "TaxInclusiveAmount", _money(inv.grand_total, cur), cur)
    if inv.prepaid_amount:
        _amt(lmt, "PrepaidAmount", _money(inv.prepaid_amount, cur), cur)
    _amt(lmt, "PayableAmount", _money(inv.due_payable, cur), cur)

    for line in inv.lines:
        node = _sub(root, "cac", "InvoiceLine")
        _sub(node, "cbc", "ID", line.line_id)
        _sub(node, "cbc", "InvoicedQuantity", _qty(line.quantity)).set("unitCode", unece_unit(line.unit))
        _amt(node, "LineExtensionAmount", _money(line.line_net_amount, cur), cur)
        gross = (line.net_unit_price * (1 + line.vat_rate / Decimal(100))).quantize(_2P, rounding=ROUND_HALF_UP)
        alt = _sub(_sub(node, "cac", "PricingReference"), "cac", "AlternativeConditionPrice")
        _amt(alt, "PriceAmount", _price(gross), cur)
        _sub(alt, "cbc", "PriceTypeCode", "01")
        line_tax = (line.line_net_amount * line.vat_rate / Decimal(100)).quantize(_2P, rounding=ROUND_HALF_UP)
        ltot = _sub(node, "cac", "TaxTotal")
        _amt(ltot, "TaxAmount", _money(line_tax, cur), cur)
        lsub = _sub(ltot, "cac", "TaxSubtotal")
        _amt(lsub, "TaxableAmount", _money(line.line_net_amount, cur), cur)
        _amt(lsub, "TaxAmount", _money(line_tax, cur), cur)
        cat = _sub(lsub, "cac", "TaxCategory")
        _sub(cat, "cbc", "Percent", str(line.vat_rate.quantize(_2P)))
        _sub(cat, "cbc", "TaxExemptionReasonCode", AFFECTATION_TAXED)
        _igv_scheme(cat)
        _sub(_sub(node, "cac", "Item"), "cbc", "Description", line.name or "-")
        _amt(_sub(node, "cac", "Price"), "PriceAmount", _price(line.net_unit_price), cur)

    ET.indent(root, space="  ")
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + _tostring(root, INV)
