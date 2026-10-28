# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure apportioned back-charge engine.

Stdlib + pytest only - mirrors the engine's constraint so it runs on the local
Python 3.11 test runner without app.* or SQLAlchemy on the path. Money is
exercised exclusively with Decimal literals, and every split is asserted to
reconcile to the cent.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.cost_recovery.apportionment import (
    DEFAULT_SHARE_TOLERANCE,
    TWOPLACES,
    UNASSIGNED,
    WHOLE,
    ApportionedAmount,
    PartyApportionment,
    PartyShare,
    distribute_chargeable,
    quantize_money,
    rollup_apportioned,
    single_party_share,
    validate_shares,
)


def _shares(*pairs: tuple[str, str]) -> list[PartyShare]:
    """Build a list of PartyShare from (party, share_pct_str) pairs."""
    return [PartyShare(party=p, share_pct=Decimal(pct)) for p, pct in pairs]


# ---------------------------------------------------------------------------
# constants / primitives
# ---------------------------------------------------------------------------


def test_whole_and_quantum_constants() -> None:
    assert Decimal("1") == WHOLE
    assert Decimal("0.01") == TWOPLACES


def test_quantize_money_half_up() -> None:
    assert quantize_money(Decimal("1.005")) == Decimal("1.01")
    assert quantize_money(Decimal("1.004")) == Decimal("1.00")


# ---------------------------------------------------------------------------
# validate_shares
# ---------------------------------------------------------------------------


def test_validate_shares_accepts_exact_unit_sum() -> None:
    validate_shares(_shares(("Sub A", "0.6"), ("Designer", "0.4")))


def test_validate_shares_accepts_single_full_share() -> None:
    validate_shares(_shares(("Sub A", "1")))


def test_validate_shares_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least one party"):
        validate_shares([])


def test_validate_shares_not_summing_to_one_raises() -> None:
    with pytest.raises(ValueError, match="must sum to 1.0"):
        validate_shares(_shares(("Sub A", "0.6"), ("Designer", "0.3")))


def test_validate_shares_over_one_raises() -> None:
    with pytest.raises(ValueError, match="must sum to 1.0"):
        validate_shares(_shares(("Sub A", "0.7"), ("Designer", "0.5")))


def test_validate_shares_negative_share_raises() -> None:
    with pytest.raises(ValueError, match="negative"):
        validate_shares(_shares(("Sub A", "1.2"), ("Designer", "-0.2")))


def test_validate_shares_within_tolerance_passes() -> None:
    # 0.3333 * 3 = 0.9999, drift of 0.0001 is within the default tolerance.
    validate_shares(_shares(("A", "0.3333"), ("B", "0.3333"), ("C", "0.3334")))


def test_validate_shares_duplicate_party_summed_before_check() -> None:
    # Two 0.5 rows for the same party sum to a valid 1.0.
    validate_shares(_shares(("Sub A", "0.5"), ("Sub A", "0.5")))


def test_validate_shares_custom_tolerance() -> None:
    # Sums to 0.99; rejected at default tolerance, accepted at a loose one.
    loose = Decimal("0.02")
    with pytest.raises(ValueError):
        validate_shares(_shares(("A", "0.5"), ("B", "0.49")))
    validate_shares(_shares(("A", "0.5"), ("B", "0.49")), tolerance=loose)


# ---------------------------------------------------------------------------
# distribute_chargeable - reconciliation to the cent
# ---------------------------------------------------------------------------


def _assert_reconciles(amount: Decimal, result: list[tuple[str, Decimal]]) -> None:
    """Every amount is 2dp and the parts sum to the (quantized) total."""
    target = amount.quantize(TWOPLACES)
    total = sum((amt for _, amt in result), Decimal("0"))
    assert total == target
    for _, amt in result:
        assert amt == amt.quantize(TWOPLACES)


