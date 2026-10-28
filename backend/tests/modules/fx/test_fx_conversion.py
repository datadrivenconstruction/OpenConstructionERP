# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the FX conversion maths and the ECB parser.

Everything here is pure: no database, no network. The point of keeping the
arithmetic in free functions is that these can be reasoned about on their own,
and a rounding decision can be pinned to an exact expected value rather than to
"about right".
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.fx.service import (
    UnknownCurrencyError,
    _q_rate,
    convert_via_base,
    cross_rate,
    decompose_movement,
    parse_ecb_xml,
)
from tests.modules.fx.conftest import ECB_XML

# Units of each currency per 1 EUR, the shape the ECB publishes.
EUR_RATES: dict[str, Decimal] = {
    "USD": Decimal("1.0850"),
    "TRY": Decimal("42.5000"),
    "VND": Decimal("27500"),
}


# ── Cross rates ──────────────────────────────────────────────────────────────


def test_cross_rate_from_base_is_the_quote_itself() -> None:
    assert cross_rate("EUR", "TRY", EUR_RATES) == Decimal("42.5000")


def test_cross_rate_to_base_is_the_inverse() -> None:
    assert cross_rate("TRY", "EUR", EUR_RATES) == Decimal("1") / Decimal("42.5000")


def test_cross_rate_between_two_quoted_currencies_goes_through_the_base() -> None:
    assert cross_rate("USD", "TRY", EUR_RATES) == Decimal("42.5000") / Decimal("1.0850")


def test_cross_rate_is_case_insensitive_and_trims() -> None:
    assert cross_rate(" try ", "usd", EUR_RATES) == cross_rate("TRY", "USD", EUR_RATES)


def test_cross_rate_rejects_a_currency_the_set_does_not_quote() -> None:
    with pytest.raises(UnknownCurrencyError, match="ZWL"):
        cross_rate("EUR", "ZWL", EUR_RATES)


def test_cross_rate_rejects_a_malformed_code() -> None:
    with pytest.raises(UnknownCurrencyError):
        cross_rate("EUR", "EU", EUR_RATES)


def test_cross_rate_rejects_a_non_positive_quote() -> None:
    with pytest.raises(UnknownCurrencyError, match="XXX"):
        cross_rate("EUR", "XXX", {**EUR_RATES, "XXX": Decimal("0")})


def test_convert_via_base_applies_the_cross_rate_to_the_amount() -> None:
    converted, effective = convert_via_base("1000", "EUR", "TRY", EUR_RATES)
    assert effective == Decimal("42.5000")
    assert converted == Decimal("42500.0000")


def test_convert_via_base_accepts_a_non_eur_base() -> None:
    # Rates quoted against USD instead: 1 USD buys 39.17 TRY.
    usd_rates = {"TRY": Decimal("39.17"), "EUR": Decimal("0.9217")}
    converted, effective = convert_via_base("100", "USD", "TRY", usd_rates, base_currency="USD")
    assert effective == Decimal("39.17")
    assert converted == Decimal("3917.00")


# ── Rate rounding ────────────────────────────────────────────────────────────


def test_rate_at_or_above_one_keeps_six_decimals() -> None:
    assert str(_q_rate(Decimal("1.08"))) == "1.080000"


def test_small_rate_keeps_twelve_significant_digits() -> None:
    # 1 VND is 0.0000363636... EUR. Six decimals would make that 0.000036 and
    # lose one percent of every figure converted with it.
    quantized = _q_rate(Decimal("1") / Decimal("27500"))
    assert str(quantized) == "0.0000363636363636"


def test_a_small_rate_that_fits_in_six_decimals_keeps_six() -> None:
    """The extra digits appear only when six decimals would truncate."""
    assert str(_q_rate(Decimal("0.845"))) == "0.845000"


def test_small_rate_rounding_error_stays_below_a_millionth_relative() -> None:
    exact = Decimal("1") / Decimal("27500")
    error = (_q_rate(exact) - exact).copy_abs() / exact
    assert error < Decimal("0.000001")


def test_zero_rate_quantizes_without_raising() -> None:
    assert _q_rate(Decimal("0")) == Decimal("0")


