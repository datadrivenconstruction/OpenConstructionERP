# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""EN 16931 UBL 2.1 invoice writer (Peppol BIS Billing 3.0 and plain UBL).

The international counterpart to the CII writer. UBL is the syntax used by the
Peppol network, which reaches well beyond Germany: the whole EU, plus the UK,
Australia, New Zealand, Singapore, and more. One EN 16931 invoice model, two
syntaxes (CII and UBL); this module renders the UBL side.

It is the exact inverse of ``supplier_catalogs.peppol`` (the UBL *parser*),
sharing the same UBL namespaces so import and export stay symmetric. Pure
stdlib ``xml.etree``, money kept as ``Decimal``, no new dependency.
"""

from __future__ import annotations

import threading
from xml.etree import ElementTree as ET  # noqa: N817 - trusted, we build not parse

from app.modules.einvoice.cii import (
    EInvoice,
    EInvoiceError,
    Party,
    _delivery_address,
    _money,
    _pct,
    _price,
    _qty,
    unece_unit,
    validate,
)
from app.modules.einvoice.profiles import PROFILES, get_profile

# UBL 2.1 namespaces (same URIs as the peppol parser). An EN 16931 invoice and
# an EN 16931 credit note are two different UBL root documents that share the
# same CommonAggregate (cac) and CommonBasic (cbc) component namespaces.
INV = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CN = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

# The shared component prefixes plus the invoice root as the default namespace.
# ElementTree can bind only one URI to the empty prefix at a time, so the credit
# note root (CreditNote-2) is swapped in as the default only while its own
# document is serialised (see :func:`_tostring`), under a lock so a concurrent
# invoice render is never affected.
_NS = {"cac": CAC, "cbc": CBC}
for _p, _u in _NS.items():
    ET.register_namespace(_p, _u)
ET.register_namespace("", INV)

_serialize_lock = threading.Lock()


def _tostring(root: ET.Element, doc_ns: str) -> bytes:
    """Serialise ``root`` with ``doc_ns`` as the default (unprefixed) namespace."""
    with _serialize_lock:
        ET.register_namespace("", doc_ns)
        try:
            return ET.tostring(root, encoding="utf-8")
        finally:
            # Restore the invoice root as the default for the next caller.
            ET.register_namespace("", INV)


# UN/CEFACT document type codes (BT-3) that must be rendered as a UBL CreditNote
# document rather than an Invoice document. 381 is the standard credit note.
_CREDIT_NOTE_TYPE_CODES = frozenset({"381"})


def is_credit_note(type_code: str | None) -> bool:
    """True when the given BT-3 type code must render as a UBL CreditNote."""
    return (type_code or "").strip() in _CREDIT_NOTE_TYPE_CODES


def _c(prefix: str, local: str) -> str:
    return f"{{{_NS[prefix]}}}{local}"


def _sub(parent: ET.Element, prefix: str, local: str, text: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, _c(prefix, local))
    if text is not None:
        el.text = text
    return el


def _amt(parent: ET.Element, local: str, value: str, currency: str) -> ET.Element:
    el = _sub(parent, "cbc", local, value)
    el.set("currencyID", currency)
    return el


def _iso_date(iso: str) -> str:
    d = (iso or "")[:10]
    parts = d.split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise EInvoiceError(f"invalid date {iso!r} (need YYYY-MM-DD)")
    return d


def _party(parent: ET.Element, wrapper_local: str, p: Party) -> None:
    wrap = _sub(parent, "cac", wrapper_local)
    party = _sub(wrap, "cac", "Party")
    if p.electronic_address:
        ep = _sub(party, "cbc", "EndpointID", p.electronic_address)
        if p.contact_id_scheme:
            ep.set("schemeID", p.contact_id_scheme)
    pn = _sub(party, "cac", "PartyName")
    _sub(pn, "cbc", "Name", p.name)
    addr = _sub(party, "cac", "PostalAddress")
    if p.line1:
        _sub(addr, "cbc", "StreetName", p.line1)
    if p.city:
        _sub(addr, "cbc", "CityName", p.city)
    if p.postcode:
        _sub(addr, "cbc", "PostalZone", p.postcode)
    # BT-40 / BT-55, and the wrapper goes with it: an empty cac:Country reads as
    # a malformed address rather than as an address with no country, and a
    # substituted country would be a false statement either way.
    if p.country_code:
        country = _sub(addr, "cac", "Country")
        _sub(country, "cbc", "IdentificationCode", p.country_code.upper())
    if p.vat_id:
        pts = _sub(party, "cac", "PartyTaxScheme")
        _sub(pts, "cbc", "CompanyID", p.vat_id)
        scheme = _sub(pts, "cac", "TaxScheme")
        _sub(scheme, "cbc", "ID", "VAT")
    legal = _sub(party, "cac", "PartyLegalEntity")
    _sub(legal, "cbc", "RegistrationName", p.name)
    if p.legal_id:
        _sub(legal, "cbc", "CompanyID", p.legal_id)
    # BG-6, the UBL spelling of the group the CII writer calls
    # DefinedTradeContact: BT-41 name, BT-42 telephone, BT-43 email.
    if p.contact_name or p.contact_phone or p.contact_email:
        contact = _sub(party, "cac", "Contact")
        if p.contact_name:
            _sub(contact, "cbc", "Name", p.contact_name)
        if p.contact_phone:
            _sub(contact, "cbc", "Telephone", p.contact_phone)
        if p.contact_email:
            _sub(contact, "cbc", "ElectronicMail", p.contact_email)


def build_ubl_xml(inv: EInvoice, *, strict: bool = True) -> bytes:
    """Render an :class:`EInvoice` as EN 16931 UBL (Peppol BIS) XML bytes.

    Branches on the document type code (BT-3): 380 renders a UBL Invoice, 381
    renders a UBL CreditNote (a different root document, with
    ``cbc:CreditNoteTypeCode`` and ``cbc:CreditedQuantity`` on the lines). Both
    share the same EN 16931 semantics and validate the same way.
    """
    profile = get_profile(inv.profile)
    if profile is None or profile.syntax != "ubl":
        raise EInvoiceError(
            f"profile {inv.profile!r} is not a UBL profile "
            f"(supported UBL: {', '.join(n for n, p in PROFILES.items() if p.syntax == 'ubl')})"
        )
    if strict:
        problems = validate(inv)
        if problems:
            raise EInvoiceError("; ".join(problems))

    credit = is_credit_note(inv.type_code)
    doc_ns = CN if credit else INV
    root_local = "CreditNote" if credit else "Invoice"
    type_code_tag = "CreditNoteTypeCode" if credit else "InvoiceTypeCode"
    line_wrapper = "CreditNoteLine" if credit else "InvoiceLine"
    qty_tag = "CreditedQuantity" if credit else "InvoicedQuantity"

    cur = inv.currency
    root = ET.Element(f"{{{doc_ns}}}{root_local}")

    _sub(root, "cbc", "CustomizationID", profile.guideline)
    if profile.profile_id:
        _sub(root, "cbc", "ProfileID", profile.profile_id)
    _sub(root, "cbc", "ID", inv.invoice_number)
    _sub(root, "cbc", "IssueDate", _iso_date(inv.issue_date))
    # A UBL CreditNote has no document-level DueDate; only the Invoice does.
    if inv.due_date and not credit:
        _sub(root, "cbc", "DueDate", _iso_date(inv.due_date))
    _sub(root, "cbc", type_code_tag, inv.type_code)
    if inv.note:
        _sub(root, "cbc", "Note", inv.note)
    _sub(root, "cbc", "DocumentCurrencyCode", cur)
    if inv.buyer_reference:
        _sub(root, "cbc", "BuyerReference", inv.buyer_reference)
    if inv.order_reference:
        oref = _sub(root, "cac", "OrderReference")
        _sub(oref, "cbc", "ID", inv.order_reference)
    # BT-11. A UBL CreditNote has no ProjectReference element; it is left off there.
    if inv.project_reference and not credit:
        pref = _sub(root, "cac", "ProjectReference")
        _sub(pref, "cbc", "ID", inv.project_reference)

    _party(root, "AccountingSupplierParty", inv.seller)
    _party(root, "AccountingCustomerParty", inv.buyer)

    site = _delivery_address(inv)
    if site:
        loc = _sub(_sub(root, "cac", "Delivery"), "cac", "DeliveryLocation")
        addr = _sub(loc, "cac", "Address")
        for key, tag in (("line1", "StreetName"), ("city", "CityName"), ("postcode", "PostalZone")):
            if site.get(key):
                _sub(addr, "cbc", tag, site[key])
        if site.get("subdivision"):
            _sub(addr, "cbc", "CountrySubentity", site["subdivision"])
        country = _sub(addr, "cac", "Country")
        _sub(country, "cbc", "IdentificationCode", site["country_code"])

    if inv.payment_means_code:
        pm = _sub(root, "cac", "PaymentMeans")
        _sub(pm, "cbc", "PaymentMeansCode", inv.payment_means_code)
        # BG-17 credit transfer: BT-84 is the account to pay into, and BR-61
        # makes it mandatory whenever the means code claims a credit transfer.
        if inv.payee_iban:
            acct = _sub(pm, "cac", "PayeeFinancialAccount")
            _sub(acct, "cbc", "ID", inv.payee_iban)
            if inv.payee_account_name:
                _sub(acct, "cbc", "Name", inv.payee_account_name)
            if inv.payee_bic:
                branch = _sub(acct, "cac", "FinancialInstitutionBranch")
                _sub(branch, "cbc", "ID", inv.payee_bic)
    if inv.payment_terms:
        pt = _sub(root, "cac", "PaymentTerms")
        _sub(pt, "cbc", "Note", inv.payment_terms)

    # Tax total + subtotals.
    tt = _sub(root, "cac", "TaxTotal")
    _amt(tt, "TaxAmount", _money(inv.tax_total, cur), cur)
    # BT-111: VAT accounted for in another currency travels as its own TaxTotal,
    # so neither amount can be read against the wrong currency.
    if inv.tax_currency and inv.tax_total_in_tax_currency is not None:
        tt_tax_cur = _sub(root, "cac", "TaxTotal")
        _amt(tt_tax_cur, "TaxAmount", _money(inv.tax_total_in_tax_currency, inv.tax_currency), inv.tax_currency)
    for grp in inv.tax_subtotals:
        sub = _sub(tt, "cac", "TaxSubtotal")
        _amt(sub, "TaxableAmount", _money(grp.basis, cur), cur)
        _amt(sub, "TaxAmount", _money(grp.tax_amount, cur), cur)
        cat = _sub(sub, "cac", "TaxCategory")
        _sub(cat, "cbc", "ID", grp.category)
        _sub(cat, "cbc", "Percent", _pct(grp.rate))
        # BT-121 / BT-120, in the UBL 2.1 element order: the code precedes the
        # reason text, and both precede the TaxScheme.
        if grp.exemption_reason_code:
            _sub(cat, "cbc", "TaxExemptionReasonCode", grp.exemption_reason_code)
        if grp.exemption_reason:
            _sub(cat, "cbc", "TaxExemptionReason", grp.exemption_reason)
        scheme = _sub(cat, "cac", "TaxScheme")
        _sub(scheme, "cbc", "ID", "VAT")

    # Monetary totals.
    lmt = _sub(root, "cac", "LegalMonetaryTotal")
    _amt(lmt, "LineExtensionAmount", _money(inv.line_total, cur), cur)
    _amt(lmt, "TaxExclusiveAmount", _money(inv.tax_basis_total, cur), cur)
    _amt(lmt, "TaxInclusiveAmount", _money(inv.grand_total, cur), cur)
    if inv.prepaid_amount:
        _amt(lmt, "PrepaidAmount", _money(inv.prepaid_amount, cur), cur)
    _amt(lmt, "PayableAmount", _money(inv.due_payable, cur), cur)

    # Lines (InvoiceLine / InvoicedQuantity, or CreditNoteLine / CreditedQuantity).
    for line in inv.lines:
        il = _sub(root, "cac", line_wrapper)
        _sub(il, "cbc", "ID", line.line_id)
        _sub(il, "cbc", qty_tag, _qty(line.quantity)).set("unitCode", unece_unit(line.unit))
        _amt(il, "LineExtensionAmount", _money(line.line_net_amount, cur), cur)
        item = _sub(il, "cac", "Item")
        _sub(item, "cbc", "Name", line.name or "-")
        cat = _sub(item, "cac", "ClassifiedTaxCategory")
        _sub(cat, "cbc", "ID", line.vat_category)
        _sub(cat, "cbc", "Percent", _pct(line.vat_rate))
        scheme = _sub(cat, "cac", "TaxScheme")
        _sub(scheme, "cbc", "ID", "VAT")
        price = _sub(il, "cac", "Price")
        _amt(price, "PriceAmount", _price(line.net_unit_price), cur)

    ET.indent(root, space="  ")
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + _tostring(root, doc_ns)
