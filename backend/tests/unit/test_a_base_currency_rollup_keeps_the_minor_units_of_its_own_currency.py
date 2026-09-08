# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``_convert_to_base`` rounds an FX rollup to the base currency's own units.

The helper is handed ``base_currency`` and is the last step that sees it, then
it quantised the converted total to a ``Decimal("0.01")`` literal for every
project on earth. A Kuwaiti dinar rollup lost its third digit, a fils a real
payment can carry, before any caller could put it back; a yen rollup came back
carrying two decimals nothing in Japan can settle.

This is arithmetic, not presentation. Five call sites in ``finance.service``
parse the string straight back into a ``Decimal`` and keep computing with it,
and one of them, ``create_evm_snapshot``, persists the result.

WHY THE SIBLING GATE DID NOT CATCH IT.
``test_a_persisted_evm_forecast_is_rounded_to_its_projects_currency`` pins the
same method's currency handling and passes. It supplies ``bac``, ``pv``, ``ev``
and ``ac`` all non-zero, so ``create_evm_snapshot`` never takes the
derive-from-empty-snapshot branch, and that branch is the only route to
``_convert_to_base``. The sibling proves the OUTER rounding, at
``money_quantum(base_ccy)``; the flattening happened one layer further in, and
the outer quantum cannot restore a digit the inner one already discarded. A
green gate whose population excludes the defect site is the shape this file
exists to close, so it tests the helper directly rather than through the method.

The counts are asserted against :func:`app.core.money.money_quantum`, the
platform's single value-layer resolver, never against a table of this file's
own, so a currency whose subdivision changes tomorrow stays covered with no
edit here.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.money import CURRENCIES, money_quantum
from app.modules.finance.service import _convert_to_base

#: One amount with a different non-zero digit at every decimal place the
#: platform can produce, so rounding it to 0, 2 or 3 places gives three numbers
#: that differ AS NUMBERS. A rounder probe (``1.50``, ``1000.00``) would survive
#: every digit count unchanged and let the defect pass this file green.
PROBE = "1.23456"

#: The value the defect produced for every currency alike, and therefore the
#: value that must NOT come back for a currency that does not round to it.
FLATTENED = Decimal("1.23")


def _places(text: str) -> int:
    """Decimal places actually carried by the returned string."""
    return -Decimal(text).as_tuple().exponent


def _rollup(code: str, amount: str = PROBE) -> str:
    """``amount`` already in the base currency, so no FX rate is involved."""
    total, _missing = _convert_to_base({"": amount}, base_currency=code, fx_rates_map={})
    return total


# ── the instrument first ──────────────────────────────────────────────────────


def test_the_probe_can_actually_tell_the_digit_counts_apart() -> None:
    """Without this, every assertion below could pass while measuring nothing.

    If the probe rounded to the same number at 0, 2 and 3 places, a helper that
    ignored its currency entirely would satisfy every case in this file.
    """
    rounded = {places: Decimal(PROBE).quantize(Decimal(1).scaleb(-places)) for places in (0, 2, 3)}
    assert len(set(rounded.values())) == 3, f"the probe cannot distinguish digit counts: {rounded}"


# ── the defect, in both directions ────────────────────────────────────────────


def test_a_three_decimal_base_currency_keeps_the_fils_it_was_losing() -> None:
    """The direction that destroys money.

    A dinar is subdivided into 1000 fils. Two places discards a fils a real
    payment can carry, and this helper's answer is parsed back into a Decimal
    and carried on with.
    """
    total = _rollup("KWD")

    assert _places(total) == 3, f"rolled up to {total!r}, a dinar carries three places"
    assert Decimal(total) != FLATTENED, f"{total!r} is the two-place answer, the fils is gone"


def test_a_zero_decimal_base_currency_is_not_given_a_subunit_it_lacks() -> None:
    """The other direction, and the one a two-place literal also gets wrong.

    A yen has no subunit at all, so two decimals are not merely redundant, they
    are a quantity the currency cannot express.
    """
    total = _rollup("JPY")

    assert _places(total) == 0, f"rolled up to {total!r}, a yen has no subunit"
    assert Decimal(total) != FLATTENED, f"{total!r} is the two-place answer"


def test_an_fx_converted_rollup_is_rounded_in_the_currency_it_lands_in() -> None:
    """The path that actually runs in production: a foreign amount times a rate.

    The rate is what produces the long tail here, so this fails if the quantum
    is read from the amount's own currency rather than from the base it was
    converted into.
    """
    total, missing = _convert_to_base({"USD": "1000"}, base_currency="KWD", fx_rates_map={"USD": "0.3061234"})

    assert missing == [], f"a configured rate should not be reported missing: {missing}"
    assert _places(total) == 3, f"converted to {total!r}, a dinar carries three places"
    assert Decimal(total) == Decimal("306.123")


# ── the cases a careless gate would also flag ─────────────────────────────────


def test_a_two_decimal_base_currency_still_gets_exactly_two() -> None:
    """The control, and the reason this file is not just "assert three places".

    Most currencies genuinely do round to two. A fix that widened everything to
    the dinar's three, or that trimmed everything to the yen's zero, would be
    just as wrong as the literal it replaced, and would pass a gate that only
    checked the two currencies above. This case fails on any such fix.
    """
    total = _rollup("EUR")

    assert _places(total) == 2, f"rolled up to {total!r}, a euro carries two places"
    assert Decimal(total) == FLATTENED


def test_a_blank_base_currency_keeps_the_two_decimal_default() -> None:
    """Nothing to resolve, so nothing is invented.

    Two places is what this helper always wrote and stays the answer when there
    is no base currency to ask about. This is also what makes the change a
    no-op for every caller that never had a currency in the first place.
    """
    for blank in ("", "   ", None):
        total, _missing = _convert_to_base({"": PROBE}, base_currency=blank, fx_rates_map={})  # type: ignore[arg-type]
        assert _places(total) == 2, f"blank base {blank!r} rolled up to {total!r}"


# ── the whole registry, with its population printed ───────────────────────────


def test_every_registered_currency_is_rounded_by_the_resolver_and_not_a_literal() -> None:
    """Swept over the entire registry, so the verdict has a denominator.

    A gate satisfied by two hand-picked currencies can be satisfied by narrowing
    the set. This asserts the helper's answer equals the resolver's answer for
    every code the platform registers, and reports how many that was, so a later
    reader can tell whether a green result covered 3 currencies or all of them.
    """
    disagreements: dict[str, tuple[str, str]] = {}
    for code in sorted(CURRENCIES):
        got = _rollup(code)
        expected = Decimal(PROBE).quantize(money_quantum(code))
        if Decimal(got) != expected:
            disagreements[code] = (got, str(expected))

    population = len(CURRENCIES)
    spread = sorted({-money_quantum(code).as_tuple().exponent for code in CURRENCIES})
    assert not disagreements, (
        f"{len(disagreements)} of {population} registered currencies disagree with money_quantum: {disagreements}"
    )
    # Printed rather than merely counted: the population is the part of a green
    # verdict that a narrowed gate cannot fake.
    print(f"currencies checked: {population}; distinct minor-unit counts covered: {spread}")
    assert population >= 79, f"registry shrank to {population}, this sweep no longer covers what it claims"
    assert spread == [0, 2, 3], f"registry no longer spans the digit counts under test: {spread}"
