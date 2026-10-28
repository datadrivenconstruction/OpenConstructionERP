# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the CPM engine's per-activity ``start_offset`` floor.

``app.core.cpm.calculate_cpm`` is the engine the schedule module's
``reschedule`` runs. A root activity has no predecessor, so before
``start_offset`` existed the forward pass floored its early_start at 0 (the
project origin) and its successors were scheduled from there, regardless of the
root's real manual start. On a project with more than one independent chain
that placed a later chain's successor BEFORE its own predecessor. These tests
pin the fix: a root's ``start_offset`` anchors it (and therefore its
successors) at its real start, while an omitted offset keeps the historical
origin-anchored behaviour.
"""

from __future__ import annotations

import pytest

from app.core.cpm import calculate_cpm


@pytest.mark.asyncio
async def test_missing_start_offset_defaults_to_origin() -> None:
    """No start_offset -> root anchored at the project origin (unchanged)."""
    activities = [{"id": "a", "duration": 3}, {"id": "b", "duration": 3}]
    relationships = [{"predecessor_id": "a", "successor_id": "b", "type": "FS", "lag": 0}]
    by_id = {r["id"]: r for r in await calculate_cpm(activities, relationships, project_start_date="2024-01-01")}
    assert by_id["a"]["early_start"] == 0
    assert by_id["b"]["early_start"] == by_id["a"]["early_finish"]


@pytest.mark.asyncio
async def test_root_start_offset_anchors_the_root() -> None:
    """A root's start_offset becomes its early_start (a 'start no earlier than' floor)."""
    activities = [{"id": "root", "duration": 5, "start_offset": 60}]
    by_id = {r["id"]: r for r in await calculate_cpm(activities, [], project_start_date="2024-01-01")}
    assert by_id["root"]["early_start"] == 60


@pytest.mark.asyncio
async def test_successor_of_a_late_root_is_never_scheduled_before_it() -> None:
    """The reported bug: an independent later chain's successor lands before its predecessor.

    Two independent FS chains share the project origin. Chain 2's root starts 60
    days in. Its successor must be scheduled after the root finishes, never at
    the origin (which is where the pre-fix engine put it, weeks before the root
    even starts).
    """
    activities = [
        {"id": "r1", "duration": 5, "start_offset": 0},
        {"id": "s1", "duration": 5, "start_offset": 0},
        {"id": "r2", "duration": 5, "start_offset": 60},
        {"id": "s2", "duration": 5, "start_offset": 0},
    ]
    relationships = [
        {"predecessor_id": "r1", "successor_id": "s1", "type": "FS", "lag": 0},
        {"predecessor_id": "r2", "successor_id": "s2", "type": "FS", "lag": 0},
    ]
    by_id = {r["id"]: r for r in await calculate_cpm(activities, relationships, project_start_date="2024-01-01")}
    # Root 2 is anchored at its own start, not the origin.
    assert by_id["r2"]["early_start"] == 60
    # Its successor starts at or after the root finishes - never before the root.
    assert by_id["s2"]["early_start"] >= by_id["r2"]["early_finish"]
    # And it is clearly NOT sitting at the origin like chain 1's successor.
    assert by_id["s2"]["early_start"] > by_id["s1"]["early_start"]


@pytest.mark.asyncio
async def test_successor_offset_does_not_pin_it_earlier_than_the_network() -> None:
    """A successor's own start_offset never overrides a later predecessor-driven date.

    reschedule only passes start_offset for roots, but the engine must stay safe
    even if a successor carries one: the max() against predecessor candidates
    means the network still wins when it pushes the successor later.
    """
    activities = [
        {"id": "p", "duration": 10, "start_offset": 0},
        # Successor floored at day 2, but its predecessor finishes well after.
        {"id": "q", "duration": 3, "start_offset": 2},
    ]
    relationships = [{"predecessor_id": "p", "successor_id": "q", "type": "FS", "lag": 0}]
    by_id = {r["id"]: r for r in await calculate_cpm(activities, relationships, project_start_date="2024-01-01")}
    # The network (predecessor finish) wins over the day-2 floor.
    assert by_id["q"]["early_start"] == by_id["p"]["early_finish"]


