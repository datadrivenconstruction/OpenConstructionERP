# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the international / edge-case field-time engine additions.

These exercise the timezone-safe worked-interval math, configurable rounding and
overtime, week-start handling, per-worker overlap detection and the metadata
config reader in :mod:`app.modules.field_time.field_time_math` - all pure, with
plain ``Decimal`` / ``datetime`` / ``dict`` inputs and no database, FastAPI or
ORM, so they run on any interpreter (including the local Python 3.11 runner).

The point of these rules is that nothing assumes one country's working day: a
night shift crossing midnight is valid, overtime is off unless a project sets a
threshold, rounding is off unless a project sets a step, and the week can start
on any weekday. Hours and money stay ``Decimal`` throughout.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.modules.field_time import field_time_math as ft

D = Decimal


def _labour(resource_id: str, hours: str, cost_code: str = "01.10", **extra: object) -> dict[str, object]:
    """Build a labour line dict."""
    line: dict[str, object] = {
        "resource_id": resource_id,
        "equipment_id": None,
        "hours": hours,
        "cost_code": cost_code,
    }
    line.update(extra)
    return line


# ── rounding to a configurable increment ─────────────────────────────────────


def test_round_to_increment_quarter_hour() -> None:
    assert ft.round_to_increment("8.10", "0.25") == D("8.00")
    assert ft.round_to_increment("8.13", "0.25") == D("8.25")
    assert ft.round_to_increment("8.40", "0.25") == D("8.50")


def test_round_to_increment_tenth_hour() -> None:
    assert ft.round_to_increment("7.44", "0.1") == D("7.40")
    assert ft.round_to_increment("7.46", "0.1") == D("7.50")


def test_round_to_increment_zero_or_negative_is_passthrough() -> None:
    # No rounding step -> value kept to two decimals as booked.
    assert ft.round_to_increment("8.37", "0") == D("8.37")
    assert ft.round_to_increment("8.37", "-1") == D("8.37")
    assert ft.round_to_increment("8.37", "not-a-number") == D("8.37")


# ── worked-interval hours (timezone-safe, overnight, breaks) ─────────────────


def test_worked_hours_simple_shift_with_break() -> None:
    start = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    end = datetime(2026, 7, 1, 17, 0, tzinfo=UTC)
    result = ft.worked_hours(start, end, break_minutes=60)
    assert result.valid is True
    assert result.gross_hours == D("9.00")
    assert result.break_hours == D("1.00")
    assert result.net_hours == D("8.00")


def test_worked_hours_naive_datetimes_allowed() -> None:
    start = datetime(2026, 7, 1, 9, 0)
    end = datetime(2026, 7, 1, 12, 30)
    result = ft.worked_hours(start, end)
    assert result.valid is True
    assert result.net_hours == D("3.50")


def test_worked_hours_overnight_shift_crosses_midnight() -> None:
    # A night shift 22:00 -> 06:00 is 8 hours, not a negative span.
    start = datetime(2026, 7, 1, 22, 0, tzinfo=UTC)
    end = datetime(2026, 7, 1, 6, 0, tzinfo=UTC)
    result = ft.worked_hours(start, end, break_minutes=30)
    assert result.valid is True
    assert result.gross_hours == D("8.00")
    assert result.net_hours == D("7.50")


def test_worked_hours_end_before_start_when_overnight_disallowed() -> None:
    start = datetime(2026, 7, 1, 17, 0, tzinfo=UTC)
    end = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    result = ft.worked_hours(start, end, allow_overnight=False)
    assert result.valid is False
    assert result.reason == ft.INTERVAL_END_BEFORE_START


def test_worked_hours_zero_length_is_invalid() -> None:
    when = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    result = ft.worked_hours(when, when)
    assert result.valid is False
    assert result.reason == ft.INTERVAL_ZERO_LENGTH


def test_worked_hours_break_longer_than_shift_is_invalid() -> None:
    start = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    end = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)  # 2 hour shift
    result = ft.worked_hours(start, end, break_minutes=180)  # 3 hour break
    assert result.valid is False
    assert result.reason == ft.INTERVAL_BREAK_EXCEEDS_SHIFT


def test_worked_hours_break_equal_to_shift_is_invalid() -> None:
    start = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    end = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    result = ft.worked_hours(start, end, break_minutes=60)
    assert result.valid is False
    assert result.reason == ft.INTERVAL_BREAK_EXCEEDS_SHIFT


def test_worked_hours_negative_break_is_invalid() -> None:
    start = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    end = datetime(2026, 7, 1, 16, 0, tzinfo=UTC)
    result = ft.worked_hours(start, end, break_minutes=-30)
    assert result.valid is False
    assert result.reason == ft.INTERVAL_BREAK_NEGATIVE


