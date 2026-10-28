# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure recovery-breakdown / provability / plain-language helpers.

Stdlib + pytest only - mirrors the engine's constraint so it runs on the local
Python 3.11 test runner without app.* runtime services (no database, no ORM, no
web framework). Money is exercised exclusively with Decimal literals. These tests
pin the international robustness, edge-case and explainability guarantees of
:mod:`app.modules.cost_recovery.recovery_breakdown`.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from app.modules.cost_recovery.recovery_breakdown import (
    DEFAULT_ADMIN_PCT,
    RecoveryBreakdown,
    RecoveryLine,
    build_recovery_breakdown,
    build_recovery_breakdown_from_lines,
    cap_recovered,
    describe_band,
    describe_status,
    ensure_not_over_recovered,
    is_over_recovered,
    lines_reconcile_to,
    quantize_money,
    remaining_to_recover,
    state_recovery,
    sum_recovery_lines,
)


def _line(
    ref: str = "INV-1",
    description: str = "materials",
    amount: Decimal = Decimal("100.00"),
    currency: str = "EUR",
) -> RecoveryLine:
    """Build a RecoveryLine with sensible defaults for a single test."""
    return RecoveryLine(ref=ref, description=description, amount=amount, currency=currency)


# ---------------------------------------------------------------------------
# defaults / international robustness
# ---------------------------------------------------------------------------


def test_default_admin_pct_is_zero() -> None:
    # No country or contract is assumed: nothing is added unless asked.
    assert Decimal("0") == DEFAULT_ADMIN_PCT


def test_no_hardcoded_currency_base_only() -> None:
    # With the default fee and no credits the recovery total is just the base.
    b = build_recovery_breakdown(Decimal("1000.00"))
    assert b.recovery_total == Decimal("1000.00")
    assert b.admin_fee == Decimal("0.00")
    assert b.currency == ""


def test_currency_is_carried_not_invented() -> None:
    b = build_recovery_breakdown(Decimal("500"), currency="JPY")
    assert b.currency == "JPY"


# ---------------------------------------------------------------------------
# breakdown math + explainability
# ---------------------------------------------------------------------------


def test_admin_fee_and_total_decompose() -> None:
    # 1000 base + 15% admin - 50 credit = 1100 recovery, every part exposed.
    b = build_recovery_breakdown(
        Decimal("1000.00"),
        admin_pct=Decimal("0.15"),
        credits=Decimal("50.00"),
        currency="USD",
    )
    assert b.base_cost == Decimal("1000.00")
    assert b.admin_fee == Decimal("150.00")
    assert b.credits_total == Decimal("50.00")
    assert b.recovery_total == Decimal("1100.00")
    # The parts re-add to the total by hand - this is what stands up to dispute.
    assert b.base_cost + b.admin_fee - b.credits_total == b.recovery_total


def test_admin_fee_is_quantized_half_up() -> None:
    # 333.33 * 10% = 33.333 -> 33.33 (half-up at two places).
    b = build_recovery_breakdown(Decimal("333.33"), admin_pct=Decimal("0.10"))
    assert b.admin_fee == Decimal("33.33")


def test_money_is_decimal_exact_not_float() -> None:
    b = build_recovery_breakdown(Decimal("0.10"), credits=Decimal("0.00"))
    # 0.10 + 0.20 style float error must not appear anywhere.
    assert b.recovery_total == Decimal("0.10")
    assert isinstance(b.recovery_total, Decimal)


def test_returned_breakdown_is_frozen() -> None:
    b = build_recovery_breakdown(Decimal("100"))
    assert isinstance(b, RecoveryBreakdown)
    with pytest.raises(FrozenInstanceError):
        b.recovery_total = Decimal("1")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# edge cases: negatives, over-credit, non-finite
# ---------------------------------------------------------------------------


def test_negative_base_cost_raises() -> None:
    with pytest.raises(ValueError, match="base cost cannot be negative"):
        build_recovery_breakdown(Decimal("-1"))


def test_negative_admin_pct_raises() -> None:
    with pytest.raises(ValueError, match="admin percentage cannot be negative"):
        build_recovery_breakdown(Decimal("100"), admin_pct=Decimal("-0.1"))


def test_negative_credits_raises() -> None:
    with pytest.raises(ValueError, match="credits cannot be negative"):
        build_recovery_breakdown(Decimal("100"), credits=Decimal("-1"))


def test_over_credit_floors_total_at_zero() -> None:
    # Credits beyond cost + fee mean fully credited: a defined zero, not negative.
    b = build_recovery_breakdown(
        Decimal("100.00"),
        admin_pct=Decimal("0.10"),
        credits=Decimal("500.00"),
    )
    assert b.recovery_total == Decimal("0.00")
    assert b.recovery_total >= Decimal("0")


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_non_finite_base_cost_raises(bad: Decimal) -> None:
    with pytest.raises(ValueError, match="finite"):
        build_recovery_breakdown(bad)


# ---------------------------------------------------------------------------
# evidence lines + provability
# ---------------------------------------------------------------------------


def test_sum_recovery_lines_totals_single_currency() -> None:
    currency, total = sum_recovery_lines([_line(amount=Decimal("100.00")), _line(ref="INV-2", amount=Decimal("50.50"))])
    assert currency == "EUR"
    assert total == Decimal("150.50")


def test_sum_recovery_lines_empty_raises() -> None:
    with pytest.raises(ValueError, match="no evidence lines"):
        sum_recovery_lines([])


def test_sum_recovery_lines_negative_amount_raises() -> None:
    with pytest.raises(ValueError, match="negative amount"):
        sum_recovery_lines([_line(amount=Decimal("-5"))])


