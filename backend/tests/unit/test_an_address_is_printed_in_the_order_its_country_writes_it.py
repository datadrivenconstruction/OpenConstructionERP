# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""One address order was printed for every country, and it was Europe's.

The invoice page joined the post code to the city in that order for every party
it has ever printed. That is right for the DACH countries and for the rest of
continental Europe, and wrong for the United States, the United Kingdom,
Australia, Singapore and Russia, and reversed for China and Japan, which write
an address from the largest unit down. The product ships ``peppol_aunz`` and
``peppol_sg`` profiles, so those are not hypothetical recipients.

What this gate holds:

- the exact lines each shape produces, one country per shape, asserted as a
  list rather than by membership, so a block that gained a line, lost one, or
  swapped two is red;
- one uncovered country, to pin what the fallback does and to keep it the
  continental shape rather than a neutral-looking one that would silently make
  France, Spain, Italy, the Netherlands and Norway wrong;
- that the cases exercise every shape the module implements, so emptying the
  table below fails instead of passing over nothing, and adding a shape without
  a case fails too;
- that the invoice page, not only the formatter, carries the result.

The population it covers is printed beside its verdict, because a green stripe
whose denominator is unstated cannot be told from a green stripe over two rows.

The Cyrillic and CJK strings below are address data, which is the one thing
they are allowed to be.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from pypdf import PdfReader

from app.core.provenance import Source
from app.core.validation.address import (
    _COUNTRY_RULES,
    _LOCALITY_SHAPES,
    DECLARED_FIELD_ORDER,
    POSTCODE_AFTER_CITY_AND_STATE,
    POSTCODE_BEFORE_CITY,
    POSTCODE_BEFORE_CITY_AND_STATE,
    POSTCODE_ON_ITS_OWN_LINE,
    format_address_lines,
    get_address_rules,
)
from app.modules.einvoice.cii import EInvoice, EInvoiceLine, Party, TaxSubtotal
from app.modules.einvoice.pdf_embed import _readable_pdf, party_address_lines
from app.modules.einvoice.profiles import PROFILES

#: One real address per country, and the lines a recipient there expects.
#:
#: Chosen so that each entry is a case somebody in that country would recognise
#: rather than a permutation of placeholders: a wrong order is only a defect
#: because a real recipient reads it as one.
CASES: dict[str, tuple[dict[str, str], list[str]]] = {
    # Post code before the city, on one line.
    "DE": (
        {"street": "Hauptstrasse 17", "postcode": "10115", "city": "Berlin"},
        ["Hauptstrasse 17", "10115 Berlin"],
    ),
    # Uncovered. France has no row and must still come out in the shape France
    # writes, which is what makes the fallback the continental one.
    "FR": (
        {"street": "55 Rue du Faubourg Saint-Honore", "postcode": "75008", "city": "Paris"},
        ["55 Rue du Faubourg Saint-Honore", "75008 Paris"],
    ),
    # City, region, post code, closing the line.
    "US": (
        {"street": "1600 Pennsylvania Ave NW", "city": "Washington", "state": "DC", "postcode": "20500"},
        ["1600 Pennsylvania Ave NW", "Washington, DC 20500"],
    ),
    "AU": (
        {"street": "111 Bourke Street", "city": "Melbourne", "state": "VIC", "postcode": "3000"},
        ["111 Bourke Street", "Melbourne, VIC 3000"],
    ),
    # Singapore has no region part, so the same shape yields two words.
    "SG": (
        {"street": "1 Marina Boulevard", "city": "Singapore", "postcode": "018989"},
        ["1 Marina Boulevard", "Singapore 018989"],
    ),
    # Post code on a line of its own, under the city.
    "GB": (
        {"street": "10 Downing Street", "city": "London", "postcode": "SW1A 2AA"},
        ["10 Downing Street", "London", "SW1A 2AA"],
    ),
    "RU": (
        {"street": "ул. Тверская, 13", "city": "Москва", "postcode": "125009"},
        ["ул. Тверская, 13", "Москва", "125009"],
    ),
    # CEP first, state abbreviation last, the way Correios prints it.
    "BR": (
        {"street": "Av. Paulista 1578", "postcode": "01310-200", "city": "Sao Paulo", "state": "SP"},
        ["Av. Paulista 1578", "01310-200 Sao Paulo - SP"],
    ),
    # Largest unit first, one part per line, the exact reverse of the above.
    "JP": (
        {"postcode": "100-8994", "state": "東京都", "city": "千代田区", "street": "丸の内2-7-2"},
        ["100-8994", "東京都", "千代田区", "丸の内2-7-2"],
    ),
    # China opens with the country where Japan closes with it, which is why the
    # reversal is read off each country's own row and not hard-coded once.
    "CN": (
        {
            "country": "中国",
            "postcode": "100031",
            "state": "北京市",
            "city": "西城区",
            "street": "复兴门内大街55号",
        },
        ["中国", "100031", "北京市", "西城区", "复兴门内大街55号"],
    ),
}

