"""ISO-4217 minor-unit handling — Audit I1.

The ``MoneyValue.convert`` method used to hardcode ``Decimal("0.01")``
as the quantisation quantum for the converted amount, regardless of
the target currency. That silently introduced fractional fils/yen on
every conversion into JPY/KRW/KWD/BHD/etc.

These tests pin the corrected behaviour:

* zero-decimal currencies (JPY, KRW, VND, ISK, ...) quantise to integers
* three-decimal currencies (KWD, BHD, OMR, JOD, IQD, LYD, TND) keep all
  three decimals
* two-decimal currencies (USD, EUR, GBP, ...) keep two decimals
* unknown currency codes fall back to 2 decimals (legacy behaviour)
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.money import CURRENCIES, MoneyValue, format_money

# ── Conversion quantisation ----------------------------------------------


def test_convert_to_jpy_yields_integer_amount() -> None:
    """USD to JPY conversion must not carry sub-yen decimals."""
    usd = MoneyValue(amount="100.00", currency_code="USD")
    jpy = usd.convert("JPY", "142.5")
    # 100.00 * 142.5 = 14250.00 → quantised to integer → "14250"
    assert Decimal(jpy.amount) == Decimal("14250")
    assert "." not in jpy.amount, f"JPY amount {jpy.amount!r} carries decimals"


def test_convert_to_krw_yields_integer_amount() -> None:
    """KRW (won) is also zero-decimal."""
    usd = MoneyValue(amount="100.00", currency_code="USD")
    krw = usd.convert("KRW", "1325.5")
    assert Decimal(krw.amount) == Decimal("132550")


def test_convert_to_kwd_keeps_three_decimals() -> None:
    """KWD (Kuwaiti dinar) needs three decimals."""
    usd = MoneyValue(amount="100.00", currency_code="USD")
    kwd = usd.convert("KWD", "0.306")
    # 100.00 * 0.306 = 30.600 → must stay 30.600 (not 30.60).
    # We assert via Decimal so trailing-zero normalisation doesn't fool us.
    assert Decimal(kwd.amount) == Decimal("30.600")


def test_convert_to_bhd_keeps_three_decimals() -> None:
    """BHD (Bahraini dinar) — same as KWD, third decimal is meaningful."""
    eur = MoneyValue(amount="1000.00", currency_code="EUR")
    bhd = eur.convert("BHD", "0.408")
    assert Decimal(bhd.amount) == Decimal("408.000")


def test_convert_to_usd_keeps_two_decimals() -> None:
    """USD/EUR (standard 2-decimal) baseline."""
    eur = MoneyValue(amount="1000.00", currency_code="EUR")
    usd = eur.convert("USD", "1.085")
    # 1000.00 * 1.085 = 1085.000 → quantised to 2 decimals → 1085.00
    assert Decimal(usd.amount) == Decimal("1085.00")


def test_convert_to_unknown_currency_falls_back_to_two_decimals() -> None:
    """Currency we don't have an entry for falls back to 2 decimals.

    Pin: must not crash, must not over-quantise. We pick "XXX" which
    is the ISO reserved no-currency code — explicitly absent from the
    registry by design.
    """
    usd = MoneyValue(amount="100.00", currency_code="USD")
    xxx = usd.convert("XXX", "1.0")
    assert Decimal(xxx.amount) == Decimal("100.00")


# ── format_money ---------------------------------------------------------


def test_format_money_jpy_no_decimals() -> None:
    """JPY rendering must not show "100.00" — should be "100"."""
    formatted = format_money("100", "JPY", "en")
    assert "." not in formatted
    assert "100" in formatted


def test_format_money_kwd_three_decimals() -> None:
    """KWD rendering preserves all three decimals."""
    formatted = format_money("30.600", "KWD", "en")
    # "30.600" must appear verbatim — losing the trailing zero would
    # signal we silently dropped to 2 decimals.
    assert "30.600" in formatted, f"got {formatted!r}"


def test_format_money_usd_two_decimals() -> None:
    """USD baseline (2 decimals)."""
    formatted = format_money("100", "USD", "en")
    assert "100.00" in formatted


# ── Registry coverage ----------------------------------------------------


@pytest.mark.parametrize(
    "code,expected_decimals",
    [
        ("JPY", 0),
        ("KRW", 0),
        ("VND", 0),
        ("ISK", 0),
        ("XOF", 0),
        ("XAF", 0),
        ("HUF", 0),
        ("CLP", 0),
        ("PYG", 0),
        ("RWF", 0),
        ("UGX", 0),
        ("KWD", 3),
        ("BHD", 3),
        ("OMR", 3),
        ("JOD", 3),
        ("IQD", 3),
        ("LYD", 3),
        ("TND", 3),
        ("USD", 2),
        ("EUR", 2),
        ("GBP", 2),
        ("BRL", 2),
    ],
)
def test_registry_has_correct_minor_units(code: str, expected_decimals: int) -> None:
    """Pin the minor-unit counts so a future cleanup doesn't accidentally
    "round-trip" KWD/BHD/etc. to 2 via copy-paste.
    """
    assert code in CURRENCIES, f"{code} missing from CURRENCIES registry"
    assert CURRENCIES[code]["decimals"] == expected_decimals
