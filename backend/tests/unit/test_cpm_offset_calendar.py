# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the additive working-day offset calendar (cpm.OffsetCalendar).

Pure-Python, no DB - exercises the calendar-aware day-offset arithmetic that a
future CPM integration can adopt to skip weekends and holidays. The existing
``compute_cpm`` passes do NOT use this helper yet; these tests pin its contract
so that adoption is safe:

* the all-days calendar reproduces plain ``es + dur`` / ``ef - dur`` arithmetic
  exactly (the "no calendar effects" opt-out),
* the default Mon-Fri calendar skips weekends,
* explicit holidays are skipped even on a working weekday,
* finish and start offsets are exact inverses (round-trip),
* ``working_days_between`` is exclusive-start / inclusive-end and round-trips a
  finish offset,
* zero / negative durations behave like milestones (offset unchanged).
"""

from __future__ import annotations

from datetime import date

from app.modules.schedule_advanced.cpm import (
    ALL_DAYS_CALENDAR,
    DEFAULT_OFFSET_CALENDAR,
    OffsetCalendar,
)

# A Monday epoch so offset 0 is a working day under the default Mon-Fri calendar.
# 2024-01-01 is a Monday.
_MONDAY = date(2024, 1, 1)


# ── All-days calendar == plain offset arithmetic (the opt-out) ────────────────


def test_all_days_calendar_reproduces_plain_arithmetic() -> None:
    """With every day working, the helper is identical to bare integer math.

    This is the contract that makes adoption a no-op for projects without a real
    calendar: ``working_finish_offset(es, d) == es + d`` for all es, d.
    """
    cal = ALL_DAYS_CALENDAR
    for start in range(0, 15):
        for dur in range(0, 15):
            assert cal.working_finish_offset(start, dur) == start + dur
            assert cal.working_start_offset(start + dur, dur) == start
    for a in range(0, 15):
        for b in range(0, 15):
            assert cal.working_days_between(a, b) == max(0, b - a)


def test_all_days_calendar_every_offset_is_working() -> None:
    """No weekday is excluded under the all-days calendar."""
    cal = ALL_DAYS_CALENDAR
    assert all(cal.is_working_offset(o) for o in range(-7, 8))


# ── Default Mon-Fri calendar skips weekends ───────────────────────────────────


def test_default_calendar_is_mon_fri() -> None:
    """The default calendar marks Mon-Fri working and Sat/Sun non-working."""
    cal = OffsetCalendar(epoch=_MONDAY)  # offset 0 = Monday 2024-01-01
    # Offsets 0..4 are Mon..Fri (working); 5,6 are Sat,Sun (non-working).
    assert [cal.is_working_offset(o) for o in range(7)] == [
        True,
        True,
        True,
        True,
        True,
        False,
        False,
    ]


def test_working_finish_offset_skips_weekend() -> None:
    """A 5-day task starting Monday finishes the next Monday, not Saturday.

    Counting is exclusive of the start day: from Monday (offset 0), five working
    days are Tue, Wed, Thu, Fri (offsets 1-4) then the weekend is skipped and the
    fifth working day is the following Monday (offset 7).
    """
    cal = OffsetCalendar(epoch=_MONDAY)
    assert cal.working_finish_offset(0, 5) == 7
    # A 3-day task from Monday lands on Thursday (offset 3) - no weekend crossed.
    assert cal.working_finish_offset(0, 3) == 3
    # Plain arithmetic would have said 0 + 5 == 5 (a Saturday).
    assert cal.working_finish_offset(0, 5) != 5


def test_working_days_between_excludes_start_includes_end() -> None:
    """Monday->Friday is 4 working days (Tue, Wed, Thu, Fri)."""
    cal = OffsetCalendar(epoch=_MONDAY)
    # offset 0 = Mon, offset 4 = Fri.
    assert cal.working_days_between(0, 4) == 4
    # Monday to the following Monday spans one weekend: 5 working days.
    assert cal.working_days_between(0, 7) == 5
    # Empty / inverted spans contribute nothing.
    assert cal.working_days_between(4, 4) == 0
    assert cal.working_days_between(7, 0) == 0


# ── Holidays are skipped even on a working weekday ────────────────────────────


def test_holiday_is_skipped() -> None:
    """An explicit holiday on a working weekday is treated as non-working."""
    # Wednesday 2024-01-03 is offset 2 from the Monday epoch; mark it a holiday.
    cal = OffsetCalendar(epoch=_MONDAY, holidays=frozenset({"2024-01-03"}))
    assert cal.is_working_offset(2) is False
    # A 5-day task from Monday now also skips that Wednesday, pushing the finish
    # one further working day to Tuesday of the next week (offset 8).
    assert cal.working_finish_offset(0, 5) == 8
    # The holiday is not counted in a working-day span across it.
    assert cal.working_days_between(0, 4) == 3  # Tue, Thu, Fri (Wed excluded)


def test_holiday_on_weekend_has_no_effect() -> None:
    """Marking a non-working weekend day a holiday changes nothing."""
    # 2024-01-06 is a Saturday (offset 5) - already non-working.
    plain = OffsetCalendar(epoch=_MONDAY)
    with_hol = OffsetCalendar(epoch=_MONDAY, holidays=frozenset({"2024-01-06"}))
    for dur in range(0, 12):
        assert with_hol.working_finish_offset(0, dur) == plain.working_finish_offset(0, dur)


# ── Finish / start offsets are exact inverses ─────────────────────────────────


def test_finish_and_start_offsets_round_trip() -> None:
    """working_start_offset undoes working_finish_offset for any working start."""
    cal = OffsetCalendar(epoch=_MONDAY, holidays=frozenset({"2024-01-10", "2024-01-15"}))
    for start in range(0, 20):
        if not cal.is_working_offset(start):
            continue  # the engine only ever starts work on a working offset
        for dur in range(1, 12):
            finish = cal.working_finish_offset(start, dur)
            assert cal.is_working_offset(finish)  # a positive-duration finish is a working day
            assert cal.working_start_offset(finish, dur) == start


def test_working_days_between_round_trips_finish_offset() -> None:
    """between(start, finish) feeds back through working_finish_offset to finish."""
    cal = OffsetCalendar(epoch=_MONDAY, holidays=frozenset({"2024-01-11"}))
    start = 0
    for dur in range(1, 12):
        finish = cal.working_finish_offset(start, dur)
        span = cal.working_days_between(start, finish)
        assert span == dur
        assert cal.working_finish_offset(start, span) == finish


# ── Milestones: zero / negative durations leave the offset untouched ──────────


def test_zero_and_negative_duration_are_milestones() -> None:
    """Zero or negative durations keep the offset unchanged (milestone behaviour)."""
    cal = OffsetCalendar(epoch=_MONDAY)
    for offset in range(0, 10):
        assert cal.working_finish_offset(offset, 0) == offset
        assert cal.working_finish_offset(offset, -3) == offset
        assert cal.working_start_offset(offset, 0) == offset
        assert cal.working_start_offset(offset, -3) == offset


def test_default_offset_calendar_constant_is_mon_fri_no_holidays() -> None:
    """The module-level default constant is Mon-Fri with no holidays."""
    assert DEFAULT_OFFSET_CALENDAR.work_weekdays == frozenset({0, 1, 2, 3, 4})
    assert DEFAULT_OFFSET_CALENDAR.holidays == frozenset()
    # Its epoch (offset 0) is a working day so default schedules start cleanly.
    assert DEFAULT_OFFSET_CALENDAR.is_working_offset(0) is True