#: Profile regions this product ships that have no address row, and are served
#: correctly anyway because they write the post code before the city, which is
#: what the fallback does. Named rather than left implicit: a profile added for
#: a country that is in neither this set nor the rules table is a country whose
#: address nobody looked at, and the test below is red until somebody does.
SERVED_BY_THE_CONTINENTAL_FALLBACK = {"FR", "NL", "NO"}


def profile_region_codes() -> set[str]:
    """The two-letter country codes the shipped e-invoice profiles name.

    ``region`` carries "DE/FR" and "AU/NZ" as well as "EU" and "international",
    so it is split and the non-country tokens dropped.
    """
    codes: set[str] = set()
    for profile in PROFILES.values():
        for raw in profile.region.split("/"):
            token = raw.strip().upper()
            if len(token) == 2 and token != "EU":
                codes.add(token)
    return codes


@pytest.mark.parametrize("country", sorted(CASES))
def test_an_address_comes_out_in_the_lines_its_country_writes(country: str) -> None:
    """The verdict. Exact list equality, in both directions at once.

    A membership check would pass on a block that had gained an empty line,
    duplicated the city or put the post code on the wrong side, which is the
    whole defect.
    """
    address, expected = CASES[country]

    lines, jurisdiction = format_address_lines(address, country)

    assert lines == expected
    assert jurisdiction.requested == country


def test_the_population_behind_that_verdict() -> None:
    """The denominator, printed, and red when the table above goes empty.

    A gate over an empty fixture passes every assertion it makes. This one
    compares the shapes the cases reach against the shapes the module has, so
    removing a case is red, and adding a shape nobody wrote a case for is red
    too. The counts go to stdout so a reader of the run sees what the green
    covers rather than having to trust the file name.
    """
    shapes_reached = {get_address_rules(cc)["locality_shape"] for cc in CASES}
    declared = {cc for cc in CASES if get_address_rules(cc)["jurisdiction"].answered}

    print(
        f"address rows: {len(_COUNTRY_RULES)} countries "
        f"({len(_COUNTRY_RULES) - 1} distinct, GB and UK being one) | "
        f"shapes implemented: {len(_LOCALITY_SHAPES)} | "
        f"cases: {len(CASES)} covering {len(shapes_reached)} shapes | "
        f"of those cases {len(declared)} declared, {len(CASES) - len(declared)} on the fallback | "
        f"document renderers routed through the formatter: 1 (the hybrid invoice page)"
    )

    assert CASES, "the case table is empty, so every other assertion in this file is over nothing"
    assert shapes_reached == set(_LOCALITY_SHAPES), (
        f"cases reach {sorted(shapes_reached)} but the module implements {sorted(_LOCALITY_SHAPES)}"
    )
    assert declared, "no case exercises a country with its own row"
    assert set(CASES) - declared, "no case exercises the fallback, so nothing pins what an uncovered country prints"


def test_the_five_shapes_are_five_different_answers() -> None:
    """Two shapes that render the same thing are one shape with two names.

    Asserted on one address put through every shape, because a table whose rows
    happen to agree is a table that cannot be regressed into: a change that
    collapsed two of them would leave every other test here green.
    """
    address = {"street": "1 Main Street", "postcode": "12345", "city": "Springfield", "state": "IL"}
    country_per_shape = {
        POSTCODE_BEFORE_CITY: "DE",
        POSTCODE_AFTER_CITY_AND_STATE: "US",
        POSTCODE_ON_ITS_OWN_LINE: "GB",
        POSTCODE_BEFORE_CITY_AND_STATE: "BR",
        DECLARED_FIELD_ORDER: "JP",
    }

    assert set(country_per_shape) == set(_LOCALITY_SHAPES)

    rendered = {shape: tuple(format_address_lines(address, cc)[0]) for shape, cc in country_per_shape.items()}
    assert len(set(rendered.values())) == len(rendered), f"two shapes render identically: {rendered}"


