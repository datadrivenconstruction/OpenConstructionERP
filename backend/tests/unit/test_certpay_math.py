# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Certified payroll arithmetic: the week, the package comparison, the pay split."""

from decimal import Decimal

import pytest

from app.modules.certified_payroll import certpay_math as m

# ── The week ─────────────────────────────────────────────────────────────────


def test_week_days_returns_seven_days_ending_on_the_date() -> None:
    days = m.week_days("2026-08-16")
    assert len(days) == m.DAYS_IN_PAYROLL_WEEK
    assert days[0] == "2026-08-10"
    assert days[-1] == "2026-08-16"


def test_week_days_crosses_a_month_boundary() -> None:
    """The week is seven calendar days, not a slice of one month."""
    assert m.week_days("2026-09-02")[0] == "2026-08-27"


def test_week_days_rejects_a_non_date() -> None:
    with pytest.raises(ValueError, match="ISO 8601"):
        m.week_days("week 33")


def test_is_in_week_covers_both_ends() -> None:
    assert m.is_in_week("2026-08-10", "2026-08-16")
    assert m.is_in_week("2026-08-16", "2026-08-16")
    assert not m.is_in_week("2026-08-09", "2026-08-16")
    assert not m.is_in_week("2026-08-17", "2026-08-16")


def test_is_in_week_treats_a_missing_date_as_outside_rather_than_raising() -> None:
    """A payroll entry with no date is a data gap the rules report, not a crash."""
    assert not m.is_in_week(None, "2026-08-16")
    assert not m.is_in_week("not a date", "2026-08-16")


def test_week_ending_for_finds_the_sunday() -> None:
    # 2026-08-12 is a Wednesday; the week ends the following Sunday.
    assert m.week_ending_for("2026-08-12") == "2026-08-16"
    # A day that already is the week end stays put.
    assert m.week_ending_for("2026-08-16") == "2026-08-16"


def test_week_ending_for_honours_another_payroll_week() -> None:
    """The payroll week is the contractor's practice, not this platform's rule."""
    assert m.week_ending_for("2026-08-12", week_ends_on=4) == "2026-08-14"


def test_week_ending_for_rejects_a_bad_weekday() -> None:
    with pytest.raises(ValueError, match="weekday index"):
        m.week_ending_for("2026-08-12", week_ends_on=9)


# ── Straight and overtime split ──────────────────────────────────────────────


def test_no_threshold_means_every_hour_is_straight() -> None:
    """The neutral default: no working-time rule is assumed for anybody."""
    per_day, straight, overtime = m.split_week_hours({"2026-08-10": "10", "2026-08-11": "10"})
    assert straight == Decimal("20")
    assert overtime == Decimal("0")
    assert per_day["2026-08-10"] == {"straight": "10", "overtime": "0"}


def test_daily_threshold_splits_each_day() -> None:
    per_day, straight, overtime = m.split_week_hours(
        {"2026-08-10": "10", "2026-08-11": "6"},
        daily_overtime_threshold="8",
    )
    assert per_day["2026-08-10"] == {"straight": "8", "overtime": "2"}
    assert per_day["2026-08-11"] == {"straight": "6", "overtime": "0"}
    assert (straight, overtime) == (Decimal("14"), Decimal("2"))


def test_weekly_threshold_splits_across_the_week() -> None:
    hours = {f"2026-08-1{n}": "9" for n in range(5)}
    _per_day, straight, overtime = m.split_week_hours(hours, weekly_overtime_threshold="40")
    assert straight == Decimal("40")
    assert overtime == Decimal("5")


def test_both_thresholds_never_count_an_hour_twice() -> None:
    """Daily first, then the weekly rule over what survived it.

    Five 10-hour days: the daily rule makes 10 hours overtime and leaves 40
    straight, and the weekly threshold of 40 then finds nothing further to move.
    Counting both independently would report 20 overtime hours out of 50 worked.
    """
    hours = {f"2026-08-1{n}": "10" for n in range(5)}
    _per_day, straight, overtime = m.split_week_hours(
        hours,
        daily_overtime_threshold="8",
        weekly_overtime_threshold="40",
    )
    assert straight == Decimal("40")
    assert overtime == Decimal("10")
    assert straight + overtime == Decimal("50")


