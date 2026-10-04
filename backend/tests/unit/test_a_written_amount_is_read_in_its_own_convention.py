# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A cost typed as free text is read in the convention it was written in.

An NCR's ``cost_impact`` is free text. The old reader only stripped commas,
so ``"BRL 12.000,00"`` became 12.00 and ``"EUR 12.500,50"`` became 12.5005: a
change order off by a factor of a thousand that still looks plausible. Brazil,
Germany and Russia all write amounts that way. ``"1.234.567"`` raised and
``"12000 EUR"`` did not match at all, so those were dropped without a trace.

Each case below separates the right reading from the wrong one. Where the
text genuinely could mean two amounts (``"12.500"`` in a currency with three
decimals) the reader says so instead of picking one.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.money import WrittenAmount, read_written_amount


@pytest.mark.parametrize(
    ("raw", "amount", "currency"),
    [
        # Dot groups, comma decimal: Brazil, Germany, much of Europe.
        ("BRL 12.000,00", "12000.00", "BRL"),
        ("EUR 12.500,50", "12500.50", "EUR"),
        ("1.234.567", "1234567", None),
        ("1.234.567,89", "1234567.89", None),
        # Comma groups, dot decimal.
        ("USD 1,250.50", "1250.50", "USD"),
        ("BRL 12,000", "12000", "BRL"),
        ("12,000", "12000", None),
        ("1,234,567", "1234567", None),
        # Indian grouping.
        ("INR 12,34,567", "1234567", "INR"),
        ("12,34,567.50", "1234567.50", None),
        # Space, no-break space and apostrophe groups.
        ("1 234 567,89", "1234567.89", None),
        ("RUB 1 234 567,89", "1234567.89", "RUB"),
        ("RUB 1 234,50", "1234.50", "RUB"),
        ("CHF 1'234.50", "1234.50", "CHF"),
        # A lone separator that is not followed by exactly three digits is the decimal point.
        ("12,5", "12.5", None),
        ("12,50", "12.50", None),
        ("1200.5", "1200.5", None),
        ("0,500", "0.500", None),
        ("1234.567", "1234.567", None),
        # The code may follow the number, with or without a space.
        ("12000 EUR", "12000", "EUR"),
        ("12.000,00EUR", "12000.00", "EUR"),
        ("eur 4500", "4500", "EUR"),
        # Plain numbers and symbols.
        ("4500", "4500", None),
        ("€ 12.500,50", "12500.50", "EUR"),
        ("R$ 12.000,00", "12000.00", "BRL"),
        ("$1,250.50", "1250.50", None),
        ("-500", "-500", None),
        ("(1,200.00)", "-1200.00", None),
    ],
)
def test_the_amount_is_read_as_written(raw: str, amount: str, currency: str | None) -> None:
    written = read_written_amount(raw)

    assert written.status == "read", f"{raw!r}: {written}"
    assert written.amount == Decimal(amount), f"{raw!r} read as {written.amount}"
    assert str(written.amount) == amount, "the digits written are the digits kept"
    assert written.currency == currency


@pytest.mark.parametrize("raw", ["12.500", "12,500", "KWD 1.250", "1,250 KWD"])
def test_three_digits_after_one_separator_is_ambiguous_in_a_three_decimal_currency(raw: str) -> None:
    """12.500 dinar may be twelve and a half or twelve thousand five hundred."""
    written = read_written_amount(raw, currency_hint="KWD")

    assert written.status == "ambiguous"
    assert written.amount is None


def test_the_written_code_beats_the_hint_when_deciding() -> None:
    """A euro amount on a dinar project is read with euro decimals."""
    written = read_written_amount("EUR 12.500", currency_hint="KWD")

    assert (written.status, written.amount, written.currency) == ("read", Decimal("12500"), "EUR")


def test_the_hint_never_becomes_the_written_currency() -> None:
    written = read_written_amount("12.500", currency_hint="EUR")

    assert (written.amount, written.currency) == (Decimal("12500"), None)


def test_an_ambiguous_amount_keeps_its_written_code() -> None:
    written = read_written_amount("KWD 12.500")

    assert (written.status, written.currency) == ("ambiguous", "KWD")


@pytest.mark.parametrize(
    "raw",
    [
        "approx. 5000",
        "5000-6000",
        "12.34.5",
        "1.234,56,78",
        "12,34.5,6",
        "EUR 500 USD",
        "XYZ 500",
        "500 apples",
        "1.2345,00",
        "12..5",
    ],
)
def test_text_that_holds_digits_but_no_clear_amount_is_unreadable(raw: str) -> None:
    written = read_written_amount(raw)

    assert written.status == "unreadable", f"{raw!r}: {written}"
    assert written.amount is None


@pytest.mark.parametrize("raw", [None, "", "   ", "to be assessed", "n/a", "EUR"])
def test_text_without_a_digit_is_blank(raw: str | None) -> None:
    assert read_written_amount(raw) == WrittenAmount(amount=None, currency=None, status="blank")


def test_a_number_is_accepted_as_it_is() -> None:
    assert read_written_amount(Decimal("12.5")).amount == Decimal("12.5")
    assert read_written_amount(4500).amount == Decimal("4500")