def test_the_shape_alone_never_says_the_country_was_consulted() -> None:
    """France and Germany print the same shape and only one of them was asked.

    The module's whole design is that a stand-in must not read as knowledge.
    The renderer got a second table, so it gets the same obligation: a caller
    telling a user "this is how your country writes it" has to read the
    provenance, because the lines cannot tell it.
    """
    german_lines, german = format_address_lines(CASES["DE"][0], "DE")
    french_lines, french = format_address_lines(CASES["FR"][0], "FR")

    assert german.source is Source.DECLARED
    assert french.source is Source.FALLBACK
    assert len(german_lines) == len(french_lines)
    assert get_address_rules("DE")["locality_shape"] == get_address_rules("FR")["locality_shape"]


def test_an_unanswered_part_leaves_no_line_and_no_stray_separator() -> None:
    """A US party with no region must not print "Boston, 02108".

    ``Party`` has no field for BT-39 / BT-54, so this is the state every
    American and Australian invoice this product renders is actually in. The
    comma belongs between two parts and has to disappear with either of them.
    """
    lines, _ = format_address_lines({"street": "1 Main Street", "city": "Boston", "postcode": "02108"}, "US")
    assert lines == ["1 Main Street", "Boston 02108"]

    lines, _ = format_address_lines({"city": "Boston", "state": "MA"}, "US")
    assert lines == ["Boston, MA"]

    lines, _ = format_address_lines({"street": " ", "city": "  ", "postcode": "\t"}, "US")
    assert lines == []


def test_a_new_profile_region_cannot_ship_before_its_address_is_classified() -> None:
    """The gate that fails on the next country rather than on this one.

    Every country a shipped profile names is either a row here or an explicit
    member of the set that the continental fallback happens to serve. A profile
    added for somewhere else is a country whose address shape nobody decided,
    and it goes red here instead of going out on an invoice.
    """
    codes = profile_region_codes()
    declared = {cc for cc in codes if get_address_rules(cc)["jurisdiction"].answered}
    unclassified = codes - declared - SERVED_BY_THE_CONTINENTAL_FALLBACK

    print(
        f"e-invoice profiles: {len(PROFILES)} | country codes named by them: {len(codes)} | "
        f"with an address row: {len(declared)} {sorted(declared)} | "
        f"on the fallback by decision: {sorted(SERVED_BY_THE_CONTINENTAL_FALLBACK & codes)}"
    )

    assert codes, "no profile named a country, so this gate is measuring nothing"
    assert not unclassified, f"shipped profiles reach {sorted(unclassified)} and nobody chose an address shape for them"


# ── The page, not only the formatter ─────────────────────────────────────────


def invoice_for(party_country: str, address: dict[str, str]) -> EInvoice:
    """One invoice whose two parties sit in *party_country*."""
    party = Party(
        name="Bau GmbH",
        country_code=party_country,
        line1=address.get("street"),
        postcode=address.get("postcode"),
        city=address.get("city"),
    )
    return EInvoice(
        profile="zugferd",
        invoice_number="AR-2026-014",
        issue_date="2026-04-15",
        currency="EUR",
        seller=party,
        buyer=party,
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


@pytest.mark.parametrize(
    ("country", "printed", "not_printed"),
    [
        ("DE", "10115 Berlin", "Berlin 10115"),
        ("US", "Washington 20500", "20500 Washington"),
        ("GB", "SW1A 2AA", None),
    ],
)
def test_the_invoice_page_carries_the_country_order_and_not_the_other_one(
    country: str, printed: str, not_printed: str | None
) -> None:
    """The formatter reaching the document, asserted on the drawn page.

    A unit test of the formatter would stay green if the renderer stopped
    calling it, which is exactly the regression this change is at risk of. The
    negative half matters as much: the old order must be gone, not merely
    joined by the new one somewhere else on the page.

    The US party prints without its region because :class:`Party` has no field
    for it, so this asserts the post code sitting after the city, which is the
    half of the fix the party model does not block.
    """
    address, _ = CASES[country]
    page = PdfReader(io.BytesIO(_readable_pdf(invoice_for(country, address), "en"))).pages[0].extract_text()

    assert printed in page
    if not_printed is not None:
        assert not_printed not in page


def test_the_page_and_the_formatter_do_not_get_to_disagree() -> None:
    """Whatever the formatter says for a party is what the party block prints.

    Held across every case rather than the three above, so a country whose
    shape the page cannot draw is found here rather than by its recipient.
    """
    for country, (address, _) in CASES.items():
        party = Party(
            name="Bau GmbH",
            country_code=country,
            line1=address.get("street"),
            postcode=address.get("postcode"),
            city=address.get("city"),
        )
        expected, _ = format_address_lines(
            {"street": party.line1, "postcode": party.postcode, "city": party.city},
            country,
        )
        assert party_address_lines(party) == expected, country
