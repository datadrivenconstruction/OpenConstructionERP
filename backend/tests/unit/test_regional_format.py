# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A document is written the way its country writes numbers and dates.

The distinguishing cases are the ones a currency-only rule gets wrong: an Irish
euro amount is ``1,234.56`` and not the German ``1.234,56``, a French one is
spaced, and a hryvnia is spaced rather than American. Each is asserted against
the wrong answer the old rule gave as well as the right one.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.core.i18n_data import COUNTRY_DEFAULTS, NUMBER_FORMATS
from app.core.regional_format import (
    ANGLO,
    CONTINENTAL,
    INDIAN,
    NBSP,
    PATTERN_STYLES,
    SPACED,
    SWISS,
    SWISS_APOSTROPHE,
    format_date,
    format_number,
    number_style,
    style_for_country,
    style_for_currency,
)

AMOUNT = Decimal("1234567.891")


@pytest.mark.parametrize(
    ("country", "currency", "expected"),
    [
        ("IE", "EUR", "1,234,567.89"),
        ("DE", "EUR", "1.234.567,89"),
        ("FR", "EUR", f"1{NBSP}234{NBSP}567,89"),
        ("CH", "CHF", f"1{SWISS_APOSTROPHE}234{SWISS_APOSTROPHE}567.89"),
        ("UA", "UAH", f"1{NBSP}234{NBSP}567,89"),
        ("HU", "HUF", f"1{NBSP}234{NBSP}567,89"),
        ("GB", "GBP", "1,234,567.89"),
        ("IN", "INR", "12,34,567.89"),
        ("RU", "RUB", f"1{NBSP}234{NBSP}567,89"),
    ],
)
def test_the_country_decides_the_separators(country: str, currency: str, expected: str) -> None:
    assert format_number(AMOUNT, 2, number_style(country, currency)) == expected


def test_an_irish_euro_amount_is_not_written_the_german_way() -> None:
    """The defect: the currency alone made every Irish bill German."""
    assert number_style("IE", "EUR") == ANGLO
    assert style_for_currency("EUR") == CONTINENTAL


def test_a_hryvnia_amount_without_a_country_is_spaced_not_american() -> None:
    assert number_style(None, "UAH") == SPACED
    assert format_number(Decimal("1234.5"), 2, number_style(None, "UAH")) == f"1{NBSP}234,50"


@pytest.mark.parametrize(
    ("currency", "expected"),
    [("EUR", CONTINENTAL), ("RUB", CONTINENTAL), ("USD", ANGLO), ("GBP", ANGLO), ("", ANGLO), ("INR", INDIAN)],
)
def test_without_a_country_the_currency_keeps_its_old_answer(currency: str, expected) -> None:
    """A document with no country prints as it did before the country decided."""
    assert number_style("", currency) == expected


def test_an_unknown_country_falls_back_to_the_currency() -> None:
    assert style_for_country("XX") is None
    assert number_style("XX", "EUR") == CONTINENTAL


def test_the_swiss_separator_is_the_one_the_browser_prints() -> None:
    """CLDR 48 writes ``de-CH`` as ``1'234'567.89`` with U+0027, measured on ICU 78.3."""
    assert SWISS.group == "'"
    assert PATTERN_STYLES["1'234.56"] == SWISS
    # The typographic spelling older CLDR releases printed still reads as Swiss.
    assert PATTERN_STYLES["1\u2019234.56"] == SWISS


@pytest.mark.parametrize(
    ("value", "decimals", "expected"),
    [
        (Decimal("0"), 2, "0.00"),
        (Decimal("-1234.5"), 2, "-1,234.50"),
        (Decimal("-0.001"), 2, "0.00"),
        (Decimal("2.675"), 2, "2.68"),
        (Decimal("999.995"), 2, "1,000.00"),
        (Decimal("1234.5"), 0, "1,235"),
        (12.5, 1, "12.5"),
        (None, 2, "0.00"),
        ("not a number", 2, "0.00"),
        (Decimal("NaN"), 2, "0.00"),
        (123, 0, "123"),
    ],
)
def test_format_number_edges(value, decimals: int, expected: str) -> None:
    assert format_number(value, decimals, ANGLO) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(Decimal("999"), "999.00"), (Decimal("1000"), "1,000.00"), (Decimal("100000"), "1,00,000.00")],
)
def test_indian_grouping_switches_to_pairs_after_the_first_thousand(value: Decimal, expected: str) -> None:
    assert format_number(value, 2, INDIAN) == expected


# ── Dates ────────────────────────────────────────────────────────────────────

DAY = date(2026, 10, 4)


@pytest.mark.parametrize(
    ("country", "expected"),
    [
        ("IE", "04/10/2026"),
        ("GB", "04/10/2026"),
        ("US", "10/04/2026"),
        ("CA", "2026-10-04"),
        ("DE", "04.10.2026"),
        ("CH", "04.10.2026"),
        ("HU", "2026.10.04."),
        ("JP", "2026/10/04"),
        (None, "04.10.2026"),
        ("XX", "04.10.2026"),
    ],
)
def test_the_country_decides_the_date_order(country: str | None, expected: str) -> None:
    assert format_date(DAY, country) == expected


def test_a_datetime_is_written_by_its_date() -> None:
    assert format_date(datetime(2026, 1, 2, 23, 59), "IE") == "02/01/2026"


def test_an_explicit_pattern_overrides_the_country() -> None:
    assert format_date(DAY, "US", pattern="YYYY-MM-DD") == "2026-10-04"


# ── The table itself ─────────────────────────────────────────────────────────


def test_every_country_default_uses_a_pattern_the_formatter_can_read() -> None:
    """A pattern nobody can read would silently fall back to the currency."""
    unreadable = {
        cc: e["number_format"] for cc, e in COUNTRY_DEFAULTS.items() if e["number_format"] not in PATTERN_STYLES
    }
    assert unreadable == {}


def test_every_country_date_format_uses_only_the_three_tokens() -> None:
    for cc, entry in COUNTRY_DEFAULTS.items():
        pattern = entry["date_format"]
        stripped = pattern.replace("YYYY", "").replace("MM", "").replace("DD", "")
        assert set(stripped) <= {".", "/", "-"}, (cc, pattern)
        assert all(token in pattern for token in ("YYYY", "MM", "DD")), (cc, pattern)


def test_every_country_default_pattern_is_described_in_number_formats() -> None:
    described = set(NUMBER_FORMATS)
    for cc, entry in COUNTRY_DEFAULTS.items():
        assert entry["number_format"] in described, (cc, entry["number_format"])


@pytest.mark.parametrize("country", ["SE", "NO", "FI", "PL", "CZ", "UA", "HU"])
def test_the_spaced_markets_are_spaced(country: str) -> None:
    """These were filed with dots, which is German, not how any of them writes a number."""
    assert style_for_country(country) == SPACED