def test_split_rejects_negative_hours() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        m.split_week_hours({"2026-08-10": "-1"})


# ── The pay split ────────────────────────────────────────────────────────────


def test_line_pay_applies_the_multiplier_to_the_basic_wage_only() -> None:
    """40 straight and 8 overtime at 40 basic + 10 fringe."""
    pay = m.line_pay("40", "8", "40", "10")
    assert pay["paid_rate"] == "50"
    assert pay["overtime_base_rate"] == "40"
    assert pay["straight_pay"] == "2000.00"
    assert pay["overtime_pay"] == "560.00"
    assert pay["gross_amount"] == "2560.00"


def test_line_pay_with_no_overtime_is_hours_times_the_package() -> None:
    pay = m.line_pay("40", "0", "40", "10")
    assert pay["gross_amount"] == "2000.00"


def test_line_pay_rejects_a_negative_fringe() -> None:
    with pytest.raises(ValueError, match="paid_fringe_rate must not be negative"):
        m.line_pay("40", "0", "40", "-10")


# ── Package comparison ───────────────────────────────────────────────────────


def test_total_package_adds_basic_and_fringe() -> None:
    assert m.total_package("40", "10") == Decimal("50")


def test_underpaid_by_reports_the_shortfall_on_the_package() -> None:
    assert m.underpaid_by("35", "10", "40", "10") == Decimal("5")


def test_underpaid_by_is_zero_when_the_package_is_met() -> None:
    assert m.underpaid_by("40", "10", "40", "10") == Decimal("0")


def test_a_different_split_of_the_same_package_is_not_underpayment() -> None:
    """Discharging more of the rate as fringe is lawful, and not a shortfall."""
    assert m.underpaid_by("30", "20", "40", "10") == Decimal("0")


def test_overpaying_is_not_a_negative_shortfall() -> None:
    assert m.underpaid_by("45", "10", "40", "10") == Decimal("0")


# ── Which determination governs ──────────────────────────────────────────────


def test_the_higher_package_governs_when_two_regimes_cover_the_work() -> None:
    """A federal determination does not satisfy a state one; the higher is owed."""
    winner, reason = m.governing_classification(
        [
            {"authority": "federal", "determination_identifier": "F-1", "basic_hourly_rate": "40", "fringe_rate": "10"},
            {"authority": "state", "determination_identifier": "S-1", "basic_hourly_rate": "44", "fringe_rate": "12"},
        ]
    )
    assert winner is not None
    assert winner["determination_identifier"] == "S-1"
    assert "state" in reason
    assert "56" in reason
    assert "does not satisfy" in reason


def test_the_comparison_is_on_the_package_not_the_basic_wage() -> None:
    """A lower basic wage can still be the higher obligation once fringe counts."""
    winner, _reason = m.governing_classification(
        [
            {"authority": "federal", "determination_identifier": "F-1", "basic_hourly_rate": "45", "fringe_rate": "2"},
            {"authority": "state", "determination_identifier": "S-1", "basic_hourly_rate": "40", "fringe_rate": "20"},
        ]
    )
    assert winner is not None
    assert winner["determination_identifier"] == "S-1"


def test_a_single_determination_governs_and_says_so() -> None:
    winner, reason = m.governing_classification(
        [
            {
                "authority": "awarding_body",
                "determination_identifier": "TX-CITY-7",
                "basic_hourly_rate": "30",
                "fringe_rate": "5",
            }
        ]
    )
    assert winner is not None
    assert "Only the awarding body determination" in reason


def test_no_determination_is_reported_rather_than_guessed() -> None:
    winner, reason = m.governing_classification([])
    assert winner is None
    assert "No wage determination" in reason


def test_equal_packages_are_recorded_as_equal_not_as_discharged() -> None:
    """Two equal obligations are still two obligations."""
    winner, reason = m.governing_classification(
        [
            {"authority": "federal", "determination_identifier": "F-1", "basic_hourly_rate": "40", "fringe_rate": "10"},
            {"authority": "state", "determination_identifier": "S-1", "basic_hourly_rate": "40", "fringe_rate": "10"},
        ]
    )
    assert winner is not None
    assert "not discharged by each other" in reason
