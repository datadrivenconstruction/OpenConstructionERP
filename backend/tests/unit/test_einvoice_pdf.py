"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the Factur-X / ZUGFeRD hybrid PDF builder."""

import io
import xml.etree.ElementTree as ET
from decimal import Decimal

import pytest
from pypdf import PdfReader

from app.modules.einvoice import build_einvoice
from app.modules.einvoice.cii import EInvoiceError, build_cii_xml
from app.modules.einvoice.pdf_embed import build_facturx_pdf


def _invoice() -> dict:
    return {
        "invoice_number": "RE-2026-0100",
        "invoice_direction": "receivable",
        "invoice_date": "2026-07-05",
        "due_date": "2026-08-04",
        "currency_code": "EUR",
        "amount_subtotal": Decimal("1000.00"),
        "tax_amount": Decimal("190.00"),
        "retention_amount": Decimal("0"),
        "amount_total": Decimal("1190.00"),
        "notes": None,
        "metadata": {
            "einvoice": {
                "seller": {
                    "name": "Bau GmbH",
                    "vat_id": "DE123456789",
                    "city": "Berlin",
                    "postcode": "10115",
                    "country_code": "DE",
                },
                "buyer": {"name": "Stadt Beispiel", "city": "Cork", "country_code": "DE"},
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


def test_hybrid_pdf_embeds_the_cii_xml():
    ei = build_einvoice(invoice=_invoice(), line_items=_lines(), profile="zugferd")
    pdf = build_facturx_pdf(ei)

    # A real PDF.
    assert pdf[:5] == b"%PDF-"

    reader = PdfReader(io.BytesIO(pdf))
    # The CII XML is embedded under the Factur-X attachment name.
    assert "factur-x.xml" in reader.attachments
    embedded = reader.attachments["factur-x.xml"][0]
    assert embedded == build_cii_xml(ei)
    # It parses and carries the invoice number.
    assert b"RE-2026-0100" in embedded

    # Associated-file relationship at the catalog level.
    root = reader.trailer["/Root"]
    assert "/AF" in root
    # XMP metadata declares the Factur-X conformance.
    meta = root["/Metadata"].get_data()
    assert b"ConformanceLevel" in meta
    assert b"factur-x.xml" in meta


def test_the_attachment_is_related_as_an_alternative_rendering():
    """The one property a lenient reader will not notice is missing.

    Factur-X 1.0 and ZUGFeRD 2.1 require /AFRelationship /Alternative, because
    the XML is the same invoice in another form. Under /Data a receiver that
    picks its attachment by relationship finds no invoice at all, while the
    file still opens, still holds a correctly named factur-x.xml and still
    passes every check that looks only at the name or the bytes.
    """
    ei = build_einvoice(invoice=_invoice(), line_items=_lines(), profile="zugferd")
    reader = PdfReader(io.BytesIO(build_facturx_pdf(ei)))

    associated = reader.trailer["/Root"]["/AF"]
    assert len(associated) == 1
    spec = associated[0].get_object()
    assert spec["/AFRelationship"] == "/Alternative"
    assert spec["/F"] == "factur-x.xml"
    assert spec["/UF"] == "factur-x.xml"


def test_the_embedded_invoice_reads_back_as_the_invoice_that_was_sent():
    """Read the hybrid the way a receiver does: open the PDF, parse the XML.

    Comparing the attachment against ``build_cii_xml`` only proves the same
    function ran twice. Parsing it and reading the business terms out proves
    the document a receiver opens carries the figures the sender approved.
    """
    ei = build_einvoice(invoice=_invoice(), line_items=_lines(), profile="zugferd")
    reader = PdfReader(io.BytesIO(build_facturx_pdf(ei)))
    root = ET.fromstring(reader.attachments["factur-x.xml"][0])

    ram = "{urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100}"
    rsm = "{urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100}"

    # Anchored on ExchangedDocument, because ExchangedDocumentContext carries a
    # ram:ID of its own holding the specification URN, and a loose .//ram:ID
    # would read that one and still look like it found the invoice number.
    number = root.find(f"{rsm}ExchangedDocument/{ram}ID")
    payable = root.find(f".//{ram}SpecifiedTradeSettlementHeaderMonetarySummation/{ram}GrandTotalAmount")

    assert number is not None and number.text == "RE-2026-0100"
    assert payable is not None and Decimal(payable.text or "0") == ei.grand_total


def test_hybrid_pdf_rejects_ubl_profiles():
    ei = build_einvoice(invoice=_invoice(), line_items=_lines(), profile="peppol")
    with pytest.raises(EInvoiceError):
        build_facturx_pdf(ei)
