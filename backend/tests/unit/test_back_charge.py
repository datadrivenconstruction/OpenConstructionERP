# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure back-charge / cost-recovery engine.

Stdlib + pytest only - mirrors the engine's constraint so it runs on the
local Python 3.11 test runner without app.* or SQLAlchemy on the path. Money
is exercised exclusively with Decimal literals.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.cost_recovery.back_charge import (
    CLOSED_STATUSES,
    OPEN_STATUSES,
    STATUS_AGREED,
    STATUS_DISPUTED,
    STATUS_PROPOSED,
    STATUS_RECOVERED,
    STATUS_WAIVED,
    UNASSIGNED,
    BackChargeItem,
    CurrencyRecovery,
    PartyRecovery,
    RecoveryLedger,
    build_ledger,
    clamp_pct,
    quantize_money,
)


def _item(
    ref_id: str = "BC-1",
    responsible_party: str = "Subcontractor A",
    gross_amount: Decimal = Decimal("1000.00"),
    chargeable_pct: Decimal = Decimal("1"),
    currency: str = "USD",
    status: str = STATUS_AGREED,
    recovered_amount: Decimal = Decimal("0"),
) -> BackChargeItem:
    """Build a BackChargeItem with sensible defaults for a single test."""
    return BackChargeItem(
        ref_id=ref_id,
        responsible_party=responsible_party,
        description="rework caused by defect",
        basis="defect rectification",
        gross_amount=gross_amount,
        chargeable_pct=chargeable_pct,
        currency=currency,
        status=status,
        recovered_amount=recovered_amount,
    )


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------


def test_open_and_closed_statuses_partition() -> None:
    assert frozenset({STATUS_PROPOSED, STATUS_AGREED, STATUS_DISPUTED}) == OPEN_STATUSES
    assert frozenset({STATUS_RECOVERED, STATUS_WAIVED}) == CLOSED_STATUSES
    assert OPEN_STATUSES.isdisjoint(CLOSED_STATUSES)


# ---------------------------------------------------------------------------
# clamp_pct
# ---------------------------------------------------------------------------


def test_clamp_pct_below_zero() -> None:
    assert clamp_pct(Decimal("-0.5")) == Decimal("0")


def test_clamp_pct_above_one() -> None:
    assert clamp_pct(Decimal("1.5")) == Decimal("1")


def test_clamp_pct_within_range_unchanged() -> None:
    assert clamp_pct(Decimal("0.4")) == Decimal("0.4")


def test_clamp_pct_boundaries() -> None:
    assert clamp_pct(Decimal("0")) == Decimal("0")
    assert clamp_pct(Decimal("1")) == Decimal("1")


# ---------------------------------------------------------------------------
# quantize_money
# ---------------------------------------------------------------------------


def test_quantize_money_rounds_half_up() -> None:
    assert quantize_money(Decimal("1.005")) == Decimal("1.01")


def test_quantize_money_rounds_half_up_again() -> None:
    assert quantize_money(Decimal("2.345")) == Decimal("2.35")


def test_quantize_money_truncates_below_half() -> None:
    assert quantize_money(Decimal("1.004")) == Decimal("1.00")


# ---------------------------------------------------------------------------
# BackChargeItem.chargeable_amount
# ---------------------------------------------------------------------------


def test_chargeable_amount_full_pct() -> None:
    item = _item(gross_amount=Decimal("1000.00"), chargeable_pct=Decimal("1"))
    assert item.chargeable_amount == Decimal("1000.00")


def test_chargeable_amount_partial_pct() -> None:
    item = _item(gross_amount=Decimal("1000.00"), chargeable_pct=Decimal("0.6"))
    assert item.chargeable_amount == Decimal("600.00")


def test_chargeable_amount_clamps_pct_above_one() -> None:
    item = _item(gross_amount=Decimal("500.00"), chargeable_pct=Decimal("1.5"))
    assert item.chargeable_amount == Decimal("500.00")


def test_chargeable_amount_clamps_negative_pct() -> None:
    item = _item(gross_amount=Decimal("500.00"), chargeable_pct=Decimal("-0.2"))
    assert item.chargeable_amount == Decimal("0.00")


def test_chargeable_amount_quantizes_half_up() -> None:
    # 333.33 * 0.5 = 166.665 -> 166.67 half-up
    item = _item(gross_amount=Decimal("333.33"), chargeable_pct=Decimal("0.5"))
    assert item.chargeable_amount == Decimal("166.67")


# ---------------------------------------------------------------------------
# BackChargeItem.is_open / outstanding
# ---------------------------------------------------------------------------


def test_is_open_for_open_statuses() -> None:
    assert _item(status=STATUS_PROPOSED).is_open is True
    assert _item(status=STATUS_AGREED).is_open is True
    assert _item(status=STATUS_DISPUTED).is_open is True


def test_is_open_false_for_closed_statuses() -> None:
    assert _item(status=STATUS_RECOVERED).is_open is False
    assert _item(status=STATUS_WAIVED).is_open is False