def test_sum_recovery_lines_mixed_currency_raises() -> None:
    with pytest.raises(ValueError, match="mix currency codes"):
        sum_recovery_lines([_line(currency="EUR"), _line(ref="INV-2", currency="USD")])


def test_sum_recovery_lines_allows_blank_currency() -> None:
    currency, total = sum_recovery_lines([_line(currency=""), _line(ref="INV-2", currency="EUR", amount=Decimal("10"))])
    assert currency == "EUR"
    assert total == Decimal("110.00")


def test_build_from_lines_ties_base_to_evidence() -> None:
    lines = [
        _line(ref="LAB-1", description="labour", amount=Decimal("600.00")),
        _line(ref="MAT-1", description="materials", amount=Decimal("400.00")),
    ]
    b = build_recovery_breakdown_from_lines(lines, admin_pct=Decimal("0.10"))
    assert b.base_cost == Decimal("1000.00")
    assert b.line_count == 2
    assert b.currency == "EUR"
    assert b.recovery_total == Decimal("1100.00")


def test_lines_reconcile_to_true_within_tolerance() -> None:
    lines = [_line(amount=Decimal("100.00")), _line(ref="INV-2", amount=Decimal("100.00"))]
    assert lines_reconcile_to(Decimal("200.00"), lines) is True
    assert lines_reconcile_to(Decimal("200.01"), lines) is True  # within one cent
    assert lines_reconcile_to(Decimal("250.00"), lines) is False


def test_lines_reconcile_empty_only_to_zero() -> None:
    assert lines_reconcile_to(Decimal("0"), []) is True
    assert lines_reconcile_to(Decimal("1"), []) is False


# ---------------------------------------------------------------------------
# over-recovery guards
# ---------------------------------------------------------------------------


def test_cap_recovered_clamps_both_ends() -> None:
    assert cap_recovered(Decimal("-5"), Decimal("100")) == Decimal("0.00")
    assert cap_recovered(Decimal("50"), Decimal("100")) == Decimal("50.00")
    assert cap_recovered(Decimal("150"), Decimal("100")) == Decimal("100.00")


def test_cap_recovered_negative_total_yields_zero() -> None:
    # A negative recovery total should never let a recovered amount through.
    assert cap_recovered(Decimal("10"), Decimal("-100")) == Decimal("0.00")


def test_is_over_recovered() -> None:
    assert is_over_recovered(Decimal("101"), Decimal("100")) is True
    assert is_over_recovered(Decimal("100"), Decimal("100")) is False


def test_ensure_not_over_recovered_raises() -> None:
    with pytest.raises(ValueError, match="exceeds the recoverable total"):
        ensure_not_over_recovered(Decimal("120"), Decimal("100"))


def test_ensure_not_over_recovered_passes_through() -> None:
    assert ensure_not_over_recovered(Decimal("80"), Decimal("100")) == Decimal("80.00")


def test_remaining_to_recover_floors_at_zero() -> None:
    assert remaining_to_recover(Decimal("100"), Decimal("30")) == Decimal("70.00")
    assert remaining_to_recover(Decimal("100"), Decimal("130")) == Decimal("0.00")


# ---------------------------------------------------------------------------
# plain-language helpers (clarity)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "needle"),
    [
        ("proposed", "not yet agreed"),
        ("agreed", "invoice it"),
        ("disputed", "contests"),
        ("recovered", "collected in full"),
        ("waived", "written off"),
        ("absorbed", "accepted the cost itself"),
    ],
)
def test_describe_status_says_what_and_next(status: str, needle: str) -> None:
    text = describe_status(status)
    assert needle in text
    # The description is a full sentence, not a bare code.
    assert text.endswith(".")


def test_describe_status_case_insensitive() -> None:
    assert describe_status("AGREED") == describe_status("agreed")


def test_describe_status_unknown_lists_valid() -> None:
    text = describe_status("bogus")
    assert "Unknown status" in text
    assert "proposed" in text and "recovered" in text


def test_describe_status_blank_is_safe() -> None:
    assert "Unknown status" in describe_status("")


@pytest.mark.parametrize(
    ("band", "needle"),
    [
        ("strong", "clearly traceable"),
        ("moderate", "partly traceable"),
        ("weak", "hard to trace"),
    ],
)
def test_describe_band(band: str, needle: str) -> None:
    assert needle in describe_band(band)


def test_describe_band_blank_and_junk_fold_to_weak() -> None:
    weak = describe_band("weak")
    assert describe_band("") == weak
    assert describe_band("nonsense") == weak


def test_state_recovery_full_sentence() -> None:
    text = state_recovery(
        amount=Decimal("1150.00"),
        currency="EUR",
        party="Subcontractor A",
        description="rework of a defective slab",
        basis="contract clause 12.3",
    )
    assert text == (
        "Recovering 1150.00 EUR from Subcontractor A for rework of a defective slab, "
        "on the basis of contract clause 12.3."
    )


def test_state_recovery_blank_party_and_description() -> None:
    text = state_recovery(
        amount="0.00",
        currency="",
        party="",
        description="",
    )
    assert "an unassigned party" in text
    assert "an unspecified cost" in text
    # No currency invented when none is given.
    assert "Recovering 0.00 from" in text


def test_state_recovery_omits_basis_when_blank() -> None:
    text = state_recovery(
        amount=Decimal("10"),
        currency="GBP",
        party="Supplier X",
        description="late delivery",
    )
    assert "on the basis of" not in text
    assert text.endswith("late delivery.")


# ---------------------------------------------------------------------------
# shared money quantum
# ---------------------------------------------------------------------------


def test_quantize_money_half_up() -> None:
    assert quantize_money(Decimal("1.005")) == Decimal("1.01")
    assert quantize_money(Decimal("1.004")) == Decimal("1.00")