# ── Movement decomposition ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("baseline_amount", "current_amount", "baseline_rate", "current_rate"),
    [
        # Awkward on purpose: the cross rates are non-terminating decimals and
        # the amounts carry odd cents, so every component needs rounding.
        ("1234567.89", "1391011.13", "0.0276485788", "0.0246049661"),
        ("999999.99", "1000000.01", "0.3333333333", "0.1428571429"),
        ("250000.55", "250000.55", "1.0700000000", "1.0900000000"),
        ("77777.77", "70000.07", "7.7777777777", "3.3333333333"),
        ("1.01", "0.99", "0.0000363636", "0.0000370370"),
    ],
)
def test_components_sum_exactly_to_the_total(
    baseline_amount: str,
    current_amount: str,
    baseline_rate: str,
    current_rate: str,
) -> None:
    """scope + rate + joint == total, for every input rather than round ones.

    A report that "nearly adds up" is a report nobody trusts, so the identity is
    checked on values whose products all need rounding.
    """
    split = decompose_movement(
        Decimal(baseline_amount),
        Decimal(current_amount),
        Decimal(baseline_rate),
        Decimal(current_rate),
        "EUR",
    )
    assert split.scope_delta + split.rate_delta + split.joint_delta == split.total_delta
    assert split.baseline_value + split.total_delta == split.current_value


def test_pure_rate_movement_attributes_nothing_to_scope() -> None:
    split = decompose_movement(
        Decimal("250000.00"),
        Decimal("250000.00"),
        Decimal("1.07"),
        Decimal("1.09"),
        "EUR",
    )
    assert split.scope_delta == Decimal("0.00")
    assert split.rate_delta == Decimal("5000.00")
    # The amount did not change, so the interaction term is only the rounding
    # residual - here nothing at all.
    assert split.joint_delta == Decimal("0.00")
    assert split.total_delta == Decimal("5000.00")


def test_pure_scope_movement_attributes_nothing_to_the_rate() -> None:
    split = decompose_movement(
        Decimal("100000.00"),
        Decimal("120000.00"),
        Decimal("1.07"),
        Decimal("1.07"),
        "EUR",
    )
    assert split.rate_delta == Decimal("0.00")
    assert split.joint_delta == Decimal("0.00")
    assert split.scope_delta == Decimal("21400.00")


def test_scope_and_rate_moving_opposite_ways_do_not_hide_each_other() -> None:
    """A flat headline can hide a large scope increase paid for by the rate."""
    split = decompose_movement(
        Decimal("1000000.00"),
        Decimal("1100000.00"),
        Decimal("1.10"),
        Decimal("1.00"),
        "EUR",
    )
    assert split.total_delta == Decimal("0.00")
    assert split.scope_delta == Decimal("110000.00")
    assert split.rate_delta == Decimal("-100000.00")
    assert split.joint_delta == Decimal("-10000.00")


def test_values_are_rounded_to_money() -> None:
    split = decompose_movement(Decimal("3"), Decimal("3"), Decimal("0.3333333333"), Decimal("0.3333333333"), "EUR")
    assert split.baseline_value == Decimal("1.00")
    assert split.current_value == Decimal("1.00")


# ── ECB feed parsing ─────────────────────────────────────────────────────────


def test_parse_ecb_xml_reads_rates_and_the_reference_date() -> None:
    rates, ref_date = parse_ecb_xml(ECB_XML)
    assert ref_date == date(2026, 3, 2)
    assert rates == {
        "USD": Decimal("1.0850"),
        "TRY": Decimal("42.5000"),
        "CNY": Decimal("7.8000"),
    }


def test_parse_ecb_xml_accepts_bytes() -> None:
    rates, _ref_date = parse_ecb_xml(ECB_XML.encode("utf-8"))
    assert rates["USD"] == Decimal("1.0850")


def test_parse_ecb_xml_rejects_a_document_with_no_rates() -> None:
    with pytest.raises(ValueError, match="No currency rates"):
        parse_ecb_xml("<Envelope><Cube time='2026-03-02'/></Envelope>")