def test_worked_hours_over_24h_single_shift_is_invalid() -> None:
    start = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    end = datetime(2026, 7, 2, 10, 0, tzinfo=UTC)  # 26 hours later
    result = ft.worked_hours(start, end, allow_overnight=False)
    assert result.valid is False
    assert result.reason == ft.INTERVAL_OVER_24H


def test_worked_hours_timezone_mismatch_is_rejected() -> None:
    start = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    end = datetime(2026, 7, 1, 17, 0)  # naive
    result = ft.worked_hours(start, end)
    assert result.valid is False
    assert result.reason == ft.INTERVAL_TIMEZONE_MISMATCH


def test_worked_hours_non_datetime_is_rejected() -> None:
    result = ft.worked_hours("08:00", "17:00")
    assert result.valid is False
    assert result.reason == ft.INTERVAL_TIMES_REQUIRED


def test_worked_hours_across_offsets_is_absolute_elapsed() -> None:
    # Same wall clock, different offsets: 09:00+02:00 to 17:00+00:00 = 10 hours.
    plus_two = timezone(timedelta(hours=2))
    start = datetime(2026, 7, 1, 9, 0, tzinfo=plus_two)
    end = datetime(2026, 7, 1, 17, 0, tzinfo=UTC)
    result = ft.worked_hours(start, end)
    assert result.valid is True
    assert result.net_hours == D("10.00")


# ── per-worker overlap detection (double booking) ────────────────────────────


def _entry(worker: str, start: datetime, end: datetime) -> dict[str, object]:
    return {"resource_id": worker, "start": start, "end": end}


def test_overlapping_worker_intervals_flags_double_booking() -> None:
    base = datetime(2026, 7, 1, tzinfo=UTC)
    entries = [
        _entry("r1", base.replace(hour=8), base.replace(hour=12)),
        _entry("r1", base.replace(hour=11), base.replace(hour=15)),  # overlaps first
        _entry("r2", base.replace(hour=8), base.replace(hour=12)),  # different worker
    ]
    assert ft.overlapping_worker_intervals(entries) == [(0, 1)]


def test_overlapping_worker_intervals_touching_is_not_overlap() -> None:
    base = datetime(2026, 7, 1, tzinfo=UTC)
    entries = [
        _entry("r1", base.replace(hour=8), base.replace(hour=12)),
        _entry("r1", base.replace(hour=12), base.replace(hour=16)),  # starts as first ends
    ]
    assert ft.overlapping_worker_intervals(entries) == []


def test_overlapping_worker_intervals_skips_entries_without_times() -> None:
    base = datetime(2026, 7, 1, tzinfo=UTC)
    entries = [
        _entry("r1", base.replace(hour=8), base.replace(hour=12)),
        {"resource_id": "r1", "hours": "4"},  # no start / end
    ]
    assert ft.overlapping_worker_intervals(entries) == []


def test_overlapping_worker_intervals_skips_mixed_timezone_awareness() -> None:
    entries = [
        _entry("r1", datetime(2026, 7, 1, 8, tzinfo=UTC), datetime(2026, 7, 1, 12, tzinfo=UTC)),
        _entry("r1", datetime(2026, 7, 1, 10), datetime(2026, 7, 1, 14)),  # naive - not comparable
    ]
    assert ft.overlapping_worker_intervals(entries) == []


# ── overtime split (off by default, configurable) ────────────────────────────


def test_split_overtime_no_threshold_is_all_regular() -> None:
    split = ft.split_overtime("11")
    assert split.regular_hours == D("11.00")
    assert split.overtime_hours == D("0.00")


def test_split_overtime_above_threshold() -> None:
    split = ft.split_overtime("11", daily_threshold="8")
    assert split.regular_hours == D("8.00")
    assert split.overtime_hours == D("3.00")


def test_split_overtime_below_threshold() -> None:
    split = ft.split_overtime("6", daily_threshold="8")
    assert split.regular_hours == D("6.00")
    assert split.overtime_hours == D("0.00")


def test_split_overtime_negative_hours_clamped() -> None:
    split = ft.split_overtime("-4", daily_threshold="8")
    assert split.regular_hours == D("0.00")
    assert split.overtime_hours == D("0.00")


def test_daily_overtime_sums_per_worker_above_threshold() -> None:
    lines = [
        _labour("r1", "10"),  # 2 over
        _labour("r2", "8"),  # none
        _labour("r3", "9.5"),  # 1.5 over
    ]
    assert ft.daily_overtime(lines, daily_threshold="8") == D("3.50")


