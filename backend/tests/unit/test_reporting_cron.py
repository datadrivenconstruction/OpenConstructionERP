"""Unit tests for the minimal cron parser (v2.3.0 scheduled reports).

Covers field parsing, range/list/step syntax, invalid inputs and the
``next_occurrence`` walker for the patterns we care about (daily,
weekly, monthly, every-N-minutes).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.modules.reporting.cron import (
    CronParseError,
    next_occurrence,
    parse_cron,
)


class TestParseCron:
    def test_star_matches_full_range(self):
        minutes, hours, doms, months, dows = parse_cron("* * * * *")
        assert minutes == set(range(60))
        assert hours == set(range(24))
        assert doms == set(range(1, 32))
        assert months == set(range(1, 13))
        assert dows == set(range(7))

    def test_single_values(self):
        minutes, hours, _, _, dows = parse_cron("30 9 * * 1")
        assert minutes == {30}
        assert hours == {9}
        assert dows == {1}

    def test_list_values(self):
        minutes, _, _, _, _ = parse_cron("0,15,30,45 * * * *")
        assert minutes == {0, 15, 30, 45}

    def test_range_values(self):
        _, _, _, _, dows = parse_cron("0 9 * * 1-5")
        assert dows == {1, 2, 3, 4, 5}

    def test_step_values(self):
        minutes, _, _, _, _ = parse_cron("*/15 * * * *")
        assert minutes == {0, 15, 30, 45}

    def test_wrong_field_count_raises(self):
        with pytest.raises(CronParseError):
            parse_cron("0 9 *")

    def test_out_of_range_raises(self):
        with pytest.raises(CronParseError):
            parse_cron("60 9 * * *")  # minute 60 is invalid
        with pytest.raises(CronParseError):
            parse_cron("0 24 * * *")  # hour 24 is invalid

    def test_invalid_characters_raise(self):
        with pytest.raises(CronParseError):
            parse_cron("abc 9 * * *")


class TestNextOccurrence:
    """UTC-only. Reports don't do DST magic — the worker runs against
    real wall-clock UTC and users have to understand their local offset."""

    def test_naive_after_raises(self):
        with pytest.raises(ValueError):
            next_occurrence("0 9 * * *", datetime(2026, 4, 22, 9, 0))

    def test_daily_at_9am(self):
        """Monday 08:00 → Monday 09:00."""
        after = datetime(2026, 4, 20, 8, 0, tzinfo=timezone.utc)  # Monday
        result = next_occurrence("0 9 * * *", after)
        assert result == datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc)

    def test_daily_after_trigger(self):
        """Monday 09:00 exactly → next day 09:00."""
        after = datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc)
        result = next_occurrence("0 9 * * *", after)
        assert result == datetime(2026, 4, 21, 9, 0, tzinfo=timezone.utc)

    def test_weekly_on_monday(self):
        """Every Monday 09:00 — from Wednesday should land on next Monday."""
        after = datetime(2026, 4, 22, 9, 0, tzinfo=timezone.utc)  # Wednesday
        result = next_occurrence("0 9 * * 1", after)
        # Next Monday is 2026-04-27.
        assert result == datetime(2026, 4, 27, 9, 0, tzinfo=timezone.utc)
        assert result.weekday() == 0  # Python: 0 = Monday

    def test_every_15_minutes(self):
        after = datetime(2026, 4, 22, 9, 17, 30, tzinfo=timezone.utc)
        result = next_occurrence("*/15 * * * *", after)
        # 9:17:30 → next 15-minute mark is 9:30.
        assert result == datetime(2026, 4, 22, 9, 30, tzinfo=timezone.utc)

    def test_monthly_on_1st(self):
        after = datetime(2026, 4, 22, 9, 0, tzinfo=timezone.utc)
        # 1st of every month, 0:00.
        result = next_occurrence("0 0 1 * *", after)
        # Next is May 1 2026.
        assert result == datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)

    def test_weekday_morning_range(self):
        """9am Mon-Fri — from Saturday should land on next Monday."""
        after = datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc)  # Saturday
        result = next_occurrence("0 9 * * 1-5", after)
        # Next Monday is 2026-04-27.
        assert result == datetime(2026, 4, 27, 9, 0, tzinfo=timezone.utc)

    def test_specific_day_of_month(self):
        after = datetime(2026, 4, 22, 9, 0, tzinfo=timezone.utc)
        # Every 15th at 06:00.
        result = next_occurrence("0 6 15 * *", after)
        # Next 15th is May 15 2026.
        assert result == datetime(2026, 5, 15, 6, 0, tzinfo=timezone.utc)
