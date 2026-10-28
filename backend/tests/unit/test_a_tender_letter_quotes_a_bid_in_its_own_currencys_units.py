"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A tender letter quotes an amount with the digits its currency has.

The award letter, the rejection notice and the award record all print money
through one renderer, ``pdf_documents._fmt_money``. It was handed the currency
code, printed that code next to the figure, and still quantised to a
``Decimal("0.01")`` literal, so a tender settled in forint went out quoting
fillér that left circulation in 1999 with the letters HUF beside them, and one
settled in Kuwaiti dinar went out a fils short of the bid it was quoting.

Tendering is where this matters most, because the module already knows bids
arrive in more than one currency: it counts the ones it had to leave out on
that ground, under ``off_currency_excluded``. And the rejection notice goes to
the bidder who lost, who is the reader most likely to check the number against
their own submission.

Two things are measured, because either alone would pass against code that is
still broken. The rendered strings are pinned by equality rather than
containment, since ``"1,234" in out`` is satisfied by ``"1,234.00"``, which is
the output being fixed. Then the documents themselves, because a helper reading
the registry proves nothing about the four places that call it.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pypdf
import pytest

from app.core.money import CURRENCIES, minor_units
from app.modules.tendering.pdf_documents import (
    _fmt_money,
    _record_fact_value,
    generate_award_letter_pdf,
    generate_award_record_pdf,
    generate_rejection_letter_pdf,
)

#: One amount with a different non-zero digit at every place the platform can
#: print, so rounding it to 0, 2 or 3 decimals gives three strings that differ
#: as strings. A rounder probe would read the same at every digit count and let
#: a currency-blind renderer pass the whole table.
PROBE = Decimal("1234567.891")


def _style_separators(code: str) -> tuple[str, str]:
    """The thousands and decimal separators this module uses for a code.

    Read back from the module's own documented styles rather than sliced out of
    a rendered string, so a renderer that dropped a separator entirely cannot
    quietly redefine what the sweep below is parsing.
    """
    if code == "EUR":
        return ".", ","
    if code == "CHF":
        return "'", "."
    return ",", "."


# ── the helper ────────────────────────────────────────────────────────────────


def test_the_probe_amount_can_tell_the_digit_counts_apart() -> None:
    """Without this the table below could be green and measuring nothing."""
    rendered = {places: str(round(PROBE, places)) for places in (0, 2, 3)}
    assert len(set(rendered.values())) == 3, f"the probe cannot distinguish digit counts: {rendered}"


def test_the_registry_still_carries_currencies_of_every_kind() -> None:
    """And a registry that had lost its 0 and 3 entries would do the same."""
    counts = {minor_units(code) for code in CURRENCIES}
    assert {0, 2, 3} <= counts, f"registry no longer spans the digit counts under test: {sorted(counts)}"


@pytest.mark.parametrize(
    ("currency", "expected"),
    [
        # No subunit at all. Two digits here are not a finer forint, they are a
        # pair of digits no payment can carry.
        ("HUF", "1,234,568 HUF"),
        ("IDR", "1,234,568 IDR"),
        ("JPY", "1,234,568 JPY"),
        # Two, which is what the old literal assumed, so these rows are the
        # control and have to come out byte-identical to the old renderer.
        # They also cover both of the module's own presentation styles.
        ("USD", "1,234,567.89 USD"),
        ("EUR", "1.234.567,89 EUR"),
        ("CHF", "1'234'567.89 CHF"),
        # Three. The Gulf and Tunisian dinars are subdivided into thousandths
        # and the third digit is a real fils a real bid carries.
        ("BHD", "1,234,567.891 BHD"),
        ("KWD", "1,234,567.891 KWD"),
        ("TND", "1,234,567.891 TND"),
    ],
)
def test_an_amount_is_written_with_the_digits_its_currency_has(currency: str, expected: str) -> None:
    assert _fmt_money(PROBE, currency) == expected


def test_a_currency_with_no_subunit_gets_no_separator_either() -> None:
    """A trailing "1,234," reads as a truncated number rather than a whole one."""
    written = _fmt_money(PROBE, "HUF")
    assert "." not in written, f"a forint was written with a decimal separator: {written!r}"
    assert written == "1,234,568 HUF"


