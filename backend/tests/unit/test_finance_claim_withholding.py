# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure-logic unit tests for Gap E retainage withholding maths + FX helpers.

These tests touch no database. They pin the exact ``Decimal`` arithmetic that
splits a certified gross into (cash paid, retainage withheld), and the FX
conversion the receivable-from-claim path reuses from the finance service. Money
is asserted as exact ``Decimal`` (never float) — a silent drift here would
mis-state every certified-claim receivable.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.finance.service import (
    _convert_to_base,
    _project_fx_map,
    compute_payment_withholding,
)

# ── compute_payment_withholding: percentage-driven split ─────────────────────


def test_compute_payment_withholding_5pct() -> None:
    pay, held = compute_payment_withholding(Decimal("100000"), retention_pct=Decimal("5"))
    assert held == Decimal("5000.00")
    assert pay == Decimal("95000.00")


def test_compute_payment_withholding_0pct() -> None:
    pay, held = compute_payment_withholding(Decimal("100000"), retention_pct=Decimal("0"))
    assert held == Decimal("0.00")
    assert pay == Decimal("100000.00")


def test_compute_payment_withholding_100pct() -> None:
    pay, held = compute_payment_withholding(Decimal("100000"), retention_pct=Decimal("100"))
    assert held == Decimal("100000.00")
    assert pay == Decimal("0.00")


def test_compute_payment_withholding_over_100pct_clamped() -> None:
    # A nonsensical >100% retention can never produce a negative cash payment.
    pay, held = compute_payment_withholding(Decimal("100000"), retention_pct=Decimal("150"))
    assert held == Decimal("100000.00")
    assert pay == Decimal("0.00")


def test_compute_payment_withholding_rounds_half_up() -> None:
    # 33333.33 * 5% = 1666.6665 → 1666.67 (half-up).
    pay, held = compute_payment_withholding(Decimal("33333.33"), retention_pct=Decimal("5"))
    assert held == Decimal("1666.67")
    assert pay == Decimal("31666.66")


@pytest.mark.parametrize(
    ("gross", "expected_cash", "expected_held"),
    [
        ("0.01", "0.00", "0.01"),
        ("1.01", "0.50", "0.51"),
        ("1.03", "0.51", "0.52"),
        ("1001.01", "500.50", "500.51"),
    ],
)
def test_percentage_withholding_conserves_cent_precision_gross(
    gross: str, expected_cash: str, expected_held: str
) -> None:
    """EUR-style cents: half-up retention owns the half-cent, cash is residual."""
    cash, held = compute_payment_withholding(gross, retention_pct="50")

    assert held == Decimal(expected_held)
    assert cash == Decimal(expected_cash)
    assert cash + held == Decimal(gross)
    assert cash.as_tuple().exponent == held.as_tuple().exponent == -2


@pytest.mark.parametrize(
    ("explicit_held", "expected_cash", "expected_held"),
    [("0.005", "1.00", "0.01"), ("0.015", "0.99", "0.02")],
)
def test_explicit_withholding_conserves_cent_precision_gross(
    explicit_held: str, expected_cash: str, expected_held: str
) -> None:
    """The accepted explicit amount keeps half-up rounding and precedence."""
    cash, held = compute_payment_withholding("1.01", retention_pct="100", withholding_amount=explicit_held)

    assert held == Decimal(expected_held)
    assert cash == Decimal(expected_cash)
    assert cash + held == Decimal("1.01")
    assert cash.as_tuple().exponent == held.as_tuple().exponent == -2


def test_percentage_uses_raw_gross_before_rounding_the_payment_split() -> None:
    cash, held = compute_payment_withholding("1.005", retention_pct="50")
    assert held == Decimal("0.50")
    assert cash == Decimal("0.51")
    assert cash + held == Decimal("1.01")


# ── compute_payment_withholding: explicit-amount split ───────────────────────


def test_compute_payment_withholding_explicit_amount() -> None:
    pay, held = compute_payment_withholding(Decimal("80000"), withholding_amount=Decimal("4000"))
    assert held == Decimal("4000.00")
    assert pay == Decimal("76000.00")


def test_compute_payment_withholding_explicit_amount_overrides_pct() -> None:
    # Explicit withholding wins over a supplied percentage.
    pay, held = compute_payment_withholding(
        Decimal("80000"), retention_pct=Decimal("5"), withholding_amount=Decimal("1000")
    )
    assert held == Decimal("1000.00")
    assert pay == Decimal("79000.00")


def test_compute_payment_withholding_explicit_over_gross_clamped() -> None:
    pay, held = compute_payment_withholding(Decimal("5000"), withholding_amount=Decimal("9999"))
    assert held == Decimal("5000.00")
    assert pay == Decimal("0.00")


def test_compute_payment_withholding_negative_gross_clamped() -> None:
    pay, held = compute_payment_withholding(Decimal("-10"), retention_pct=Decimal("5"))
    assert held == Decimal("0.00")
    assert pay == Decimal("0.00")


def test_compute_payment_withholding_string_inputs() -> None:
    # Decimal-as-string inputs (the wire form) coerce correctly.
    pay, held = compute_payment_withholding("100000.00", retention_pct="5")
    assert held == Decimal("5000.00")
    assert pay == Decimal("95000.00")


# ── FX conversion reused by create_receivable_from_claim ─────────────────────


class _FakeProject:
    def __init__(self, fx_rates: list[dict[str, str]]) -> None:
        self.fx_rates = fx_rates


def test_convert_to_base_gbp_to_usd() -> None:
    # 1 GBP = 1.25 USD; a 10,000 GBP claim converts to 12,500 USD base.
    fx = _project_fx_map(_FakeProject([{"code": "GBP", "rate": "1.25"}]))
    converted, missing = _convert_to_base({"GBP": 10000.0}, base_currency="USD", fx_rates_map=fx)
    # _convert_to_base returns a quantized 2-place Decimal string (money never
    # round-trips through a binary float); callers parse it back with Decimal().
    assert converted == "12500.00"
    assert missing == []


def test_convert_to_base_missing_rate_keeps_value_not_zero() -> None:
    # No FX rate for GBP → keep the value in its own units, never zero it, and
    # surface the missing code so the UI can warn.
    fx = _project_fx_map(_FakeProject([]))
    converted, missing = _convert_to_base({"GBP": 10000.0}, base_currency="USD", fx_rates_map=fx)
    assert converted == "10000.00"
    assert missing == ["GBP"]


def test_convert_to_base_same_currency_passthrough() -> None:
    fx = _project_fx_map(_FakeProject([]))
    converted, missing = _convert_to_base({"USD": 5000.0}, base_currency="USD", fx_rates_map=fx)
    assert converted == "5000.00"
    assert missing == []


def test_project_fx_map_ignores_malformed_entries() -> None:
    fx = _project_fx_map(
        _FakeProject(
            [
                {"code": "GBP", "rate": "1.25"},
                {"code": "", "rate": "9"},  # blank code skipped
                {"code": "EUR"},  # no rate skipped
                "garbage",  # non-dict skipped
            ]
        )
    )
    assert fx == {"GBP": "1.25"}
