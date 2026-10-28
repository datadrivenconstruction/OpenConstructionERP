"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the EN 16931 CII e-invoice builder (einvoice module).

Pure and DB-free: they exercise the builder and the finance-dict mapping the
same way the GAEB export tests pin ``build_gaeb_xml``.
"""

from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest

from app.modules.einvoice import (
    build_einvoice,
    problems_for,
    render_einvoice,
    validate,
)
from app.modules.einvoice.cii import RAM, RSM, UDT, EInvoiceError, unece_unit

NS = {"rsm": RSM, "ram": RAM, "udt": UDT}


def _invoice() -> dict:
    return {
        "invoice_number": "RE-2026-0007",
        "invoice_direction": "receivable",
        "invoice_date": "2026-07-05",
        "due_date": "2026-08-04",
        "currency_code": "EUR",
        "amount_subtotal": Decimal("1000.00"),
        "tax_amount": Decimal("190.00"),
        "retention_amount": Decimal("50.00"),
        "amount_total": Decimal("1140.00"),
        "notes": "Thank you for your business",
        "metadata": {
            "einvoice": {
                "seller": {
                    "name": "Bau GmbH",
                    "vat_id": "DE123456789",
                    "line1": "Baustrasse 1",
                    "postcode": "10115",
                    "city": "Berlin",
                    "country_code": "DE",
                    # BG-6, mandatory on the seller under XRechnung (BR-DE-2).
                    "contact_name": "Anke Reimann",
                    "contact_phone": "+49 30 1234560",
                    "contact_email": "rechnung@baugmbh.example",
                },
                "buyer": {
                    "name": "Stadt Beispiel",
                    "postcode": "12345",
                    "city": "Beispielstadt",
                    "country_code": "DE",
                },
                "buyer_reference": "04011000-1234512345-06",
            }
        },
    }


def _lines() -> list[dict]:
    return [
        {
            "description": "Concrete C30/37",
            "unit": "m3",
            "quantity": Decimal("40"),
            "unit_rate": Decimal("20"),
            "amount": Decimal("800.00"),
        },
        {
            "description": "Formwork",
            "unit": "m2",
            "quantity": Decimal("100"),
            "unit_rate": Decimal("2"),
            "amount": Decimal("200.00"),
        },
    ]


def _find(root: ET.Element, path: str) -> ET.Element:
    el = root.find(path, NS)
    assert el is not None, f"missing {path}"
    return el


def _text(root: ET.Element, path: str) -> str:
    return (_find(root, path).text or "").strip()


def test_unece_unit_mapping():
    assert unece_unit("m3") == "MTQ"
    assert unece_unit("m2") == "MTK"
    assert unece_unit("m") == "MTR"
    assert unece_unit("pcs") == "C62"
    assert unece_unit(None) == "C62"
    assert unece_unit("totally-unknown") == "C62"


def test_totals_reconcile_and_no_validation_problems():
    ei = build_einvoice(invoice=_invoice(), line_items=_lines(), profile="xrechnung")
    assert ei.line_total == Decimal("1000.00")
    assert ei.tax_basis_total == Decimal("1000.00")
    assert ei.tax_total == Decimal("190.00")
    assert ei.grand_total == Decimal("1190.00")
    assert ei.prepaid_amount == Decimal("50.00")
    assert ei.due_payable == Decimal("1140.00")
    assert validate(ei) == []


@pytest.mark.parametrize(
    ("profile", "guideline"),
    [
        ("en16931", "urn:cen.eu:en16931:2017"),
        ("zugferd", "urn:cen.eu:en16931:2017"),
        ("facturx", "urn:cen.eu:en16931:2017"),
        (
            "xrechnung",
            "urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_3.0",
        ),
    ],
)
def test_guideline_per_profile(profile: str, guideline: str):
    _, media, xml = render_einvoice(invoice=_invoice(), line_items=_lines(), profile=profile)
    assert media == "application/xml"
    root = ET.fromstring(xml)
    got = _text(
        root,
        "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID",
    )
    assert got == guideline


def test_cii_structure_and_values():
    filename, _, xml = render_einvoice(invoice=_invoice(), line_items=_lines(), profile="xrechnung")
    assert filename == "einvoice_RE-2026-0007_xrechnung.xml"
    root = ET.fromstring(xml)

    assert root.tag == f"{{{RSM}}}CrossIndustryInvoice"
    assert _text(root, "rsm:ExchangedDocument/ram:ID") == "RE-2026-0007"
    assert _text(root, "rsm:ExchangedDocument/ram:TypeCode") == "380"
    issue = _find(root, "rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString")
    assert issue.text == "20260705"
    assert issue.attrib["format"] == "102"

    tx = "rsm:SupplyChainTradeTransaction"
    lines = root.findall(f"{tx}/ram:IncludedSupplyChainTradeLineItem", NS)
    assert len(lines) == 2
    # First line: quantity, unit code, net price, line total.
    bq = _find(
        root,
        f"{tx}/ram:IncludedSupplyChainTradeLineItem/ram:SpecifiedLineTradeDelivery/ram:BilledQuantity",
    )
    assert bq.attrib["unitCode"] == "MTQ"

    # Buyer reference (Leitweg-ID) present for XRechnung.
    assert _text(root, f"{tx}/ram:ApplicableHeaderTradeAgreement/ram:BuyerReference") == "04011000-1234512345-06"
    # Seller VAT registration with scheme VA.
    reg = _find(
        root,
        f"{tx}/ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID",
    )
    assert reg.text == "DE123456789"
    assert reg.attrib["schemeID"] == "VA"

    # Header settlement totals.
    summ = f"{tx}/ram:ApplicableHeaderTradeSettlement/ram:SpecifiedTradeSettlementHeaderMonetarySummation"
    assert _text(root, f"{summ}/ram:LineTotalAmount") == "1000.00"
    assert _text(root, f"{summ}/ram:TaxBasisTotalAmount") == "1000.00"
    tax_total = _find(root, f"{summ}/ram:TaxTotalAmount")
    assert tax_total.text == "190.00"
    assert tax_total.attrib["currencyID"] == "EUR"
    assert _text(root, f"{summ}/ram:GrandTotalAmount") == "1190.00"
    assert _text(root, f"{summ}/ram:TotalPrepaidAmount") == "50.00"
    assert _text(root, f"{summ}/ram:DuePayableAmount") == "1140.00"

    # VAT breakdown group.
    tax_grp = f"{tx}/ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax"
    assert _text(root, f"{tax_grp}/ram:RateApplicablePercent") == "19.00"
    assert _text(root, f"{tax_grp}/ram:CategoryCode") == "S"
    assert _text(root, f"{tax_grp}/ram:TypeCode") == "VAT"


def test_xrechnung_requires_buyer_reference():
    inv = _invoice()
    inv["metadata"]["einvoice"].pop("buyer_reference")
    problems = problems_for(invoice=inv, line_items=_lines(), profile="xrechnung")
    assert any("Leitweg" in p or "BT-10" in p for p in problems)
    with pytest.raises(EInvoiceError):
        render_einvoice(invoice=inv, line_items=_lines(), profile="xrechnung")
    # ...but the same invoice is fine under the plain EN 16931 / ZUGFeRD profile.
    assert problems_for(invoice=inv, line_items=_lines(), profile="zugferd") == []


def test_seller_without_tax_id_is_flagged():
    inv = _invoice()
    inv["metadata"]["einvoice"]["seller"].pop("vat_id")
    problems = problems_for(invoice=inv, line_items=_lines(), profile="zugferd")
    assert any("VAT id" in p or "tax number" in p for p in problems)


def test_zero_tax_uses_category_z():
    inv = _invoice()
    inv["amount_subtotal"] = Decimal("1000.00")
    inv["tax_amount"] = Decimal("0")
    inv["metadata"]["einvoice"].pop("buyer_reference", None)
    ei = build_einvoice(invoice=inv, line_items=_lines(), profile="zugferd")
    assert ei.tax_subtotals[0].category == "Z"
    assert ei.tax_subtotals[0].rate == Decimal("0")
    assert ei.grand_total == Decimal("1000.00")
    assert validate(ei) == []
