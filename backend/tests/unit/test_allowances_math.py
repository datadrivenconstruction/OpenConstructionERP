# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure allowances / contingency register engine.

Stdlib + pytest only - mirrors the engine's constraint so it runs on the local
Python test runner without app.* database plumbing on the path. Money is
exercised with Decimal literals; every per-currency roll-up is asserted to keep
currencies separate, to reconcile held - drawn = remaining, and to flag over-draw
as advisory rather than clamping.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.allowances.allowance_math import (
    ALLOWANCE_CONTINGENCY,
    ALLOWANCE_PC_SUM,
    ALLOWANCE_PROVISIONAL_SUM,
    ALLOWANCE_TYPES,
    AllowanceLine,
    is_overdrawn,
    quantize_money,
    remaining,
    roll_up_register,
    to_decimal,
    total_drawn,
)


def _line(
    allowance_type: str = ALLOWANCE_PROVISIONAL_SUM,
    currency: str = "USD",
    held: Decimal = Decimal("1000.00"),
    drawdowns: tuple[Decimal, ...] = (),
) -> AllowanceLine:
    return AllowanceLine(
        allowance_type=allowance_type,
        currency=currency,
        held=held,
        drawdowns=drawdowns,
    )


# ── to_decimal / quantize ──────────────────────────────────────────────────


def test_to_decimal_coerces_and_defaults() -> None:
    assert to_decimal(Decimal("5.5")) == Decimal("5.5")
    assert to_decimal("12.34") == Decimal("12.34")
    assert to_decimal(7) == Decimal("7")
    # Bad input collapses to the default (zero), never raises.
    assert to_decimal(None) == Decimal("0")
    assert to_decimal("not-a-number") == Decimal("0")
    assert to_decimal("nope", default=Decimal("3")) == Decimal("3")


def test_quantize_money_half_up_two_places() -> None:
    assert quantize_money(Decimal("1.005")) == Decimal("1.01")
    assert quantize_money(Decimal("1000")) == Decimal("1000.00")


# ── total_drawn / remaining / is_overdrawn ─────────────────────────────────


def test_total_drawn_sums_and_quantizes() -> None:
    assert total_drawn([]) == Decimal("0.00")
    assert total_drawn([Decimal("100.10"), Decimal("50.05"), Decimal("0.25")]) == Decimal("150.40")
    # Mixed wire forms coerce cleanly.
    assert total_drawn(["100", 25, Decimal("0.50")]) == Decimal("125.50")


def test_remaining_basic() -> None:
    result = remaining(Decimal("1000.00"), [Decimal("250.00"), Decimal("100.00")])
    assert result == Decimal("650.00")


def test_remaining_no_drawdowns_returns_full_held() -> None:
    assert remaining(Decimal("500.00"), []) == Decimal("500.00")


def test_remaining_goes_negative_on_overdraw_not_clamped() -> None:
    # Drawing beyond the held amount is a real situation: remaining is negative,
    # never clamped to zero, so the over-draw is visible.
    assert remaining(Decimal("100.00"), [Decimal("150.00")]) == Decimal("-50.00")


def test_remaining_exact_before_single_quantize() -> None:
    # Sub-cent parts sum exactly and quantize once at the end (no drift).
    result = remaining(Decimal("10.00"), [Decimal("3.334"), Decimal("3.333")])
    assert result == Decimal("3.33")


def test_is_overdrawn_flag() -> None:
    assert is_overdrawn(Decimal("100.00"), Decimal("150.00")) is True
    assert is_overdrawn(Decimal("100.00"), Decimal("100.00")) is False
    assert is_overdrawn(Decimal("100.00"), Decimal("40.00")) is False


# ── roll_up_register ───────────────────────────────────────────────────────


def test_roll_up_empty_is_empty_summary() -> None:
    summary = roll_up_register([])
    assert summary.by_currency == ()
    assert summary.primary_currency == ""
    assert summary.allowance_count == 0


def test_roll_up_single_currency_reconciles() -> None:
    summary = roll_up_register(
        [
            _line(ALLOWANCE_PROVISIONAL_SUM, "USD", Decimal("1000.00"), (Decimal("400.00"),)),
            _line(ALLOWANCE_CONTINGENCY, "USD", Decimal("500.00"), ()),
        ]
    )
    assert summary.primary_currency == "USD"
    assert summary.allowance_count == 2
    assert len(summary.by_currency) == 1
    row = summary.by_currency[0]
    assert row.held == Decimal("1500.00")
    assert row.drawn == Decimal("400.00")
    assert row.remaining == Decimal("1100.00")
    assert row.overdrawn is False


def test_roll_up_orders_types_canonically() -> None:
    # Feed the types out of order; the roll-up presents them in ALLOWANCE_TYPES order.
    summary = roll_up_register(
        [
            _line(ALLOWANCE_CONTINGENCY, "USD", Decimal("100.00")),
            _line(ALLOWANCE_PC_SUM, "USD", Decimal("100.00")),
            _line(ALLOWANCE_PROVISIONAL_SUM, "USD", Decimal("100.00")),
        ]
    )
    order = [t.allowance_type for t in summary.by_currency[0].by_type]
    assert order == list(ALLOWANCE_TYPES)


def test_roll_up_never_blends_currencies() -> None:
    summary = roll_up_register(
        [
            _line(ALLOWANCE_PROVISIONAL_SUM, "USD", Decimal("1000.00"), (Decimal("100.00"),)),
            _line(ALLOWANCE_PROVISIONAL_SUM, "EUR", Decimal("2000.00"), (Decimal("500.00"),)),
        ]
    )
    assert {r.currency for r in summary.by_currency} == {"USD", "EUR"}
    # Heaviest held leads: EUR (2000) before USD (1000).
    assert summary.primary_currency == "EUR"
    assert [r.currency for r in summary.by_currency] == ["EUR", "USD"]
    usd = next(r for r in summary.by_currency if r.currency == "USD")
    eur = next(r for r in summary.by_currency if r.currency == "EUR")
    assert usd.remaining == Decimal("900.00")
    assert eur.remaining == Decimal("1500.00")


def test_roll_up_flags_overdraw_at_type_and_currency() -> None:
    summary = roll_up_register(
        [
            _line(ALLOWANCE_PROVISIONAL_SUM, "GBP", Decimal("100.00"), (Decimal("175.00"),)),
        ]
    )
    row = summary.by_currency[0]
    assert row.overdrawn is True
    assert row.remaining == Decimal("-75.00")
    type_row = row.by_type[0]
    assert type_row.allowance_type == ALLOWANCE_PROVISIONAL_SUM
    assert type_row.overdrawn is True
    assert type_row.remaining == Decimal("-75.00")


def test_roll_up_same_type_multiple_allowances_aggregate() -> None:
    summary = roll_up_register(
        [
            _line(ALLOWANCE_CONTINGENCY, "USD", Decimal("300.00"), (Decimal("50.00"),)),
            _line(
                ALLOWANCE_CONTINGENCY,
                "USD",
                Decimal("700.00"),
                (Decimal("100.00"), Decimal("25.00")),
            ),
        ]
    )
    row = summary.by_currency[0]
    assert len(row.by_type) == 1
    type_row = row.by_type[0]
    assert type_row.count == 2
    assert type_row.held == Decimal("1000.00")
    assert type_row.drawn == Decimal("175.00")
    assert type_row.remaining == Decimal("825.00")
