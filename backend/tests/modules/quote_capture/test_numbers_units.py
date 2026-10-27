# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Number​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ formats per locale and unit normalisation of quote lines."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.quote_capture.numbers import decimal_mark, looks_numeric, parse_number, plain, to_decimal
from app.modules.quote_capture.units import is_known_unit, normalise_unit, same_unit

D = Decimal


@pytest.mark.parametrize(
    ("raw", "locale", "expected"),
    [
        ("1.234,56", "de", D("1234.56")),
        ("1,234.56", "en", D("1234.56")),
        ("1 234,56", "fr", D("1234.56")),
        ("1 234,56 €", "fr", D("1234.56")),
        ("1'234.50", "de-CH", D("1234.50")),
        ("12,5", "de", D("12.5")),
        ("12.5", "en", D("12.5")),
        ("1.234", "de", D("1234")),
        ("1.234", "en", D("1.234")),
        ("1,234", "en", D("1234")),
        ("1,234", "de", D("1.234")),
        ("1.234.567,8", "de", D("1234567.8")),
        ("(120.00)", "en", D("-120.00")),
        ("EUR 980,00", "de", D("980.00")),
        ("١٬٢٣٤٫٥٠", "ar", D("1234.50")),
        ("٣٥٠", "ar", D("350")),
    ],
)
def test_parse_number_reads_every_locale(raw: str, locale: str, expected: Decimal) -> None:
    assert parse_number(raw, locale) == expected


def test_parse_number_rejects_text() -> None:
    assert parse_number("Beton") is None
    assert parse_number("") is None
    assert parse_number(None) is None
    assert not looks_numeric("m2")
    assert looks_numeric("1.234,50")


def test_ambiguous_group_without_locale_is_thousands() -> None:
    assert parse_number("2.500") == D("2500")


def test_decimal_mark_by_locale() -> None:
    assert decimal_mark("de") == ","
    assert decimal_mark("de-CH") == "."
    assert decimal_mark("en-US") == "."
    assert decimal_mark("ar") == "."
    assert decimal_mark(None) is None


def test_stored_values_round_trip() -> None:
    assert plain(D("1234.5")) == "1234.50"
    assert plain(D("12.125")) == "12.125"
    assert to_decimal("12.125") == D("12.125")
    assert to_decimal(plain(D("1500"))) == D("1500")


@pytest.mark.parametrize(
    ("raw", "locale", "canonical"),
    [
        ("m²", None, "m2"),
        ("m2", None, "m2"),
        ("qm", "de", "m2"),
        ("lfm", "de", "lm"),
        ("lm", "en", "lm"),
        ("Stk", "de", "pcs"),
        ("Stk.", "de", "pcs"),
        ("pcs", "en", "pcs"),
        ("ea", "en", "pcs"),
        ("m³", None, "m3"),
        ("psch", "de", "lsum"),
        ("forfait", "fr", "lsum"),
        ("ml", "fr", "lm"),
        ("u", "fr", "pcs"),
        ("م2", "ar", "m2"),
        ("متر مربع", "ar", "m2"),
        ("шт", "ru", "pcs"),
    ],
)
def test_units_normalise(raw: str, locale: str | None, canonical: str) -> None:
    assert normalise_unit(raw, locale) == canonical


def test_ml_is_not_a_linear_metre_outside_french() -> None:
    assert normalise_unit("ml", "de") == "ml"
    assert normalise_unit("ml", "fr") == "lm"


def test_unit_helpers() -> None:
    assert same_unit("m²", "qm", "de")
    assert not same_unit("m2", "m3")
    assert is_known_unit("Stk")
    assert not is_known_unit("Beton")
