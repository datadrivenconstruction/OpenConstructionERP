"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the UBL / Peppol BIS Billing 3.0 e-invoice writer.

Proves the same EN 16931 invoice renders as valid UBL for worldwide use
(Peppol reaches the EU, UK, Australia, New Zealand, Singapore and more), not
just the DACH CII formats.
"""

from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest

from app.modules.einvoice import (
    EInvoiceError,
    problems_for,
    render_einvoice,
)
from app.modules.einvoice.profiles import PEPPOL_CUSTOMIZATION, PEPPOL_PROFILE
from app.modules.einvoice.ubl import CAC, CBC, INV

NS = {"inv": INV, "cac": CAC, "cbc": CBC}


def _invoice() -> dict:
    return {
        "invoice_number": "INV-2026-0042",
        "invoice_direction": "receivable",
        "invoice_date": "2026-07-05",
        "due_date": "2026-08-04",
        "currency_code": "EUR",
        "amount_subtotal": Decimal("1000.00"),
        "tax_amount": Decimal("200.00"),
        "retention_amount": Decimal("0"),
        "amount_total": Decimal("1200.00"),
        "notes": None,
        "metadata": {
            "einvoice": {
                "vat_rate": "20",
                "seller": {
                    "name": "Global Build Ltd",
                    "vat_id": "IE1234567FA",
                    "city": "Dublin",
                    "postcode": "D01",
                    "country_code": "IE",
                    "electronic_address": "0088:1234567890123",
                    "electronic_address_scheme": "0088",
                },
                "buyer": {
                    "name": "City Works",
                    "city": "Cork",
                    "postcode": "T12",
                    "country_code": "IE",
                },
                "buyer_reference": "PO-99887",
            }
        },
    }


def _lines() -> list[dict]:
    return [
        {
            "description": "Excavation",
            "unit": "m3",
            "quantity": Decimal("50"),
            "unit_rate": Decimal("12"),
            "amount": Decimal("600.00"),
        },
        {
            "description": "Backfill",
            "unit": "m3",
            "quantity": Decimal("40"),
            "unit_rate": Decimal("10"),
            "amount": Decimal("400.00"),
        },
    ]


def _find(root: ET.Element, path: str) -> ET.Element:
    el = root.find(path, NS)
    assert el is not None, f"missing {path}"
    return el


def _text(root: ET.Element, path: str) -> str:
    return (_find(root, path).text or "").strip()


def test_peppol_ubl_structure_and_totals():
    filename, media, xml = render_einvoice(invoice=_invoice(), line_items=_lines(), profile="peppol")
    assert media == "application/xml"
    assert filename == "einvoice_INV-2026-0042_peppol.xml"
    root = ET.fromstring(xml)

    assert root.tag == f"{{{INV}}}Invoice"
    assert _text(root, "cbc:CustomizationID") == PEPPOL_CUSTOMIZATION
    assert _text(root, "cbc:ProfileID") == PEPPOL_PROFILE
    assert _text(root, "cbc:ID") == "INV-2026-0042"
    assert _text(root, "cbc:IssueDate") == "2026-07-05"
    assert _text(root, "cbc:InvoiceTypeCode") == "380"
    assert _text(root, "cbc:DocumentCurrencyCode") == "EUR"
    assert _text(root, "cbc:BuyerReference") == "PO-99887"

    # Seller VAT + endpoint.
    supplier = "cac:AccountingSupplierParty/cac:Party"
    assert _text(root, f"{supplier}/cac:PartyName/cbc:Name") == "Global Build Ltd"
    assert _text(root, f"{supplier}/cac:PartyTaxScheme/cbc:CompanyID") == "IE1234567FA"
    assert _text(root, f"{supplier}/cac:PostalAddress/cac:Country/cbc:IdentificationCode") == "IE"

    # Two lines, currency on every amount.
    lines = root.findall("cac:InvoiceLine", NS)
    assert len(lines) == 2
    qty = _find(root, "cac:InvoiceLine/cbc:InvoicedQuantity")
    assert qty.attrib["unitCode"] == "MTQ"

    tax_amt = _find(root, "cac:TaxTotal/cbc:TaxAmount")
    assert tax_amt.text == "200.00"
    assert tax_amt.attrib["currencyID"] == "EUR"
    assert _text(root, "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:Percent") == "20.00"

    lmt = "cac:LegalMonetaryTotal"
    assert _text(root, f"{lmt}/cbc:LineExtensionAmount") == "1000.00"
    assert _text(root, f"{lmt}/cbc:TaxExclusiveAmount") == "1000.00"
    assert _text(root, f"{lmt}/cbc:TaxInclusiveAmount") == "1200.00"
    payable = _find(root, f"{lmt}/cbc:PayableAmount")
    assert payable.text == "1200.00"
    assert payable.attrib["currencyID"] == "EUR"


def test_plain_ubl_has_no_peppol_profile_id():
    _, _, xml = render_einvoice(invoice=_invoice(), line_items=_lines(), profile="ubl")
    root = ET.fromstring(xml)
    assert _text(root, "cbc:CustomizationID") == "urn:cen.eu:en16931:2017"
    assert root.find("cbc:ProfileID", NS) is None


def test_peppol_accepts_order_reference_instead_of_buyer_reference():
    inv = _invoice()
    inv["metadata"]["einvoice"].pop("buyer_reference")
    # No BT-10 and no BT-13 -> Peppol rejects.
    problems = problems_for(invoice=inv, line_items=_lines(), profile="peppol")
    assert any("BT-10" in p or "BT-13" in p or "Buyer reference" in p for p in problems)
    with pytest.raises(EInvoiceError):
        render_einvoice(invoice=inv, line_items=_lines(), profile="peppol")
    # Adding an order reference (BT-13) satisfies the Peppol rule.
    inv["metadata"]["einvoice"]["order_reference"] = "ORD-555"
    assert problems_for(invoice=inv, line_items=_lines(), profile="peppol") == []
    _, _, xml = render_einvoice(invoice=inv, line_items=_lines(), profile="peppol")
    root = ET.fromstring(xml)
    assert _text(root, "cac:OrderReference/cbc:ID") == "ORD-555"


def test_non_eu_currency_and_country_render():
    inv = _invoice()
    inv["currency_code"] = "AUD"
    inv["metadata"]["einvoice"]["seller"]["country_code"] = "AU"
    inv["metadata"]["einvoice"]["buyer"]["country_code"] = "AU"
    _, _, xml = render_einvoice(invoice=inv, line_items=_lines(), profile="peppol")
    root = ET.fromstring(xml)
    assert _text(root, "cbc:DocumentCurrencyCode") == "AUD"
    payable = _find(root, "cac:LegalMonetaryTotal/cbc:PayableAmount")
    assert payable.attrib["currencyID"] == "AUD"