@pytest.mark.asyncio
async def test_weekend_anchored_root_has_no_spurious_negative_float() -> None:
    """Regression: a root whose manual start lands on a non-working day.

    Seeding early_start with the raw calendar-day offset of a weekend start
    broke the symmetry with the working-day backward pass (``_sub_working_days``
    always lands on a working day), so an isolated root dated on a Saturday or
    Sunday got a spurious NEGATIVE total_float and a false is_critical. The
    engine snaps a nonzero start floor forward to the next working day, so
    early_start lands on a working day and the float stays correct.
    """
    # 2024-01-01 is a Monday; day-offset 6 is Sunday 2024-01-07.
    activities = [{"id": "sunday_root", "duration": 4, "start_offset": 6}]
    by_id = {r["id"]: r for r in await calculate_cpm(activities, [], project_start_date="2024-01-01")}
    root = by_id["sunday_root"]
    # Pre-fix this was -2 (late_start 4 < early_start 6). Total float is never negative.
    assert root["total_float"] >= 0
    # early_start is snapped onto the next working day (Mon 2024-01-08 = offset 7).
    assert root["early_start"] == 7


@pytest.mark.asyncio
async def test_weekend_anchored_root_on_the_critical_chain_is_not_false_negative() -> None:
    """A weekend-anchored root that drives the longest chain gets float 0, not < 0.

    Root ``r`` starts on a Saturday and feeds ``s``; the r->s chain defines the
    project finish, so ``r`` is genuinely critical at float 0. Pre-fix the
    calendar-day vs working-day mismatch made ``r``'s total_float negative - an
    impossible, out-of-range value that reschedule would then persist (red bar).
    """
    # 2024-01-01 is a Monday; day-offset 5 is Saturday 2024-01-06.
    activities = [
        {"id": "r", "duration": 6, "start_offset": 5},
        {"id": "s", "duration": 2, "start_offset": 0},
    ]
    relationships = [{"predecessor_id": "r", "successor_id": "s", "type": "FS", "lag": 0}]
    by_id = {rec["id"]: rec for rec in await calculate_cpm(activities, relationships, project_start_date="2024-01-01")}
    assert by_id["r"]["total_float"] >= 0
    assert by_id["r"]["early_start"] == 7  # snapped Sat -> Mon
    # r drives the finish through s, so it is legitimately critical at float 0.
    assert by_id["r"]["is_critical"] is True


@pytest.mark.asyncio
async def test_non_working_project_origin_root_is_not_falsely_critical() -> None:
    """The whole schedule starting on a weekend must not falsely flag its root.

    The trigger is a non-working DATE, not a nonzero offset: when the project
    origin (schedule.start_date) is itself a Saturday, the first root sits at
    offset 0, so the snap has to apply there too. Pre-fix that root got
    total_float=-1 and a false is_critical. The offset is snapped forward to the
    first working day regardless of it being zero.
    """
    # 2024-01-06 is a Saturday; the root defaults to offset 0 (no start_offset).
    activities = [{"id": "sat_origin_root", "duration": 4}]
    by_id = {r["id"]: r for r in await calculate_cpm(activities, [], project_start_date="2024-01-06")}
    root = by_id["sat_origin_root"]
    assert root["total_float"] >= 0  # pre-fix -1
    assert root["early_start"] == 2  # Sat 01-06 -> Mon 01-08


@pytest.mark.asyncio
async def test_holiday_project_origin_root_is_not_falsely_critical() -> None:
    """A working-day origin that is a holiday must snap past the holiday too.

    2024-01-01 is a Monday but marked a holiday, so offset 0 lands on a
    non-working date even though the weekday is a working one. Pre-fix the root
    got total_float=-3 and a false is_critical.
    """
    calendar = {"work_days": [0, 1, 2, 3, 4], "exceptions": ["2024-01-01"]}
    activities = [{"id": "holiday_origin_root", "duration": 3}]
    by_id = {
        r["id"]: r for r in await calculate_cpm(activities, [], calendar=calendar, project_start_date="2024-01-01")
    }
    root = by_id["holiday_origin_root"]
    assert root["total_float"] >= 0  # pre-fix -3
    assert root["early_start"] == 1  # Mon 01-01 (holiday) -> Tue 01-02
