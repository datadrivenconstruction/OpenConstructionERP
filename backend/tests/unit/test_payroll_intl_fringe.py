# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The overtime base: what the multiplier is allowed to touch.

Overtime is computed on the basic hourly wage. Where a rate is made up of a
basic wage plus an hourly fringe benefit amount, multiplying the combined figure
overpays the fringe on every overtime hour. This file pins both halves of that:
the new basic-rate parameter does the right thing, and leaving it out leaves
every existing caller byte for byte where it was.

The second half matters as much as the first. ``payroll.intl`` is used by the
whole platform and most of its users are nowhere near a prevailing wage regime,
so a change made for one country's compliance form must be invisible to them.
"""

from decimal import Decimal

import pytest

from app.modules.payroll import intl

# ── The multiplier applies to the basic rate only ────────────────────────────


def test_overtime_pay_multiplies_only_the_basic_rate() -> None:
    """40 basic + 10 fringe, 2 overtime hours at 1.5x.

    Right answer: 2 x (40 x 1.5 + 10) = 140.00.
    The error this guards against is 2 x 50 x 1.5 = 150.00, which pays the
    time-and-a-half premium on the fringe money as well as on the wage.
    """
    assert intl.overtime_pay("2", "50", "1.5", basic_rate="40") == Decimal("140.00")
    assert intl.overtime_pay("2", "50", "1.5") == Decimal("150.00")


def test_gross_pay_splits_straight_and_overtime_correctly() -> None:
    """40 straight hours and 8 overtime, 40 basic + 10 fringe.

    Straight: 40 x 50 = 2000. Overtime: 8 x (40 x 1.5 + 10) = 560. Total 2560.
    """
    assert intl.gross_pay("40", "8", "50", "1.5", basic_rate="40") == Decimal("2560.00")


def test_the_fringe_is_paid_on_overtime_hours_too() -> None:
    """The fringe is not multiplied, but it is not dropped either.

    A tempting wrong fix is to pay the fringe only on straight hours. Over one
    overtime hour that costs the worker the whole fringe rate.
    """
    with_fringe = intl.overtime_pay("1", "50", "1.5", basic_rate="40")
    basic_only = intl.overtime_pay("1", "40", "1.5", basic_rate="40")
    assert with_fringe - basic_only == Decimal("10.00")


def test_a_higher_fringe_share_lowers_the_overtime_bill() -> None:
    """Same package, different split, and the overtime cost genuinely differs.

    This is why the split cannot be folded into one number after the fact: the
    same 50 an hour produces two different overtime totals depending on how much
    of it is basic wage. A stored blended rate has lost the information.
    """
    mostly_basic = intl.overtime_pay("10", "50", "1.5", basic_rate="45")
    mostly_fringe = intl.overtime_pay("10", "50", "1.5", basic_rate="35")
    # 10 x (45 x 1.5 + 5) = 725.00 against 10 x (35 x 1.5 + 15) = 675.00.
    assert mostly_basic == Decimal("725.00")
    assert mostly_fringe == Decimal("675.00")
    assert mostly_basic > mostly_fringe


# ── Omitting the parameter changes nothing ───────────────────────────────────


@pytest.mark.parametrize(
    ("hours", "rate", "multiplier"),
    [("2", "20", "1.5"), ("0", "20", "1.5"), ("7.25", "33.4567", "2"), ("40", "0", "1.5")],
)
def test_no_basic_rate_is_the_old_behaviour(hours: str, rate: str, multiplier: str) -> None:
    """With no basic rate the whole rate is the base, exactly as before."""
    assert intl.overtime_pay(hours, rate, multiplier) == intl.quantize_money(
        Decimal(hours) * Decimal(rate) * Decimal(multiplier)
    )


def test_basic_rate_equal_to_rate_agrees_with_omitting_it() -> None:
    """The two forms must meet where the fringe is zero, or one of them is wrong."""
    assert intl.overtime_pay("3", "27.50", "1.5", basic_rate="27.50") == intl.overtime_pay("3", "27.50", "1.5")
    assert intl.gross_pay("8", "3", "27.50", "1.5", basic_rate="27.50") == intl.gross_pay("8", "3", "27.50", "1.5")


# ── resolve_overtime_base ────────────────────────────────────────────────────


def test_resolve_overtime_base_splits_the_rate() -> None:
    assert intl.resolve_overtime_base("50", "40") == (Decimal("40"), Decimal("10"))


def test_resolve_overtime_base_without_a_basic_rate_is_the_whole_rate() -> None:
    assert intl.resolve_overtime_base("50") == (Decimal("50"), Decimal("0"))


def test_resolve_overtime_base_rejects_a_basic_rate_above_the_rate() -> None:
    """Two figures that cannot describe one rate are an input error, not a negative fringe."""
    with pytest.raises(ValueError, match="must not exceed"):
        intl.resolve_overtime_base("40", "50")


def test_resolve_overtime_base_rejects_negatives() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        intl.resolve_overtime_base("50", "-1")


# ── The breakdown exposes the split ──────────────────────────────────────────


def test_payslip_breakdown_reports_the_base_it_used() -> None:
    """An auditable payslip has to say what the multiplier was applied to."""
    report = intl.payslip_breakdown(
        "48",
        "50",
        "USD",
        overtime_threshold="40",
        basic_rate="40",
    )
    assert report["regular_hours"] == "40"
    assert report["overtime_hours"] == "8"
    assert report["basic_rate"] == "40.0000"
    assert report["fringe_rate"] == "10.0000"
    assert report["overtime_base_rate"] == "40.0000"
    assert report["overtime_pay"] == "560.00"
    assert report["gross_pay"] == "2560.00"


def test_payslip_breakdown_without_a_basic_rate_leaves_it_blank() -> None:
    """No basic rate stated means no claim about the split, not a claim of zero."""
    report = intl.payslip_breakdown("48", "50", "USD", overtime_threshold="40")
    assert report["basic_rate"] == ""
    assert report["fringe_rate"] == "0.0000"
    assert report["overtime_base_rate"] == "50.0000"
    assert report["gross_pay"] == "2600.00"