def test_the_renderer_takes_its_digit_count_from_the_one_registry() -> None:
    """Every code in the registry, so a currency added tomorrow is covered.

    The pinned table above records the decision for a handful of codes; this
    one says the renderer holds no table of its own for any of the rest.
    """
    disagreements = {}
    for code in CURRENCIES:
        body = _fmt_money(PROBE, code).removesuffix(f" {code}")
        _, dec_sep = _style_separators(code)
        _, _, frac = body.partition(dec_sep)
        if len(frac) != minor_units(code):
            disagreements[code] = (body, minor_units(code))
    assert not disagreements, f"the renderer disagrees with the registry: {disagreements}"


@pytest.mark.parametrize("code", ["", "ZZZ", "zzz"])
def test_a_code_the_registry_does_not_carry_keeps_the_two_decimal_default(code: str) -> None:
    """Not a guess made here: it is the registry's own documented default.

    A fact assembled from a procedure can genuinely carry no currency, and the
    renderer must not invent one. It asks the registry and takes whatever the
    registry says about a code it does not know.
    """
    assert _fmt_money(PROBE, code).startswith("1,234,567.89")


# ── the documents ─────────────────────────────────────────────────────────────

#: Chosen so the two spellings differ in the integer part as well: half a forint
#: rounds up. An amount ending in .00 would print "250,000" either way and the
#: assertion would be satisfied by the code being replaced.
AMOUNT = "250000.50"
IN_FORINT = "250,001HUF"
IN_CENTS = "250,000.50"


def _text(data: bytes) -> str:
    """Extracted page text with all whitespace squashed out.

    reportlab is free to place the space between the figure and the code as
    positioning rather than as a space character, so both sides of every
    assertion are squashed the same way and the code is asserted to sit next to
    the number it belongs to.
    """
    reader = pypdf.PdfReader(io.BytesIO(data))
    return "".join("".join((page.extract_text() or "").split()) for page in reader.pages)


def _award() -> bytes:
    return generate_award_letter_pdf(
        package_name="Roofing works",
        package_ref="PKG-2026-0001",
        project_name="Riverside Gardens",
        company_name="Kreuzer Roofing",
        contact_email="tender@example.com",
        awarded_amount=AMOUNT,
        currency="HUF",
        awarded_at="2026-06-01T09:00:00+00:00",
    )


def _rejection() -> bytes:
    return generate_rejection_letter_pdf(
        package_name="Roofing works",
        package_ref="PKG-2026-0001",
        project_name="Riverside Gardens",
        company_name="Second Place Bau",
        contact_email="tender@example.com",
        bid_amount=AMOUNT,
        currency="HUF",
        winning_amount=AMOUNT,
        rejected_at="2026-06-01T09:00:00+00:00",
    )


def _record() -> bytes:
    return generate_award_record_pdf(
        record={
            "package_name": "Roofing works",
            "project_name": "Riverside Gardens",
            "stage": "awarded",
            "is_complete": True,
            "gaps": [],
            "sections": [
                {
                    "key": "bids_received",
                    "state": "recorded",
                    "facts": [{"key": "bid", "amount": AMOUNT, "currency": "HUF"}],
                }
            ],
        },
        package_ref="PKG-2026-0001",
    )


GENERATORS = {"award letter": _award, "rejection notice": _rejection, "award record": _record}


@pytest.mark.parametrize("document", sorted(GENERATORS))
def test_a_forint_tender_document_is_issued_without_the_subunit_it_has_not_got(document: str) -> None:
    text = _text(GENERATORS[document]())

    assert IN_FORINT in text, f"{document} does not carry {IN_FORINT!r}: {text!r}"
    assert IN_CENTS not in text, f"{document} still quotes a forint with cents: {text!r}"


def test_the_bidder_who_lost_is_shown_both_figures_in_the_same_units() -> None:
    """The rejection notice prints the bidder's own bid and the awarded sum.

    Two separate call sites, both reached from one generator, and the bidder
    reading it is the one most likely to compare them. If either kept the old
    literal the letter would set two figures side by side in different units.
    """
    text = _text(_rejection())
    assert text.count(IN_FORINT) == 2, f"expected both figures in whole forint: {text!r}"


def test_an_assembled_fact_without_a_currency_is_still_rendered() -> None:
    """The record's fact renderer passes a blank code straight through."""
    assert _record_fact_value({"key": "bid", "amount": AMOUNT}) == "250,000.50"
