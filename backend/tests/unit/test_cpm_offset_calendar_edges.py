# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Edge-case unit tests for the working-day offset calendar (cpm.OffsetCalendar).

Pure-Python, no DB. These complement ``test_cpm_offset_calendar.py`` by pinning
the harder corners of the calendar-aware day-offset arithmetic a future CPM
integration can adopt:

* a finish or span that crosses MULTIPLE weekends,
* a holiday that lands exactly on the computed finish (it must be skipped),
* consecutive / block holidays,
* a holiday on an already non-working weekend (no effect),
* NEGATIVE start offsets (work that begins before the calendar epoch),
* custom working weeks (six-day Mon-Sat and a Sun-Thu "Gulf" week),
* round-trip invariants under multiple weekends + holidays,
* ``working_days_between`` over inverted / zero / negative-endpoint spans,
* zero-duration milestone behaviour from a non-working offset,
* the all-days calendar staying byte-for-byte equal to plain arithmetic across
  weekend boundaries.

Nothing in ``compute_cpm`` calls this helper yet; these tests guard the contract
so adoption stays a no-op for projects without a real calendar.
"""

from __future__ import annotations

from datetime import date

from app.modules.schedule_advanced.cpm import (
    ALL_DAYS_CALENDAR,
    OffsetCalendar,
)

# 2024-01-01 is a Monday, so offset 0 is a working day under the default week.
_MONDAY = date(2024, 1, 1)


# -- Spanning multiple weeks ---------------------------------------------------


def test_finish_crosses_two_weekends() -> None:
    """Ten working days from Monday land two full work-weeks later.

    Tue-Fri (offsets 1-4) is four days, skip the weekend, Mon-Fri (offsets 7-11)
    is five more = nine, skip the weekend again, the tenth working day is the
    following Monday at offset 14. Plain arithmetic would wrongly say 0 + 10.
    """
    cal = OffsetCalendar(epoch=_MONDAY)
    assert cal.working_finish_offset(0, 10) == 14
    assert cal.working_finish_offset(0, 10) != 10
    # The span back is exactly the ten working days requested.
    assert cal.working_days_between(0, 14) == 10


def test_long_span_counts_only_working_days() -> None:
    """A four-calendar-week span (28 days) contains exactly 20 working days."""
    cal = OffsetCalendar(epoch=_MONDAY)
    # Counting is exclusive of the start offset, so the 28-day window holds the
    # 20 working days strictly after offset 0.
    assert cal.working_days_between(0, 28) == 20
    # A 20-working-day task from Monday finishes on offset 28 (a Monday). The
    # count starts the day AFTER the start, so the 20th counted working day is
    # the Monday following the fourth full work-week (the fourth Friday is the
    # 19th counted day at offset 25, then the weekend, then offset 28).
    finish = cal.working_finish_offset(0, 20)
    assert finish == 28
    assert cal.is_working_offset(finish)
    # The finish round-trips: 20 working days separate the start and the finish.
    assert cal.working_days_between(0, finish) == 20


# -- Holiday landing exactly on the finish / blocks ----------------------------


def test_holiday_on_the_finish_day_is_skipped() -> None:
    """When the natural finish lands on a holiday it rolls to the next work day.

    A 4-day task from Monday would finish on Friday (offset 4). Marking that
    Friday a holiday pushes the fourth working day to the following Monday
    (offset 7), never returning a non-working finish.
    """
    cal = OffsetCalendar(epoch=_MONDAY, holidays=frozenset({"2024-01-05"}))  # Fri
    assert cal.is_working_offset(4) is False
    finish = cal.working_finish_offset(0, 4)
    assert finish == 7
    assert cal.is_working_offset(finish)


def test_consecutive_holidays_are_both_skipped() -> None:
    """A block of two mid-week holidays both drop out of the count."""
    # Tue 2024-01-02 and Wed 2024-01-03 are offsets 1 and 2.
    cal = OffsetCalendar(epoch=_MONDAY, holidays=frozenset({"2024-01-02", "2024-01-03"}))
    assert cal.is_working_offset(1) is False
    assert cal.is_working_offset(2) is False
    # Three working days from Monday: Thu, Fri (offsets 3,4), skip the weekend,
    # the third is the following Monday (offset 7).
    assert cal.working_finish_offset(0, 3) == 7
    # The span (0, 4] now has only Thu + Fri working.
    assert cal.working_days_between(0, 4) == 2


def test_holiday_on_weekend_is_a_noop_across_a_long_span() -> None:
    """A holiday on a Saturday changes no finish offset over many durations."""
    # 2024-01-06 is a Saturday (offset 5) - already non-working.
    plain = OffsetCalendar(epoch=_MONDAY)
    with_hol = OffsetCalendar(epoch=_MONDAY, holidays=frozenset({"2024-01-06"}))
    for dur in range(0, 25):
        assert with_hol.working_finish_offset(0, dur) == plain.working_finish_offset(0, dur)
    for end in range(0, 25):
        assert with_hol.working_days_between(0, end) == plain.working_days_between(0, end)


# -- Negative start offsets (work beginning before the epoch) ------------------


def test_negative_start_offset_skips_weekend_forward() -> None:
    """A finish counted from a Friday before the epoch lands on the next Monday.

    Offset -3 is the Friday before the Monday epoch (2023-12-29). One working
    day after it skips the weekend and is the epoch Monday at offset 0.
    """
    cal = OffsetCalendar(epoch=_MONDAY)
    assert cal.is_working_offset(-3) is True  # Friday 2023-12-29
    assert cal.is_working_offset(-1) is False  # Sunday 2023-12-31
    assert cal.working_finish_offset(-3, 1) == 0


def test_working_days_between_negative_endpoints() -> None:
    """The exclusive-start / inclusive-end rule holds across the epoch.

    Offset -3 (Fri) exclusive to offset 0 (Mon) inclusive crosses a weekend, so
    only the Monday counts.
    """
    cal = OffsetCalendar(epoch=_MONDAY)
    assert cal.working_days_between(-3, 0) == 1
    # A full week starting the Monday before the epoch: -7 (prev Mon) .. 0 (Mon).
    assert cal.working_days_between(-7, 0) == 5


def test_round_trip_with_negative_start_and_holidays() -> None:
    """Finish/start offsets invert each other even for pre-epoch working starts."""
    cal = OffsetCalendar(epoch=_MONDAY, holidays=frozenset({"2023-12-29", "2024-01-04"}))
    for start in range(-10, 5):
        if not cal.is_working_offset(start):
            continue
        for dur in range(1, 10):
            finish = cal.working_finish_offset(start, dur)
            assert cal.is_working_offset(finish)
            assert cal.working_start_offset(finish, dur) == start


# -- Custom working weeks ------------------------------------------------------


def test_six_day_week_includes_saturday() -> None:
    """A Mon-Sat working week only skips Sundays."""
    cal = OffsetCalendar(epoch=_MONDAY, work_weekdays=frozenset({0, 1, 2, 3, 4, 5}))
    assert cal.is_working_offset(5) is True  # Saturday now works
    assert cal.is_working_offset(6) is False  # Sunday still off
    # Six working days from Monday: Tue-Sat (offsets 1-5), skip Sunday, the sixth
    # is the next Monday at offset 7.
    assert cal.working_finish_offset(0, 6) == 7


def test_gulf_sun_thu_week() -> None:
    """A Sun-Thu working week treats Friday and Saturday as the weekend."""
    # work weekdays: Sun(6), Mon(0), Tue(1), Wed(2), Thu(3); Fri(4)/Sat(5) off.
    cal = OffsetCalendar(epoch=_MONDAY, work_weekdays=frozenset({6, 0, 1, 2, 3}))
    assert cal.is_working_offset(4) is False  # Friday
    assert cal.is_working_offset(5) is False  # Saturday
    assert cal.is_working_offset(6) is True  # Sunday is a working day here
    # Five working days from Monday: Tue, Wed, Thu (offsets 1-3), skip Fri+Sat,
    # then Sun + the next Mon (offsets 6,7) -> finish offset 7.
    assert cal.working_finish_offset(0, 5) == 7


def test_custom_week_round_trips() -> None:
    """The inverse relationship holds for a non-default working week too."""
    cal = OffsetCalendar(epoch=_MONDAY, work_weekdays=frozenset({0, 1, 2, 3, 4, 5}))
    start = 0
    for dur in range(1, 14):
        finish = cal.working_finish_offset(start, dur)
        span = cal.working_days_between(start, finish)
        assert span == dur
        assert cal.working_start_offset(finish, dur) == start


# -- Degenerate spans and milestones -------------------------------------------


def test_inverted_and_empty_spans_are_zero() -> None:
    """``working_days_between`` returns 0 for equal or inverted endpoints."""
    cal = OffsetCalendar(epoch=_MONDAY)
    assert cal.working_days_between(5, 5) == 0
    assert cal.working_days_between(10, 3) == 0
    assert cal.working_days_between(0, -5) == 0


def test_zero_duration_from_nonworking_offset_is_unchanged() -> None:
    """A milestone (duration 0) keeps its offset even on a weekend / holiday.

    The engine clamps a milestone to its own offset regardless of whether that
    offset is a working day, so it never silently rolls onto a later date.
    """
    cal = OffsetCalendar(epoch=_MONDAY, holidays=frozenset({"2024-01-03"}))
    for offset in (5, 6, 2):  # Saturday, Sunday, the holiday Wednesday
        assert cal.is_working_offset(offset) is False
        assert cal.working_finish_offset(offset, 0) == offset
        assert cal.working_start_offset(offset, 0) == offset


def test_large_negative_duration_behaves_like_milestone() -> None:
    """A large negative duration is clamped to a milestone (offset unchanged)."""
    cal = OffsetCalendar(epoch=_MONDAY)
    assert cal.working_finish_offset(9, -100) == 9
    assert cal.working_start_offset(9, -100) == 9


# -- All-days calendar stays equal to plain arithmetic across weekends ---------


def test_all_days_calendar_equals_plain_math_over_long_range() -> None:
    """The opt-out calendar matches bare integer math far past a week boundary."""
    cal = ALL_DAYS_CALENDAR
    for start in (-10, 0, 13, 30):
        for dur in range(0, 30):
            assert cal.working_finish_offset(start, dur) == start + dur
            assert cal.working_start_offset(start + dur, dur) == start
    for a in (-5, 0, 12):
        for b in range(-5, 30):
            assert cal.working_days_between(a, b) == max(0, b - a)
