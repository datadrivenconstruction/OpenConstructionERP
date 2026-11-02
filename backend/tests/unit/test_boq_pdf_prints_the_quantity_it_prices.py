"""The PDF bill prints a quantity with the decimals it carries (2 to 4)."""

from decimal import Decimal

import pytest

from app.modules.boq.pdf_export import _fmt_quantity, _quantity_decimals


@pytest.mark.parametrize(
    ("value", "decimals"),
    [
        (2.5, 2),
        (2, 2),
        (2.625, 3),
        (0.2205, 4),
        (Decimal("1.23456"), 4),
        ("12.500", 2),
        (Decimal("3.1000"), 2),
    ],
)
def test_decimals_follow_the_value(value, decimals):
    assert _quantity_decimals(value) == decimals


def test_formats_in_the_market_separators():
    assert _fmt_quantity(2.625, "US", "USD") == "2.625"
    assert _fmt_quantity(2.5, "US", "USD") == "2.50"
    assert _fmt_quantity(0.2205, "US", "USD") == "0.2205"


def test_a_zero_decimal_currency_does_not_round_quantities():
    assert _fmt_quantity(2.625, "JP", "JPY") == "2.625"


def test_unreadable_value_is_printed_as_is():
    assert _fmt_quantity("n/a") == "n/a"
