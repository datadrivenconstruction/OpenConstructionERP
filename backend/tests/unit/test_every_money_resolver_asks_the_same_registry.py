"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The money resolvers are checked against each other, not against a roster.

Five paths are compared here, and until this file existed they agreed because
somebody had typed the same numbers into each of them. That is the failure mode
this codebase has already been bitten by twice: two registries that match today,
one of them gains a row, and nothing notices until a user does.

Five is this file's coverage, not a count of the backend, which is the reading
the first version of this docstring invited. An AST sweep of ``app`` found
fifteen functions that are handed a currency and ask ``minor_units`` or
``money_quantum`` how many digits it keeps, and nine more that are handed a
currency and quantize to a literal of their own anyway. A check asserting that
the backend still holds exactly five would be asserting something that was never
true, so this file neither claims it nor tests it.

Four of the five are swept below. The fifth is the one this file read as four
for a while: ``app.modules.property_dev.document_templates._format_money``, the
renderer behind every contract, receipt and certificate the property module
issues. It took a locale and no currency at all and quantised to a
``Decimal("0.01")`` literal, so it was never a resolver that agreed, it was a
resolver nobody had counted. It reads ``minor_units`` now, and is pinned in
``test_a_property_document_prints_an_amount_in_its_own_currencys_units``. It is
named here rather than swept below because importing it pulls the whole PDF
stack into a file that otherwise touches nothing but arithmetic.

So nothing here asserts a currency against a literal. Every assertion asks one
resolver what it says and compares it to what another resolver says, iterating
over ``CURRENCIES`` so that a currency added tomorrow is covered the moment it is
added and no test needs a manual edit to keep up.

The per-code decisions themselves live where they are made and are pinned where
they are made: the document overrides in ``test_einvoice_rules`` and the registry
counts in ``test_money_iso4217_minor_units``. Recording a decision and detecting
drift are different jobs and are kept in different files on purpose.

Which layer governs what is written out in full in ``app.core.money``, above
:func:`app.core.money.minor_units`. The short version, because it is the thing a
reader has to have in mind to know whether a failure here is a bug or a decision:
the value layer rounds the amount and follows the currency's real subdivision,
the document layer caps that at what EN 16931 permits, and the screen layer is in
the frontend and follows the reader's own conventions instead. Only the first two
are backend code and only the first two are compared here.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.core.money import CURRENCIES, MoneyValue, minor_units, money_quantum
from app.modules.einvoice.rules import _DOCUMENT_MINOR_UNITS, _EN16931_MAX_DECIMALS, money_decimals
from app.modules.fx.service import _q_money, decompose_movement
from app.modules.price_breakdown.model import money_quantum as price_breakdown_quantum

#: One probe amount with a different non-zero digit at every decimal place the
#: platform can produce, so rounding it to 0, 2 or 3 places gives three numbers
#: that differ as numbers. A rounder probe (``1.5``, ``100.00``) would survive
#: every digit count unchanged and let a broken resolver pass.
PROBE = Decimal("1.23456")

#: Every code any backend resolver can be asked about, as a sorted list so a
#: failure names the same currency every run.
ALL_CODES = sorted(set(CURRENCIES) | set(_DOCUMENT_MINOR_UNITS))


def _through_core(code: str) -> Decimal:
    """``PROBE`` rounded by the conversion path in ``app.core.money``."""
    return MoneyValue(amount=str(PROBE), currency_code="XXX").convert(code, "1").to_decimal()


def _through_fx(code: str) -> Decimal:
    """``PROBE`` rounded by the FX service's converted-amount path."""
    return _q_money(PROBE, code)


def _through_price_breakdown(code: str) -> Decimal:
    """``PROBE`` rounded by the unit-price-analysis path."""
    return PROBE.quantize(price_breakdown_quantum(code), rounding=ROUND_HALF_UP)


# ── the instrument first ──────────────────────────────────────────────────────


def test_the_probe_can_actually_tell_the_digit_counts_apart() -> None:
    """Without this, every comparison below could pass while measuring nothing.

    The comparisons are equalities between resolvers, and equalities are cheap to
    satisfy by accident: if the probe rounded to the same number at every digit
    count, three resolvers disagreeing about the count would still return three
    equal values and the suite would be green and empty.
    """
    rounded = {places: PROBE.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP) for places in (0, 2, 3)}
    assert len(set(rounded.values())) == 3, f"the probe cannot distinguish digit counts: {rounded}"


def test_the_registry_actually_carries_currencies_of_every_kind() -> None:
    """And without this, the sweep could be a sweep over one digit count.

    A registry that had lost its zero-decimal and three-decimal entries would let
    a resolver hardcoded to two decimals pass every comparison in this file.
    """
    counts = {minor_units(code) for code in CURRENCIES}
    assert {0, 2, 3} <= counts, f"registry no longer spans the digit counts under test: {sorted(counts)}"


# ── resolver against resolver ─────────────────────────────────────────────────


