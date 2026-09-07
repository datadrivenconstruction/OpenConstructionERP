# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The readable half of a hybrid invoice printed no street, the XML half did.

A Factur-X / ZUGFeRD file is one invoice in two representations: a page a person
reads and a CII document the receiver's software reads. They have to say the
same thing. The page carried the party name, the post code and the city; BT-35
and BT-50, the street, went into the XML and never onto the page. That is not a
formatting preference and needs no external authority to be a defect: two
representations of one document, shipped together, stated different addresses.

The instrument is the extracted page text, because the claim is about what a
person sees. Both directions are asserted: the street reaches the page when the
party answers it, and the locality line is untouched when it does not, which is
what proves the block is driven by the field rather than carrying a string that
was always going to be there.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from pypdf import PdfReader

from app.modules.einvoice.cii import EInvoice, EInvoiceLine, Party, TaxSubtotal, build_cii_xml
from app.modules.einvoice.pdf_embed import _readable_pdf, party_address_lines

STREET = "Hauptstrasse 17"
POSTCODE = "60327"
CITY = "Frankfurt am Main"


def invoice(*, street: str | None) -> EInvoice:
    """One EN 16931 invoice whose parties differ only in whether they name a street."""
    party = Party(
        name="Bau GmbH",
        country_code="DE",
        vat_id="DE812345678",
        line1=street,
        postcode=POSTCODE,
        city=CITY,
    )
    buyer = Party(
        name="Stadt Beispiel",
        country_code="DE",
        line1=street,
        postcode="60308",
        city=CITY,
    )
    return EInvoice(
        profile="zugferd",
        invoice_number="AR-2026-014",
        issue_date="2026-04-15",
        currency="EUR",
        seller=party,
        buyer=buyer,
        lines=[
            EInvoiceLine(
                line_id="1",
                name="Rohbau",
                quantity=Decimal("1"),
                unit="C62",
                net_unit_price=Decimal("1000.00"),
                line_net_amount=Decimal("1000.00"),
                vat_rate=Decimal("19"),
            )
        ],
        tax_subtotals=[
            TaxSubtotal(category="S", rate=Decimal("19"), basis=Decimal("1000.00"), tax_amount=Decimal("190.00"))
        ],
        line_total=Decimal("1000.00"),
        tax_basis_total=Decimal("1000.00"),
        tax_total=Decimal("190.00"),
        grand_total=Decimal("1190.00"),
        due_payable=Decimal("1190.00"),
    )


def page_text(inv: EInvoice) -> str:
    """The text a person reads off the rendered page."""
    return PdfReader(io.BytesIO(_readable_pdf(inv, "en"))).pages[0].extract_text()


def test_the_street_the_xml_carries_is_on_the_page_as_well() -> None:
    """The defect itself, asserted on both representations of one document.

    Read the CII first. If the XML did not carry the street either then the
    party never had one and a page without it would be honest, so the page
    assertion below would be passing for the wrong reason.
    """
    inv = invoice(street=STREET)

    xml = build_cii_xml(inv, strict=False).decode("utf-8")
    assert f"<ram:LineOne>{STREET}</ram:LineOne>" in xml, "the XML half never carried the street, nothing to compare"

    text = page_text(inv)
    assert STREET in text, "the street is in the embedded XML and not on the page a person reads"


def test_a_party_with_no_street_still_prints_the_locality_line_it_always_printed() -> None:
    """The other direction, and the reason no issued invoice moved.

    Every invoice this product has issued carries a post code and a city and no
    street, because the field was never on the page to be filled. Those pages
    must come out as they were: the block is a consequence of what the party
    answered, not of a line that is always drawn.
    """
    text = page_text(invoice(street=None))

    assert f"{POSTCODE} {CITY}" in text
    assert STREET not in text


def test_the_block_is_the_fields_in_order_and_nothing_else() -> None:
    """The line list itself, so a regression names the shape rather than a PDF.

    Asserted on the exact list. A membership check would pass on a block that
    had gained a blank line, duplicated the city, or reversed the two.
    """
    party = Party(name="Bau GmbH", country_code="DE", line1=STREET, postcode=POSTCODE, city=CITY)

    assert party_address_lines(party) == [STREET, f"{POSTCODE} {CITY}"]


@pytest.mark.parametrize(
    ("line1", "postcode", "city", "expected"),
    [
        (None, POSTCODE, CITY, [f"{POSTCODE} {CITY}"]),
        (STREET, None, CITY, [STREET, CITY]),
        (STREET, POSTCODE, None, [STREET, POSTCODE]),
        ("   ", "  ", "  ", []),
        (None, None, None, []),
    ],
)
def test_an_unanswered_field_produces_no_line_rather_than_an_empty_one(
    line1: str | None, postcode: str | None, city: str | None, expected: list[str]
) -> None:
    """A blank drawn at a party's own offset reads as an address with a hole in it.

    Whitespace counts as unanswered. The contacts directory stores addresses as
    a free-form dict and a key present with a space in it is a shape that
    reaches here, so a truthiness test alone would draw the space.
    """
    party = Party(name="Bau GmbH", country_code="DE", line1=line1, postcode=postcode, city=city)

    assert party_address_lines(party) == expected
