# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for per-activity work calendars in the CPM engine.

``app.core.cpm.calculate_cpm`` lets each activity carry its own ``calendar``
({"work_days": [...], "exceptions": [...]}) so its duration is measured on its
own work week - a six-day trade finishes sooner than a five-day one over the
same duration, a crew with its own holidays finishes later. An activity without
its own calendar falls back to the schedule-wide ``calendar`` argument, so the
default path is unchanged. These pin that behaviour, and that the working-day
snap (which keeps a weekend-anchored root off the critical path) uses the
activity's own calendar too.

2024-01-01 is a Monday, so day-offsets map cleanly: offset 5 = Saturday
2024-01-06, offset 6 = Sunday 2024-01-07.
"""

from __future__ import annotations

import pytest

from app.core.cpm import calculate_cpm

_SIX_DAY = {"work_days": [0, 1, 2, 3, 4, 5], "exceptions": []}  # Mon-Sat
_FIVE_DAY = {"work_days": [0, 1, 2, 3, 4], "exceptions": []}  # Mon-Fri


@pytest.mark.asyncio
async def test_six_day_activity_finishes_sooner_than_five_day() -> None:
    """The same duration finishes at a smaller offset on a six-day week."""
    five = {r["id"]: r for r in await calculate_cpm([{"id": "x", "duration": 6}], [], project_start_date="2024-01-01")}
    six = {
        r["id"]: r
        for r in await calculate_cpm(
            [{"id": "x", "duration": 6, "calendar": _SIX_DAY}], [], project_start_date="2024-01-01"
        )
    }
    # Five-day skips both weekend days; six-day works the Saturday, so it lands
    # one calendar day earlier.
    assert five["x"]["early_finish"] == 8
    assert six["x"]["early_finish"] == 7
    assert six["x"]["early_finish"] < five["x"]["early_finish"]


@pytest.mark.asyncio
async def test_per_activity_calendar_overrides_schedule_default() -> None:
    """An activity's own calendar wins over the schedule-wide default."""
    by_id = {
        r["id"]: r
        for r in await calculate_cpm(
            [{"id": "x", "duration": 6, "calendar": _SIX_DAY}],
            [],
            calendar=_FIVE_DAY,  # schedule default is five-day
            project_start_date="2024-01-01",
        )
    }
    assert by_id["x"]["early_finish"] == 7  # the six-day activity calendar, not the five-day default


@pytest.mark.asyncio
async def test_activity_without_calendar_uses_schedule_default() -> None:
    """No per-activity calendar -> the schedule-wide calendar applies."""
    by_id = {
        r["id"]: r
        for r in await calculate_cpm(
            [{"id": "x", "duration": 6}], [], calendar=_SIX_DAY, project_start_date="2024-01-01"
        )
    }
    assert by_id["x"]["early_finish"] == 7  # schedule-wide six-day week


@pytest.mark.asyncio
async def test_snap_uses_the_activity_calendar_so_a_saturday_root_is_kept() -> None:
    """A Saturday-started root on a six-day week is a working day, so not snapped.

    On the default five-day week the same root would snap Sat -> Mon (see
    test_cpm_start_offset). Here Saturday is a working day, so early_start stays
    at the Saturday offset and the float is still non-negative.
    """
    by_id = {
        r["id"]: r
        for r in await calculate_cpm(
            [{"id": "sat", "duration": 3, "start_offset": 5, "calendar": _SIX_DAY}],
            [],
            project_start_date="2024-01-01",
        )
    }
    assert by_id["sat"]["early_start"] == 5  # Saturday kept, not snapped to Monday
    assert by_id["sat"]["total_float"] >= 0


@pytest.mark.asyncio
async def test_mixed_calendars_each_measured_on_its_own_week() -> None:
    """An FS chain where predecessor and successor use different work weeks.

    The five-day predecessor and six-day successor each measure their own
    duration on their own calendar; the successor still starts no earlier than
    the predecessor finishes.
    """
    activities = [
        {"id": "p", "duration": 5, "calendar": _FIVE_DAY},
        {"id": "s", "duration": 6, "calendar": _SIX_DAY},
    ]
    relationships = [{"predecessor_id": "p", "successor_id": "s", "type": "FS", "lag": 0}]
    by_id = {r["id"]: r for r in await calculate_cpm(activities, relationships, project_start_date="2024-01-01")}
    # Successor never starts before the predecessor's finish.
    assert by_id["s"]["early_start"] >= by_id["p"]["early_finish"]
    # Successor's own six-day span: from its early_start, 6 working days on a
    # Mon-Sat week lands one calendar day sooner than a five-day span would.
    assert by_id["s"]["early_finish"] - by_id["s"]["early_start"] == 7


@pytest.mark.parametrize("bad_work_days", [[7], [], [8, 9], ["x", None], [-1]])
@pytest.mark.asyncio
async def test_out_of_range_work_days_fall_back_and_never_hang(bad_work_days: list) -> None:
    """A calendar with no valid 0-6 weekday must fall back to Mon-Fri, not spin.

    ISO uses Mon=1..Sun=7; a caller that stores ``[7]`` (their "Sunday") gives
    the engine a week with zero of its own working days (Mon=0..Sun=6). Without
    the guard, ``_add_working_days`` would step forever looking for a working
    day and overflow -> a single-worker hang. The parse must drop the invalid
    entries and use Monday-Friday, so the run finishes exactly like the default.
    """
    got = {
        r["id"]: r
        for r in await calculate_cpm(
            [{"id": "x", "duration": 3, "calendar": {"work_days": bad_work_days, "exceptions": []}}],
            [],
            project_start_date="2024-01-01",
        )
    }
    default = {
        r["id"]: r for r in await calculate_cpm([{"id": "x", "duration": 3}], [], project_start_date="2024-01-01")
    }
    assert got["x"]["early_finish"] == default["x"]["early_finish"] == 3


@pytest.mark.asyncio
async def test_six_day_predecessor_into_five_day_successor_keeps_float_non_negative() -> None:
    """A six-day predecessor finishing on a Saturday must not push the five-day
    successor negative.

    The six-day predecessor (duration 5 from Monday 2024-01-01) finishes at
    offset 5, which is Saturday - a working day on its own Mon-Sat week but not
    on the successor's Mon-Fri week. The successor's early_start is driven to
    that Saturday by the FS link, then must snap forward to Monday (offset 7) on
    its OWN calendar so the working-day forward and backward passes stay
    symmetric. Before the snap moved after the predecessor-max, the successor
    kept the Saturday start and came out with negative total_float / a false
    critical flag.
    """
    activities = [
        {"id": "p", "duration": 5, "calendar": _SIX_DAY},
        {"id": "s", "duration": 3, "calendar": _FIVE_DAY},
    ]
    relationships = [{"predecessor_id": "p", "successor_id": "s", "type": "FS", "lag": 0}]
    by_id = {r["id"]: r for r in await calculate_cpm(activities, relationships, project_start_date="2024-01-01")}
    assert by_id["p"]["early_finish"] == 5  # Saturday offset on the six-day week
    assert by_id["s"]["early_start"] == 7  # snapped Sat -> Mon on the successor's own five-day week
    assert by_id["s"]["early_finish"] == 10
    # The real regression guard: no activity ends up with negative float.
    assert by_id["p"]["total_float"] >= 0
    assert by_id["s"]["total_float"] >= 0
