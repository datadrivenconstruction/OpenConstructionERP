"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for credit notes (BT-3 type code 381).

A credit note is the same EN 16931 model as an invoice but a different
document. In CII it is only the TypeCode; in UBL it is a whole different root
document (CreditNote instead of Invoice) with CreditedQuantity on the lines.
Sample data is deliberately non-German to keep the library international.
"""

from decimal import Decimal
from xml.etree import ElementTree as ET

from app.modules.einvoice import build_einvoice, render_einvoice
from app.modules.einvoice.cii import RAM, RSM, UDT
from app.modules.einvoice.ubl import CAC, CBC, CN, INV, is_credit_note

CII_NS = {"rsm": RSM, "ram": RAM, "udt": UDT}
UBL_NS = {"inv": INV, "cn": CN, "cac": CAC, "cbc": CBC}


def _credit_invoice(**extra: object) -> dict:
    meta_ei = {
        "vat_rate": "21",
        "seller": {
            "name": "Iberia Construccion SL",
            "vat_id": "ESB12345678",
            "city": "Madrid",
            "postcode": "28001",
            "country_code": "ES",
            "electronic_address": "0088:9501101020345",
            "electronic_address_scheme": "0088",
        },
        "buyer": {
            "name": "Obras Municipales",
            "city": "Sevilla",
            "postcode": "41001",
            "country_code": "ES",
        },
        "buyer_reference": "PO-CN-7788",
    }
    meta_ei.update(extra)
    return {
        "invoice_number": "NC-2026-0003",
        "invoice_date": "2026-07-05",
        "currency_code": "EUR",
        "amount_subtotal": Decimal("500.00"),
        "tax_amount": Decimal("105.00"),
        "metadata": {"einvoice": meta_ei},
    }


def _lines() -> list[dict]:
    return [
        {
            "description": "Returned tiles",
            "unit": "m2",
            "quantity": Decimal("25"),
            "unit_rate": Decimal("20"),
            "amount": Decimal("500.00"),
        }
    ]


def _text(root: ET.Element, path: str, ns: dict) -> str:
    el = root.find(path, ns)
    assert el is not None, f"missing {path}"
    return (el.text or "").strip()


def test_type_code_from_explicit_metadata():
    ei = build_einvoice(invoice=_credit_invoice(type_code="381"), line_items=_lines(), profile="peppol")
    assert ei.type_code == "381"


def test_type_code_from_credit_flag():
    ei = build_einvoice(invoice=_credit_invoice(credit_note=True), line_items=_lines(), profile="peppol")
    assert ei.type_code == "381"


def test_type_code_defaults_to_invoice():
    ei = build_einvoice(invoice=_credit_invoice(), line_items=_lines(), profile="peppol")
    assert ei.type_code == "380"


def test_is_credit_note_helper():
    assert is_credit_note("381") is True
    assert is_credit_note("380") is False
    assert is_credit_note(None) is False
    assert is_credit_note(" 381 ") is True


def test_cii_credit_note_sets_type_code_381():
    inv = _credit_invoice(type_code="381")
    filename, media, xml = render_einvoice(invoice=inv, line_items=_lines(), profile="zugferd")
    assert media == "application/xml"
    root = ET.fromstring(xml)
    # In CII a credit note is only the TypeCode; the document shape is unchanged.
    assert root.tag == f"{{{RSM}}}CrossIndustryInvoice"
    assert _text(root, "rsm:ExchangedDocument/ram:TypeCode", CII_NS) == "381"


def test_ubl_credit_note_is_a_creditnote_document():
    inv = _credit_invoice(type_code="381")
    filename, media, xml = render_einvoice(invoice=inv, line_items=_lines(), profile="peppol")
    assert media == "application/xml"
    root = ET.fromstring(xml)

    # Different root document in the CreditNote namespace.
    assert root.tag == f"{{{CN}}}CreditNote"
    # Type code lives in CreditNoteTypeCode, not InvoiceTypeCode.
    assert _text(root, "cbc:CreditNoteTypeCode", UBL_NS) == "381"
    assert root.find("cbc:InvoiceTypeCode", UBL_NS) is None

    # Lines are CreditNoteLine with CreditedQuantity, not InvoiceLine.
    lines = root.findall("cac:CreditNoteLine", UBL_NS)
    assert len(lines) == 1
    assert root.find("cac:InvoiceLine", UBL_NS) is None
    qty = root.find("cac:CreditNoteLine/cbc:CreditedQuantity", UBL_NS)
    assert qty is not None
    assert qty.attrib["unitCode"] == "MTK"
    assert root.find("cac:CreditNoteLine/cbc:InvoicedQuantity", UBL_NS) is None

    # Same EN 16931 totals as an invoice.
    assert _text(root, "cbc:CustomizationID", UBL_NS).startswith("urn:cen.eu:en16931:2017")
    assert _text(root, "cac:LegalMonetaryTotal/cbc:PayableAmount", UBL_NS) == "605.00"


def test_ubl_invoice_still_renders_after_credit_note():
    # A credit note temporarily changes the default namespace; prove the very
    # next invoice render is unaffected.
    render_einvoice(invoice=_credit_invoice(type_code="381"), line_items=_lines(), profile="peppol")
    _, _, xml = render_einvoice(invoice=_credit_invoice(), line_items=_lines(), profile="peppol")
    root = ET.fromstring(xml)
    assert root.tag == f"{{{INV}}}Invoice"
    assert _text(root, "cbc:InvoiceTypeCode", UBL_NS) == "380"