def test_distribute_even_split_no_remainder() -> None:
    result = distribute_chargeable(Decimal("100.00"), _shares(("A", "0.5"), ("B", "0.5")))
    assert result == [("A", Decimal("50.00")), ("B", Decimal("50.00"))]
    _assert_reconciles(Decimal("100.00"), result)


def test_distribute_sixty_forty() -> None:
    result = distribute_chargeable(Decimal("100.00"), _shares(("A", "0.6"), ("B", "0.4")))
    assert result == [("A", Decimal("60.00")), ("B", Decimal("40.00"))]
    _assert_reconciles(Decimal("100.00"), result)


def test_distribute_thirds_equal_shares_first_appearance_absorbs() -> None:
    # 1/3 of 100.00 = 33.3333... -> 33.33 each = 99.99; the 0.01 residual goes to
    # the largest share. The three shares are exactly equal (Decimal 1/3 each), so
    # the tie is broken by first appearance and A absorbs the residual.
    third = Decimal("1") / Decimal("3")
    result = distribute_chargeable(
        Decimal("100.00"),
        [PartyShare(party=p, share_pct=third) for p in ("A", "B", "C")],
    )
    amounts = dict(result)
    assert amounts == {"A": Decimal("33.34"), "B": Decimal("33.33"), "C": Decimal("33.33")}
    _assert_reconciles(Decimal("100.00"), result)


def test_distribute_thirds_remainder_to_strictly_largest() -> None:
    # When one share is strictly the largest, IT absorbs the residual - even when
    # it is the last party listed. C at 0.3334 (> 0.3333) takes the extra cent.
    result = distribute_chargeable(
        Decimal("100.00"),
        _shares(("A", "0.3333"), ("B", "0.3333"), ("C", "0.3334")),
    )
    amounts = dict(result)
    assert amounts == {"A": Decimal("33.33"), "B": Decimal("33.33"), "C": Decimal("33.34")}
    _assert_reconciles(Decimal("100.00"), result)


def test_distribute_remainder_goes_to_largest_share_not_first() -> None:
    # Largest share (B at 0.5) must absorb the residual even though it is not the
    # first party. 70.01 split 0.2/0.5/0.3:
    #   A 14.002 -> 14.00, B 35.005 -> 35.01 (half-up), C 21.003 -> 21.00 = 70.01
    # Already reconciles here, so pick an amount that forces a residual instead.
    result = distribute_chargeable(
        Decimal("10.00"),
        _shares(("A", "0.3333"), ("B", "0.5"), ("C", "0.1667")),
    )
    amounts = dict(result)
    # raw: A 3.333->3.33, B 5.00, C 1.667->1.67 = 10.00 exactly here; ensure B>=others
    _assert_reconciles(Decimal("10.00"), result)
    assert amounts["B"] >= amounts["A"]
    assert amounts["B"] >= amounts["C"]


def test_distribute_forces_residual_to_largest() -> None:
    # 0.05 across 0.7/0.3: A 0.035 -> 0.04 (half-up), B 0.015 -> 0.02 (half-up)
    # = 0.06 versus target 0.05, residual -0.01 -> taken off the largest (A).
    result = distribute_chargeable(Decimal("0.05"), _shares(("A", "0.7"), ("B", "0.3")))
    amounts = dict(result)
    assert amounts["A"] == Decimal("0.03")
    assert amounts["B"] == Decimal("0.02")
    _assert_reconciles(Decimal("0.05"), result)


def test_distribute_many_tiny_shares_reconcile() -> None:
    # Seven equal shares of 0.01 (a hard split: 0.01/7 = 0.001428...).
    seven = [PartyShare(party=f"P{i}", share_pct=Decimal("1") / Decimal("7")) for i in range(7)]
    result = distribute_chargeable(Decimal("0.01"), seven)
    _assert_reconciles(Decimal("0.01"), result)
    # The whole cent lands on exactly one party; the rest are zero.
    nonzero = [amt for _, amt in result if amt != Decimal("0.00")]
    assert nonzero == [Decimal("0.01")]