def test_outstanding_open_no_recovery() -> None:
    item = _item(
        gross_amount=Decimal("1000.00"),
        chargeable_pct=Decimal("0.8"),
        status=STATUS_AGREED,
    )
    assert item.outstanding == Decimal("800.00")


def test_outstanding_open_partial_recovery() -> None:
    item = _item(
        gross_amount=Decimal("1000.00"),
        chargeable_pct=Decimal("1"),
        status=STATUS_DISPUTED,
        recovered_amount=Decimal("250.00"),
    )
    assert item.outstanding == Decimal("750.00")


def test_outstanding_zero_when_recovered_status() -> None:
    item = _item(
        gross_amount=Decimal("1000.00"),
        chargeable_pct=Decimal("1"),
        status=STATUS_RECOVERED,
        recovered_amount=Decimal("1000.00"),
    )
    assert item.outstanding == Decimal("0.00")


def test_outstanding_zero_when_waived_status() -> None:
    item = _item(
        gross_amount=Decimal("1000.00"),
        chargeable_pct=Decimal("1"),
        status=STATUS_WAIVED,
        recovered_amount=Decimal("0"),
    )
    assert item.outstanding == Decimal("0.00")


def test_outstanding_clamps_when_recovered_exceeds_chargeable() -> None:
    item = _item(
        gross_amount=Decimal("1000.00"),
        chargeable_pct=Decimal("0.5"),
        status=STATUS_AGREED,
        recovered_amount=Decimal("900.00"),  # exceeds 500.00 chargeable
    )
    assert item.outstanding == Decimal("0.00")


# ---------------------------------------------------------------------------
# build_ledger - grouping
# ---------------------------------------------------------------------------


def test_build_ledger_groups_by_party() -> None:
    items = [
        _item(ref_id="BC-1", responsible_party="Sub A", gross_amount=Decimal("1000.00")),
        _item(ref_id="BC-2", responsible_party="Sub A", gross_amount=Decimal("500.00")),
        _item(ref_id="BC-3", responsible_party="Sub B", gross_amount=Decimal("200.00")),
    ]
    ledger = build_ledger(items)
    parties = {r.party for r in ledger.by_party}
    assert parties == {"Sub A", "Sub B"}
    sub_a = next(r for r in ledger.by_party if r.party == "Sub A")
    assert sub_a.item_count == 2
    assert sub_a.gross_total == Decimal("1500.00")
    assert sub_a.chargeable_total == Decimal("1500.00")
    assert sub_a.outstanding_total == Decimal("1500.00")


def test_build_ledger_open_count_excludes_closed() -> None:
    items = [
        _item(ref_id="BC-1", status=STATUS_AGREED),
        _item(ref_id="BC-2", status=STATUS_PROPOSED),
        _item(ref_id="BC-3", status=STATUS_RECOVERED, recovered_amount=Decimal("1000.00")),
        _item(ref_id="BC-4", status=STATUS_WAIVED),
    ]
    ledger = build_ledger(items)
    assert ledger.item_count == 4
    assert ledger.open_count == 2


def test_build_ledger_party_split_across_two_currencies() -> None:
    items = [
        _item(ref_id="BC-1", responsible_party="Sub A", currency="USD", gross_amount=Decimal("1000.00")),
        _item(ref_id="BC-2", responsible_party="Sub A", currency="EUR", gross_amount=Decimal("400.00")),
    ]
    ledger = build_ledger(items)
    sub_a_rows = [r for r in ledger.by_party if r.party == "Sub A"]
    assert len(sub_a_rows) == 2
    currencies = {r.currency for r in sub_a_rows}
    assert currencies == {"USD", "EUR"}
    usd_row = next(r for r in sub_a_rows if r.currency == "USD")
    eur_row = next(r for r in sub_a_rows if r.currency == "EUR")
    assert usd_row.chargeable_total == Decimal("1000.00")
    assert eur_row.chargeable_total == Decimal("400.00")


def test_build_ledger_multi_currency_totals_stay_separate() -> None:
    items = [
        _item(ref_id="BC-1", currency="USD", gross_amount=Decimal("1000.00")),
        _item(ref_id="BC-2", currency="EUR", gross_amount=Decimal("750.00")),
        _item(ref_id="BC-3", currency="USD", gross_amount=Decimal("250.00")),
    ]
    ledger = build_ledger(items)
    by_cur = {r.currency: r for r in ledger.by_currency}
    assert set(by_cur) == {"USD", "EUR"}
    assert by_cur["USD"].chargeable_total == Decimal("1250.00")
    assert by_cur["USD"].item_count == 2
    assert by_cur["EUR"].chargeable_total == Decimal("750.00")
    assert by_cur["EUR"].item_count == 1


def test_build_ledger_blank_party_becomes_unassigned() -> None:
    items = [
        _item(ref_id="BC-1", responsible_party="   "),
        _item(ref_id="BC-2", responsible_party=""),
    ]
    ledger = build_ledger(items)
    assert len(ledger.by_party) == 1
    assert ledger.by_party[0].party == UNASSIGNED
    assert ledger.by_party[0].item_count == 2


# ---------------------------------------------------------------------------
# build_ledger - primary currency
# ---------------------------------------------------------------------------


