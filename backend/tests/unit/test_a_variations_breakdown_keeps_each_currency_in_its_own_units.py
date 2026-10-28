"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A per-currency variations breakdown is written in each currency's units.

``variations.service._money_str_map`` turns a ``{code: Decimal}`` map into the
wire format the dashboard reads. It is keyed by currency code, which is the
whole reason it exists: the scalar totals beside it are single-currency, and
this map is what a project running variations in more than one currency has
instead. It quantised every value in it to two decimals.

So it was wrong in exactly the place its own purpose lies. A forint entry came
back carrying fillér that left circulation in 1999, a Kuwaiti dinar entry came
back a fils short, and the two sat in one dictionary next to a euro entry that
was right, which is the arrangement most likely to make a reader trust all
three. That is not a missed edge case, it is the function contradicting the
reason it was written.

Four response fields are rendered through it, ``cost_impact_by_currency``,
``cost_impact_unconverted_by_currency``, ``daywork_value_by_currency`` and
``daywork_value_unconverted_by_currency``, and none of them had a test of any
kind before this file.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.money import CURRENCIES, minor_units
from app.modules.variations.service import _money_str_map

#: One amount with a different non-zero digit at every place the platform can
#: print, so rounding it to 0, 2 or 3 decimals gives three strings that differ
#: as strings. A rounder probe would read the same at every digit count and let
#: a currency-blind renderer pass the whole table.
PROBE = Decimal("1234567.891")


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
        ("HUF", "1234568"),
        ("IDR", "1234568"),
        ("JPY", "1234568"),
        # Two, which is what the old literal assumed, so these rows are the
        # control and have to come out byte-identical to the old renderer.
        ("EUR", "1234567.89"),
        ("USD", "1234567.89"),
        ("GBP", "1234567.89"),
        # Three. The Gulf and Tunisian dinars are subdivided into thousandths
        # and the third digit is a real fils a real variation was agreed in.
        ("BHD", "1234567.891"),
        ("KWD", "1234567.891"),
        ("TND", "1234567.891"),
    ],
)
def test_an_amount_is_written_with_the_digits_its_currency_has(currency: str, expected: str) -> None:
    assert _money_str_map({currency: PROBE}) == {currency: expected}


def test_one_map_carries_three_currencies_at_three_different_precisions() -> None:
    """The headline property, and the one the old code could not have.

    A single call, three keys, three digit counts. This is what the map is for:
    the scalar totals beside it are single-currency, and a project that runs
    variations in more than one currency has this instead. A renderer holding
    one opinion about decimals cannot pass it, whatever that opinion is.
    """
    written = _money_str_map({"HUF": PROBE, "EUR": PROBE, "KWD": PROBE})

    assert written == {"EUR": "1234567.89", "HUF": "1234568", "KWD": "1234567.891"}
    assert len({len(v.partition(".")[2]) for v in written.values()}) == 3


def test_every_registered_currency_takes_its_count_from_the_one_registry() -> None:
    """Every code in the registry, so a currency added tomorrow is covered."""
    written = _money_str_map(dict.fromkeys(CURRENCIES, PROBE))
    disagreements = {
        code: (value, minor_units(code))
        for code, value in written.items()
        if len(value.partition(".")[2]) != minor_units(code)
    }
    assert not disagreements, f"the breakdown disagrees with the registry: {disagreements}"


def test_a_currency_with_no_subunit_gets_no_separator_either() -> None:
    """A trailing "1234568." is a truncated number rather than a whole one."""
    written = _money_str_map({"HUF": PROBE})["HUF"]
    assert "." not in written, f"a forint was written with a decimal separator: {written!r}"


@pytest.mark.parametrize("code", ["", "  ", "ZZZ"])
def test_a_key_the_registry_does_not_carry_keeps_the_two_decimal_default(code: str) -> None:
    """Not a guess made here: it is the registry's own documented default.

    A variation can be recorded before anybody sets a currency on the project,
    and the breakdown must not invent one for it.
    """
    written = _money_str_map({code: PROBE})
    assert list(written.values()) == ["1234567.89"]


def test_a_blank_key_is_still_normalised_and_a_lowercase_key_uppercased() -> None:
    """Unchanged behaviour, asserted so the digit count cannot have moved it."""
    assert _money_str_map({"  ": Decimal("1")}) == {"": "1.00"}
    assert _money_str_map({"huf": Decimal("1")}) == {"HUF": "1"}


def test_the_wire_format_stays_plain_decimal_rather_than_scientific() -> None:
    """A large forint total must not come back as an exponent string.

    ``format(d, "f")`` is what keeps this true and the quantum change could
    have disturbed it, since quantising to a whole unit leaves an exponent of
    zero rather than a negative one.
    """
    written = _money_str_map({"HUF": Decimal("120000000000")})["HUF"]
    assert written == "120000000000", f"the wire format is no longer plain decimal: {written!r}"