def test_every_value_layer_path_rounds_an_amount_to_the_same_number() -> None:
    """The three value-layer rounders agree, for every currency, by construction.

    They agree because all three now derive their quantum from
    :func:`app.core.money.money_quantum` rather than each holding a table. This
    asserts the consequence rather than the mechanism, so it keeps working if one
    of them is rewritten and keeps failing if one of them grows its own opinion.
    """
    disagreements: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
    for code in ALL_CODES:
        answers = (_through_core(code), _through_fx(code), _through_price_breakdown(code))
        if len(set(answers)) > 1:
            disagreements[code] = answers
    assert not disagreements, f"value-layer resolvers disagree: {disagreements}"


def test_no_value_layer_path_rounds_to_two_decimals_regardless_of_the_currency() -> None:
    """The specific regression: a rounding step that ignores its currency.

    ``Decimal("0.01")`` written as a literal is the shape of this bug, and it has
    now appeared on three separate conversion paths in this codebase. For every
    currency that is not a two-decimal currency, each path has to produce
    something a blind two-decimal rounding could not have produced.
    """
    blind = PROBE.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    offenders: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
    for code in ALL_CODES:
        if minor_units(code) == 2:
            continue
        answers = (_through_core(code), _through_fx(code), _through_price_breakdown(code))
        if blind in answers:
            offenders[code] = answers
    assert not offenders, f"a value-layer path rounded a non-two-decimal currency to cents: {offenders}"


def test_the_quantum_and_the_digit_count_are_two_readings_of_one_answer() -> None:
    """``money_quantum`` and ``minor_units`` cannot drift apart either."""
    mismatched = {
        code: (money_quantum(code), minor_units(code))
        for code in ALL_CODES
        if money_quantum(code) != Decimal(1).scaleb(-minor_units(code))
    }
    assert not mismatched, f"quantum and digit count disagree: {mismatched}"


# ── the document layer derives from the value layer ───────────────────────────


def test_the_document_resolver_holds_no_private_opinion_about_an_undecided_code() -> None:
    """A code the document table has not decided takes the registry's count.

    This is what makes ``money_decimals`` a cap on one source rather than a
    second source. It fails the moment somebody gives the document layer its own
    fallback table, which is exactly how the two would start to drift.
    """
    divergent = {
        code: (money_decimals(code), minor_units(code))
        for code in CURRENCIES
        if code not in _DOCUMENT_MINOR_UNITS and money_decimals(code) != min(minor_units(code), _EN16931_MAX_DECIMALS)
    }
    assert not divergent, f"the document resolver diverges from the registry it is supposed to read: {divergent}"


def test_a_decided_code_is_written_as_decided_capped_at_what_en16931_permits() -> None:
    """And a code the document table HAS decided is written the way it decided.

    The cap stays a separate step: the Iraqi dinar is carried at three because
    that is its subdivision, and it is EN 16931 that trims it to two, not the
    table pre-baking the trim.
    """
    divergent = {
        code: (money_decimals(code), declared)
        for code, declared in _DOCUMENT_MINOR_UNITS.items()
        if money_decimals(code) != min(declared, _EN16931_MAX_DECIMALS)
    }
    assert not divergent, f"a decided code is not written as decided: {divergent}"


def test_no_currency_can_put_more_decimals_on_a_document_than_the_standard_allows() -> None:
    """BR-DEC caps document amounts at two decimals, whatever the currency does."""
    over_cap = {code: money_decimals(code) for code in ALL_CODES if not 0 <= money_decimals(code) <= 2}
    assert not over_cap, f"document amounts outside the permitted range: {over_cap}"


# ── the value layer, end to end ───────────────────────────────────────────────


def test_a_revaluation_is_reported_in_the_units_its_reporting_currency_has() -> None:
    """Movement attribution rounds to the reporting currency, not to cents.

    A yen figure has no sub-yen part to attribute, and the three components still
    have to add up to the total after rounding - the property the split exists
    for. Both are asked here because a currency-aware quantum that broke the
    addition would be a worse answer than the currency-blind one it replaced.

    The rates are deliberately long enough that every product has a fractional
    part. With round rates the old behaviour produced ``6100.00`` where the new
    one produces ``6100``, and those two are equal as numbers, so an assertion
    on the value alone would have passed against the code this replaced. The
    exponent is asserted for the same reason.
    """
    split = decompose_movement(
        Decimal("1000000"), Decimal("1100000"), Decimal("0.0061234"), Decimal("0.0064321"), "JPY"
    )
    for name, value in (
        ("baseline_value", split.baseline_value),
        ("current_value", split.current_value),
        ("scope_delta", split.scope_delta),
        ("rate_delta", split.rate_delta),
    ):
        assert value.as_tuple().exponent == 0, f"{name} is written to sub-yen precision: {value}"
        assert value == value.to_integral_value(), f"{name} carries a sub-yen part: {value}"
    assert split.scope_delta + split.rate_delta + split.joint_delta == split.total_delta
    assert split.baseline_value + split.total_delta == split.current_value


def test_a_conversion_into_a_three_decimal_currency_keeps_its_third_digit() -> None:
    """The other direction of the same fault, and the one that loses money.

    Two decimals on a Kuwaiti dinar is not a tidier number, it is a discarded
    fils, and the fils is a subunit a payment can genuinely carry.
    """
    kept = _q_money(Decimal("30.6789"), "KWD")
    assert kept == Decimal("30.679"), f"the third digit was dropped: {kept}"
    assert kept != Decimal("30.68")
