"""A typed duration sets the end date on the working week; public holidays list for import."""

from __future__ import annotations

from functools import partial

import pytest

from app.modules.schedule.service import (
    compute_duration,
    end_from_working_days,
    public_holidays_for_import,
)


def _de(start: str, end: str) -> int:
    return compute_duration(start, end, "DE")


def test_ten_working_days_from_a_monday_end_on_the_second_friday() -> None:
    # Monday 8 June 2026: ten weekdays later is Friday 19 June (no German holiday in between).
    assert end_from_working_days("2026-06-08", 10, _de) == "2026-06-19"


def test_holiday_inside_the_span_pushes_the_end_one_working_day() -> None:
    # Ascension Day, Thursday 14 May 2026, is a German public holiday.
    assert end_from_working_days("2026-05-11", 5, _de) == "2026-05-18"


def test_zero_days_is_a_milestone_on_its_start() -> None:
    assert end_from_working_days("2026-05-04", 0, _de) == "2026-05-04"


def test_custom_week_counts_saturdays() -> None:
    six_day = partial(compute_duration, region="DE", work_weekdays=frozenset({0, 1, 2, 3, 4, 5}))
    assert end_from_working_days("2026-05-04", 6, lambda s, e: six_day(s, e)) == "2026-05-09"


def test_inverse_of_compute_duration() -> None:
    end = end_from_working_days("2026-03-02", 37, _de)
    assert _de("2026-03-02", end) == 37


def test_holidays_for_import_lists_named_dates_for_each_year() -> None:
    result = public_holidays_for_import("fr", [2026, 2027])
    assert result["country"] == "FR"
    dates = result["dates"]
    assert "2026-07-14" in dates
    assert "2027-07-14" in dates
    assert dates == sorted(dates)
    assert [c["year"] for c in result["coverage"]] == [2026, 2027]
    assert all(c["applied"] for c in result["coverage"])


def test_holidays_for_import_rejects_unknown_country() -> None:
    with pytest.raises(ValueError, match="country"):
        public_holidays_for_import("ZZ", [2026])