def test_daily_overtime_zero_when_no_threshold() -> None:
    lines = [_labour("r1", "12")]
    assert ft.daily_overtime(lines, daily_threshold=0) == D("0.00")


# ── configurable week start ──────────────────────────────────────────────────


def test_week_start_defaults_to_monday() -> None:
    # 2026-07-01 is a Wednesday -> Monday of that week is 2026-06-29.
    assert ft.week_start(date(2026, 7, 1)) == date(2026, 6, 29)


def test_week_start_sunday() -> None:
    # Week starting Sunday (6): the Sunday on or before Wednesday 2026-07-01.
    assert ft.week_start(date(2026, 7, 1), week_starts_on=6) == date(2026, 6, 28)


def test_week_start_out_of_range_falls_back_to_monday() -> None:
    assert ft.week_start(date(2026, 7, 1), week_starts_on=99) == date(2026, 6, 29)


# ── rollup honours a rounding step ───────────────────────────────────────────


def test_rollup_rounds_each_line_to_increment() -> None:
    lines = [_labour("r1", "8.10"), _labour("r2", "8.13")]
    roll = ft.rollup(lines, rounding_increment=D("0.25"))
    # 8.10 -> 8.00, 8.13 -> 8.25, total 16.25.
    assert roll.labour_hours == D("16.25")


def test_rollup_without_increment_keeps_booked_hours() -> None:
    lines = [_labour("r1", "8.10"), _labour("r2", "8.13")]
    roll = ft.rollup(lines)
    assert roll.labour_hours == D("16.23")


# ── metadata config reader (worldwide-safe defaults) ─────────────────────────


def test_read_hours_config_defaults_when_empty() -> None:
    config = ft.read_hours_config(None)
    assert config.max_hours_per_day == ft.MAX_HOURS_PER_DAY
    assert config.overtime_daily_threshold is None
    assert config.rounding_increment is None
    assert config.week_starts_on == 0


def test_read_hours_config_parses_all_fields() -> None:
    config = ft.read_hours_config(
        {
            "max_hours_per_day": "16",
            "overtime_daily_threshold": "8",
            "hours_rounding_increment": "0.25",
            "week_starts_on": 6,
        },
    )
    assert config.max_hours_per_day == D("16")
    assert config.overtime_daily_threshold == D("8")
    assert config.rounding_increment == D("0.25")
    assert config.week_starts_on == 6


def test_read_hours_config_rejects_bad_values() -> None:
    config = ft.read_hours_config(
        {
            "max_hours_per_day": "0",  # out of range -> default 24
            "overtime_daily_threshold": "-1",  # invalid -> None
            "hours_rounding_increment": "nonsense",  # invalid -> None
            "week_starts_on": 42,  # out of range -> 0
        },
    )
    assert config.max_hours_per_day == ft.MAX_HOURS_PER_DAY
    assert config.overtime_daily_threshold is None
    assert config.rounding_increment is None
    assert config.week_starts_on == 0


def test_read_hours_config_caps_max_hours_at_24() -> None:
    config = ft.read_hours_config({"max_hours_per_day": "30"})
    assert config.max_hours_per_day == ft.MAX_HOURS_PER_DAY


# ── overlap detection flows into the aggregate check ─────────────────────────


def test_check_timesheet_flags_overlapping_worker_lines() -> None:
    base = datetime(2026, 7, 1, tzinfo=UTC)
    lines = [
        {
            "resource_id": "r1",
            "equipment_id": None,
            "hours": "4",
            "cost_code": "01.10",
            "start": base.replace(hour=8),
            "end": base.replace(hour=12),
        },
        {
            "resource_id": "r1",
            "equipment_id": None,
            "hours": "4",
            "cost_code": "01.10",
            "start": base.replace(hour=11),
            "end": base.replace(hour=15),
        },
    ]
    checks = ft.check_timesheet(lines, valid_cost_codes={"01.10"}, valid_wbs=set())
    assert checks.overlapping_worker_line_pairs == [(0, 1)]
    assert checks.has_blocking_errors is True


def test_check_timesheet_without_times_has_no_overlaps() -> None:
    lines = [_labour("r1", "8", "01.10"), _labour("r1", "4", "01.10")]
    checks = ft.check_timesheet(lines, valid_cost_codes={"01.10"}, valid_wbs=set())
    assert checks.overlapping_worker_line_pairs == []


if __name__ == "__main__":  # pragma: no cover - manual smoke run
    raise SystemExit(pytest.main([__file__, "-q"]))