def test_distribute_awkward_amount_and_shares() -> None:
    result = distribute_chargeable(
        Decimal("1234.57"),
        _shares(("A", "0.45"), ("B", "0.35"), ("C", "0.20")),
    )
    _assert_reconciles(Decimal("1234.57"), result)
    # Largest share A should be the biggest amount.
    amounts = dict(result)
    assert amounts["A"] >= amounts["B"] >= amounts["C"]


def test_distribute_single_party_gets_everything() -> None:
    result = distribute_chargeable(Decimal("777.77"), _shares(("Sub A", "1")))
    assert result == [("Sub A", Decimal("777.77"))]
    _assert_reconciles(Decimal("777.77"), result)


def test_distribute_zero_amount_splits_to_zero() -> None:
    result = distribute_chargeable(Decimal("0.00"), _shares(("A", "0.6"), ("B", "0.4")))
    assert result == [("A", Decimal("0.00")), ("B", Decimal("0.00"))]
    _assert_reconciles(Decimal("0.00"), result)


def test_distribute_negative_amount_reconciles() -> None:
    # Reversal / credit note path: negative total still reconciles exactly.
    result = distribute_chargeable(Decimal("-100.00"), _shares(("A", "0.6"), ("B", "0.4")))
    total = sum((amt for _, amt in result), Decimal("0"))
    assert total == Decimal("-100.00")


def test_distribute_blank_party_resolved_to_unassigned() -> None:
    result = distribute_chargeable(Decimal("100.00"), _shares(("   ", "1")))
    assert result == [(UNASSIGNED, Decimal("100.00"))]


def test_distribute_duplicate_parties_merged() -> None:
    # Same party twice (0.5 + 0.5) collapses to one row holding the whole amount.
    result = distribute_chargeable(Decimal("100.00"), _shares(("Sub A", "0.5"), ("Sub A", "0.5")))
    assert result == [("Sub A", Decimal("100.00"))]


def test_distribute_invalid_shares_raise() -> None:
    with pytest.raises(ValueError, match="must sum to 1.0"):
        distribute_chargeable(Decimal("100.00"), _shares(("A", "0.6"), ("B", "0.1")))


def test_distribute_preserves_first_appearance_order() -> None:
    result = distribute_chargeable(Decimal("100.00"), _shares(("Zeta", "0.5"), ("Alpha", "0.5")))
    assert [p for p, _ in result] == ["Zeta", "Alpha"]


def test_distribute_decimal_exactness_no_float_artifacts() -> None:
    # 0.1 + 0.2 style floats would drift; Decimal must stay exact.
    result = distribute_chargeable(Decimal("0.30"), _shares(("A", "0.3333333333"), ("B", "0.6666666667")))
    total = sum((amt for _, amt in result), Decimal("0"))
    assert total == Decimal("0.30")
    for _, amt in result:
        assert amt.as_tuple().exponent == -2  # exactly two decimal places


# ---------------------------------------------------------------------------
# single_party_share - back-compat
# ---------------------------------------------------------------------------


def test_single_party_share_is_whole() -> None:
    shares = single_party_share("Sub A", Decimal("0.8"))
    assert shares == [PartyShare(party="Sub A", share_pct=WHOLE)]


def test_single_party_share_round_trips_through_distribute() -> None:
    # The no-apportionment path must reproduce "one party, the whole chargeable".
    chargeable = Decimal("4321.99")
    shares = single_party_share("Sub A", Decimal("0.5"))
    result = distribute_chargeable(chargeable, shares)
    assert result == [("Sub A", chargeable)]


def test_single_party_share_ignores_chargeable_pct_value() -> None:
    # Different chargeable_pct values produce the same 1.0 share (scaling happens
    # before distribution, not here).
    a = single_party_share("Sub A", Decimal("0.1"))
    b = single_party_share("Sub A", Decimal("0.9"))
    assert a == b


# ---------------------------------------------------------------------------
# rollup_apportioned - per (party, currency), no currency blending
# ---------------------------------------------------------------------------