def test_build_ledger_primary_currency_by_greatest_chargeable() -> None:
    items = [
        _item(ref_id="BC-1", currency="USD", gross_amount=Decimal("1000.00")),
        _item(ref_id="BC-2", currency="EUR", gross_amount=Decimal("400.00")),
    ]
    ledger = build_ledger(items)
    assert ledger.primary_currency == "USD"
    assert ledger.primary_outstanding == Decimal("1000.00")


def test_build_ledger_primary_currency_alphabetical_tie_break() -> None:
    # Equal chargeable totals -> alphabetical wins (EUR before USD).
    items = [
        _item(ref_id="BC-1", currency="USD", gross_amount=Decimal("500.00")),
        _item(ref_id="BC-2", currency="EUR", gross_amount=Decimal("500.00")),
    ]
    ledger = build_ledger(items)
    assert ledger.primary_currency == "EUR"
    assert ledger.primary_outstanding == Decimal("500.00")


# ---------------------------------------------------------------------------
# build_ledger - sort order
# ---------------------------------------------------------------------------


def test_build_ledger_by_party_sorted_by_outstanding_desc() -> None:
    items = [
        _item(ref_id="BC-1", responsible_party="Sub A", currency="USD", gross_amount=Decimal("100.00")),
        _item(ref_id="BC-2", responsible_party="Sub B", currency="USD", gross_amount=Decimal("900.00")),
        _item(ref_id="BC-3", responsible_party="Sub C", currency="USD", gross_amount=Decimal("500.00")),
    ]
    ledger = build_ledger(items)
    order = [(r.party, r.outstanding_total) for r in ledger.by_party]
    assert order == [
        ("Sub B", Decimal("900.00")),
        ("Sub C", Decimal("500.00")),
        ("Sub A", Decimal("100.00")),
    ]


def test_build_ledger_by_party_tie_break_party_then_currency() -> None:
    # Same outstanding total (all zero, since waived) -> party then currency.
    items = [
        _item(ref_id="BC-1", responsible_party="Sub B", currency="USD", status=STATUS_WAIVED),
        _item(ref_id="BC-2", responsible_party="Sub A", currency="USD", status=STATUS_WAIVED),
        _item(ref_id="BC-3", responsible_party="Sub A", currency="EUR", status=STATUS_WAIVED),
    ]
    ledger = build_ledger(items)
    order = [(r.party, r.currency) for r in ledger.by_party]
    assert order == [("Sub A", "EUR"), ("Sub A", "USD"), ("Sub B", "USD")]


def test_build_ledger_by_currency_sorted_by_chargeable_desc() -> None:
    items = [
        _item(ref_id="BC-1", currency="USD", gross_amount=Decimal("300.00")),
        _item(ref_id="BC-2", currency="EUR", gross_amount=Decimal("900.00")),
        _item(ref_id="BC-3", currency="GBP", gross_amount=Decimal("600.00")),
    ]
    ledger = build_ledger(items)
    order = [r.currency for r in ledger.by_currency]
    assert order == ["EUR", "GBP", "USD"]


def test_build_ledger_by_currency_tie_break_alphabetical() -> None:
    items = [
        _item(ref_id="BC-1", currency="USD", gross_amount=Decimal("500.00")),
        _item(ref_id="BC-2", currency="EUR", gross_amount=Decimal("500.00")),
    ]
    ledger = build_ledger(items)
    order = [r.currency for r in ledger.by_currency]
    assert order == ["EUR", "USD"]


# ---------------------------------------------------------------------------
# build_ledger - empty input + recovered roll-up
# ---------------------------------------------------------------------------


def test_build_ledger_empty_input() -> None:
    ledger = build_ledger([])
    assert isinstance(ledger, RecoveryLedger)
    assert ledger.item_count == 0
    assert ledger.open_count == 0
    assert ledger.primary_currency == ""
    assert ledger.primary_outstanding == Decimal("0")
    assert ledger.by_party == ()
    assert ledger.by_currency == ()


def test_build_ledger_recovered_total_clamped_per_currency() -> None:
    # An over-recovery on one item must not inflate the currency recovered
    # total beyond that item's chargeable amount.
    items = [
        _item(
            ref_id="BC-1",
            currency="USD",
            gross_amount=Decimal("1000.00"),
            chargeable_pct=Decimal("0.5"),  # chargeable 500.00
            status=STATUS_AGREED,
            recovered_amount=Decimal("900.00"),  # over-recovered
        ),
    ]
    ledger = build_ledger(items)
    usd = next(r for r in ledger.by_currency if r.currency == "USD")
    assert usd.chargeable_total == Decimal("500.00")
    assert usd.recovered_total == Decimal("500.00")
    assert usd.outstanding_total == Decimal("0.00")


def test_build_ledger_dataclass_types_returned() -> None:
    items = [_item(ref_id="BC-1")]
    ledger = build_ledger(items)
    assert all(isinstance(r, PartyRecovery) for r in ledger.by_party)
    assert all(isinstance(r, CurrencyRecovery) for r in ledger.by_currency)
