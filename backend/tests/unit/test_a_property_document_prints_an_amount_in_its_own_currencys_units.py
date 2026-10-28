"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A property document writes an amount with the digits its currency has.

Every contract, receipt and certificate the property module issues goes through
one renderer, ``document_templates._format_money``. It took a locale and no
currency at all, and quantised to a ``Decimal("0.01")`` literal, so a forint
contract was issued carrying fillér that left circulation in 1999 and a Kuwaiti
dinar receipt was issued a fils short of what the payment actually settled.
Both are wrong in a document a buyer signs and a regulator reads, and neither
raises anything.

Two things are measured, because either alone would pass against code that is
still broken.

The rendered strings are pinned by equality and not by containment. A
containment assertion is exactly the shape this defect survives: ``"1,234" in
out`` is satisfied by ``"1,234.00"``, which is the output being fixed. The
table spans a zero-decimal currency, a two-decimal one and a three-decimal one
for the same reason - a table of two-decimal currencies would be green against
a renderer that had never heard of a currency at all, since two is what it
already assumed.

Then the documents themselves. The helper reading the registry proves nothing
about the ten places that call it, and a call site that still passes no
currency is a ``TypeError`` only because the argument was made required; had it
been given a default, every one of them would have kept printing cents while
this file stayed green. So each generator that prints money renders a real PDF
in forint and the extracted text is asked for the whole amount.
"""

from __future__ import annotations

import io
from decimal import Decimal
from types import SimpleNamespace

import pypdf
import pytest

from app.core.money import CURRENCIES, minor_units
from app.modules.property_dev.document_templates import (
    _format_money,
    _separators_for_locale,
    render_escrow_release_authorization_pdf,
    render_payment_receipt_pdf,
    render_refund_authorization_pdf,
    render_reservation_receipt_pdf,
    render_sales_contract_pdf,
    render_tenant_lease_agreement_pdf,
)

#: One amount with a different non-zero digit at every place the platform can
#: print, so rounding it to 0, 2 or 3 decimals gives three strings that differ
#: as strings. A rounder probe would read the same at every digit count and let
#: a currency-blind renderer pass the whole table.
PROBE = Decimal("1234567.891")


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
    ("currency", "locale", "expected"),
    [
        # No subunit at all. Two digits here are not a finer forint, they are a
        # pair of digits no payment can carry.
        ("HUF", "en", "1,234,568"),
        ("HUF", "de", "1.234.568"),
        ("IDR", "en", "1,234,568"),
        # Russian groups with a non-breaking space, written as an escape
        # here so this file carries no invisible character of its own.
        ("JPY", "ru", "1 234 568"),
        # Two, which is what the old literal assumed, so these rows are the
        # control: they have to come out byte-identical to the old renderer.
        ("EUR", "en", "1,234,567.89"),
        ("EUR", "de", "1.234.567,89"),
        ("USD", "en", "1,234,567.89"),
        ("GBP", "en", "1,234,567.89"),
        # Three. The Gulf and Tunisian dinars are subdivided into thousandths
        # and the third digit is a real fils a real payment carries.
        ("BHD", "en", "1,234,567.891"),
        ("KWD", "de", "1.234.567,891"),
        ("TND", "en", "1,234,567.891"),
    ],
)
def test_an_amount_is_written_with_the_digits_its_currency_has(currency: str, locale: str, expected: str) -> None:
    assert _format_money(PROBE, locale, currency) == expected


@pytest.mark.parametrize("locale", ["en", "de", "ru", "fr"])
def test_a_currency_with_no_subunit_gets_no_separator_either(locale: str) -> None:
    """A trailing "1,234," reads as a truncated number rather than a whole one.

    The old renderer appended ``or '00'`` after the decimal separator, so
    removing only the two digits would have left the separator dangling in
    every locale that writes one.
    """
    thou_sep, dec_sep = _separators_for_locale(locale)
    written = _format_money(PROBE, locale, "HUF")

    assert dec_sep not in written, f"a forint was written with a decimal separator: {written!r}"
    assert written.replace(thou_sep, "") == "1234568", f"a forint lost or gained a digit: {written!r}"


def test_the_renderer_takes_its_digit_count_from_the_one_registry() -> None:
    """Every code in the registry, so a currency added tomorrow is covered.

    This is the drift assertion. The pinned table above records the decision
    for a handful of codes; this one says the renderer holds no table of its
    own for any of the rest.
    """
    disagreements = {}
    for code in CURRENCIES:
        _, _, frac = _format_money(PROBE, "en", code).partition(".")
        if len(frac) != minor_units(code):
            disagreements[code] = (frac, minor_units(code))
    assert not disagreements, f"the renderer disagrees with the registry: {disagreements}"


@pytest.mark.parametrize("code", ["", None, "ZZZ", "zzz"])
def test_a_code_the_registry_does_not_carry_keeps_the_two_decimal_default(code: str | None) -> None:
    """Not a guess made here: it is ``minor_units``' own documented default.

    A property record can genuinely carry no currency, and the renderer must
    not invent one. It asks the registry and takes whatever the registry says
    about a code it does not know.
    """
    assert _format_money(PROBE, "en", code) == "1,234,567.89"


def test_a_missing_amount_still_renders_nothing() -> None:
    """Unchanged, and asserted so the currency argument cannot have moved it."""
    assert _format_money(None, "en", "HUF") == ""


# ── the documents ─────────────────────────────────────────────────────────────

#: Chosen so that the two spellings differ in the integer part as well: half a
#: forint rounds up. An amount ending in .00 would print "250,000" either way
#: and the assertion would be satisfied by the code being replaced.
AMOUNT = Decimal("250000.50")
IN_FORINT = "250,001"
IN_CENTS = "250,000.50"


def _development() -> SimpleNamespace:
    return SimpleNamespace(
        id="dev-1",
        name="Riverside Gardens",
        code="DEV-1",
        metadata_={"regulator": "NONE"},
    )


def _plot(currency: str = "HUF") -> SimpleNamespace:
    return SimpleNamespace(
        id="plot-1",
        plot_number="P-101",
        area_m2=Decimal("78.50"),
        currency=currency,
        metadata_={},
    )


def _reservation() -> SimpleNamespace:
    return SimpleNamespace(
        id="res-1",
        reservation_number="RES-2026-0001",
        deposit_amount=AMOUNT,
        currency="HUF",
        expires_at="2026-06-15",
        cooling_off_until="2026-06-15",
        cooling_off_days=14,
        status="active",
    )


def _contract(currency: str = "HUF") -> SimpleNamespace:
    return SimpleNamespace(
        id="spa-1",
        contract_number="SPA-2026-0001",
        total_value=AMOUNT,
        currency=currency,
        status="draft",
        place="Budapest",
        signing_date="2026-06-01",
        total_price_breakdown={"base": str(AMOUNT)},
        metadata_={},
    )


def _instalment() -> SimpleNamespace:
    return SimpleNamespace(
        id="ins-1",
        sequence=1,
        milestone_label="Foundation",
        milestone_event="foundation_complete",
        due_date="2026-09-01",
        amount=AMOUNT,
        amount_paid=AMOUNT,
        paid_at="2026-09-05",
    )


def _lease() -> SimpleNamespace:
    return SimpleNamespace(
        id="lea-1",
        lease_number="LEA-2026-0001",
        monthly_rent=AMOUNT,
        security_deposit=AMOUNT,
        currency="HUF",
        start_date="2026-06-01",
        end_date="2027-05-31",
        term_months=12,
        status="draft",
    )


def _person(name: str = "Buyer One") -> SimpleNamespace:
    return SimpleNamespace(full_name=name, email="one@example.com")


def _party() -> SimpleNamespace:
    return SimpleNamespace(
        buyer_id="b-1",
        party_role="primary",
        ownership_pct=Decimal("100"),
        full_name="Buyer One",
        email="one@example.com",
    )


def _page_text(data: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(data))
    return "".join("".join((page.extract_text() or "").split()) for page in reader.pages)


#: Every generator that prints money, and the field it prints. Between them
#: they exercise all ten call sites the renderer has.
GENERATORS = {
    "reservation receipt": lambda: render_reservation_receipt_pdf(
        _reservation(), _plot(), _development(), [_person()], locale="en"
    ),
    "sales contract": lambda: render_sales_contract_pdf(
        _contract(),
        SimpleNamespace(currency="HUF"),
        [_instalment()],
        [_party()],
        _plot(),
        _development(),
        locale="en",
    ),
    "payment receipt": lambda: render_payment_receipt_pdf(
        _instalment(),
        _contract(),
        "bank_transfer",
        "WIRE-0001",
        locale="en",
        plot=_plot(),
        development=_development(),
    ),
    "tenant lease": lambda: render_tenant_lease_agreement_pdf(
        _lease(), _plot(), _development(), [_person("Tenant One")], locale="en"
    ),
    "escrow release": lambda: render_escrow_release_authorization_pdf(
        _contract(), _plot(), _development(), "ESC-0001", AMOUNT, "Foundation complete", locale="en"
    ),
    "refund": lambda: render_refund_authorization_pdf(
        _contract(), _plot(), _development(), AMOUNT, "Contract cancelled", "bank_transfer", locale="en"
    ),
}


@pytest.mark.parametrize("document", sorted(GENERATORS))
def test_a_forint_document_is_issued_without_the_subunit_it_has_not_got(document: str) -> None:
    text = _page_text(GENERATORS[document]())

    assert IN_FORINT in text, f"{document} does not carry {IN_FORINT!r}: {text!r}"
    assert IN_CENTS not in text, f"{document} still writes a forint with cents: {text!r}"


def test_an_instalment_is_written_in_the_currency_printed_beside_it() -> None:
    """The instalments table prints an amount and a currency code in one row.

    The code is the payment schedule's, not the contract's, and the two are
    allowed to differ. If the amount took its digit count from the contract
    the row would contradict itself: a figure with cents under a heading that
    says forint. One document, both currencies, so a renderer that reached for
    the nearest currency in scope fails here rather than looking plausible.
    """
    pdf = render_sales_contract_pdf(
        _contract("EUR"),
        SimpleNamespace(currency="HUF"),
        [_instalment()],
        [_party()],
        _plot("EUR"),
        _development(),
        locale="en",
    )
    text = _page_text(pdf)

    assert IN_CENTS in text, f"the EUR purchase price lost its cents: {text!r}"
    assert IN_FORINT in text, f"the forint instalment was not written in whole forint: {text!r}"