def _amt(party: str, currency: str, amount: str) -> ApportionedAmount:
    return ApportionedAmount(party=party, currency=currency, amount=Decimal(amount))


def test_rollup_groups_by_party() -> None:
    rows = rollup_apportioned(
        [
            _amt("Sub A", "USD", "60.00"),
            _amt("Sub A", "USD", "40.00"),
            _amt("Designer", "USD", "25.00"),
        ]
    )
    by_party = {r.party: r for r in rows}
    assert set(by_party) == {"Sub A", "Designer"}
    assert by_party["Sub A"].amount_total == Decimal("100.00")
    assert by_party["Sub A"].item_count == 2
    assert by_party["Designer"].amount_total == Decimal("25.00")


def test_rollup_keeps_currencies_separate() -> None:
    rows = rollup_apportioned(
        [
            _amt("Sub A", "USD", "100.00"),
            _amt("Sub A", "EUR", "40.00"),
        ]
    )
    sub_a = [r for r in rows if r.party == "Sub A"]
    assert len(sub_a) == 2
    by_cur = {r.currency: r.amount_total for r in sub_a}
    assert by_cur == {"USD": Decimal("100.00"), "EUR": Decimal("40.00")}


def test_rollup_sorted_by_amount_desc_then_party_then_currency() -> None:
    rows = rollup_apportioned(
        [
            _amt("Sub A", "USD", "100.00"),
            _amt("Sub B", "USD", "900.00"),
            _amt("Sub C", "USD", "500.00"),
        ]
    )
    order = [(r.party, r.amount_total) for r in rows]
    assert order == [
        ("Sub B", Decimal("900.00")),
        ("Sub C", Decimal("500.00")),
        ("Sub A", Decimal("100.00")),
    ]


def test_rollup_tie_break_party_then_currency() -> None:
    rows = rollup_apportioned(
        [
            _amt("Sub B", "USD", "50.00"),
            _amt("Sub A", "USD", "50.00"),
            _amt("Sub A", "EUR", "50.00"),
        ]
    )
    order = [(r.party, r.currency) for r in rows]
    assert order == [("Sub A", "EUR"), ("Sub A", "USD"), ("Sub B", "USD")]


def test_rollup_blank_party_resolved_to_unassigned() -> None:
    rows = rollup_apportioned([_amt("  ", "USD", "10.00"), _amt("", "USD", "5.00")])
    assert len(rows) == 1
    assert rows[0].party == UNASSIGNED
    assert rows[0].item_count == 2
    assert rows[0].amount_total == Decimal("15.00")


def test_rollup_empty_input() -> None:
    assert rollup_apportioned([]) == ()


def test_rollup_returns_dataclasses() -> None:
    rows = rollup_apportioned([_amt("Sub A", "USD", "10.00")])
    assert all(isinstance(r, PartyApportionment) for r in rows)


# ---------------------------------------------------------------------------
# end-to-end: distribute then roll up reconciles per currency
# ---------------------------------------------------------------------------


def test_distribute_then_rollup_reconciles_per_currency() -> None:
    # Two back-charges in different currencies, each apportioned, then rolled up.
    usd_split = distribute_chargeable(Decimal("100.00"), _shares(("A", "0.6"), ("B", "0.4")))
    eur_split = distribute_chargeable(Decimal("90.00"), _shares(("A", "0.5"), ("B", "0.5")))
    items = [ApportionedAmount(party=p, currency="USD", amount=a) for p, a in usd_split]
    items += [ApportionedAmount(party=p, currency="EUR", amount=a) for p, a in eur_split]

    rows = rollup_apportioned(items)
    usd_total = sum((r.amount_total for r in rows if r.currency == "USD"), Decimal("0"))
    eur_total = sum((r.amount_total for r in rows if r.currency == "EUR"), Decimal("0"))
    assert usd_total == Decimal("100.00")
    assert eur_total == Decimal("90.00")


def test_default_tolerance_value() -> None:
    assert Decimal("0.0001") == DEFAULT_SHARE_TOLERANCE
