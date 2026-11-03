"""CPM engine honours activity constraints; plans without constraints are unchanged."""

from __future__ import annotations

import pytest

from app.core.cpm import calculate_cpm
from app.modules.schedule.constraints import CONSTRAINT_TYPES, normalize_constraint

WEEK = {"work_days": [0, 1, 2, 3, 4, 5, 6], "exceptions": []}
START = "2026-05-04"


async def _run(**constraint):
    """A(5) -> B(3) beside Long(10): B starts day 5, ends day 8, project ends day 10, B has 2 days of float."""
    b: dict = {"id": "B", "duration": 3}
    b.update(constraint)
    rows = await calculate_cpm(
        [{"id": "A", "duration": 5}, b, {"id": "Long", "duration": 10}],
        [{"predecessor_id": "A", "successor_id": "B", "type": "FS", "lag": 0}],
        calendar=WEEK,
        project_start_date=START,
    )
    return {r["id"]: r for r in rows}


def _dates(row):
    return row["early_start"], row["early_finish"], row["late_start"], row["total_float"], row["is_critical"]


@pytest.mark.asyncio
async def test_no_constraint_baseline():
    assert _dates((await _run())["B"]) == (5, 8, 7, 2, False)


@pytest.mark.asyncio
async def test_constraint_without_offset_or_asap_changes_nothing():
    base = await _run()
    assert await _run(constraint_type="start_no_earlier") == base
    assert await _run(constraint_type="as_soon_as_possible", constraint_offset=9) == base


@pytest.mark.asyncio
async def test_plain_results_carry_no_constraint_keys():
    assert "constraint_type" not in (await _run())["B"]


@pytest.mark.asyncio
async def test_start_no_earlier_raises_early_start():
    assert _dates((await _run(constraint_type="start_no_earlier", constraint_offset=6))["B"]) == (6, 9, 7, 1, False)


@pytest.mark.asyncio
async def test_must_start_on_floors_and_caps():
    assert _dates((await _run(constraint_type="must_start_on", constraint_offset=6))["B"]) == (6, 9, 6, 0, True)


@pytest.mark.asyncio
async def test_finish_no_earlier_raises_early_finish():
    assert _dates((await _run(constraint_type="finish_no_earlier", constraint_offset=10))["B"]) == (7, 10, 7, 0, True)


@pytest.mark.asyncio
async def test_must_finish_on_floors_and_caps():
    assert _dates((await _run(constraint_type="must_finish_on", constraint_offset=8))["B"]) == (5, 8, 5, 0, True)


@pytest.mark.asyncio
async def test_start_no_later_gives_negative_float_when_logic_is_too_slow():
    row = (await _run(constraint_type="start_no_later", constraint_offset=4))["B"]
    assert _dates(row) == (5, 8, 4, -1, True)


@pytest.mark.asyncio
async def test_finish_no_later_gives_negative_float_when_logic_is_too_slow():
    row = (await _run(constraint_type="finish_no_later", constraint_offset=7))["B"]
    assert _dates(row) == (5, 8, 4, -1, True)


@pytest.mark.asyncio
async def test_finish_no_later_with_room_keeps_positive_float():
    row = (await _run(constraint_type="finish_no_later", constraint_offset=9))["B"]
    assert _dates(row) == (5, 8, 6, 1, False)


@pytest.mark.asyncio
async def test_as_late_as_possible_moves_to_late_dates_and_leaves_critical_alone():
    rows = await _run(constraint_type="as_late_as_possible")
    assert (rows["B"]["early_start"], rows["B"]["early_finish"]) == (7, 10)
    assert rows["B"]["total_float"] == 2
    assert (rows["Long"]["early_start"], rows["Long"]["early_finish"]) == (0, 10)


@pytest.mark.asyncio
async def test_negative_float_reaches_predecessors():
    rows = await _run(constraint_type="finish_no_later", constraint_offset=7)
    assert rows["A"]["total_float"] == -1
    assert rows["A"]["is_critical"] is True


def test_every_constraint_name_survives_normalisation():
    assert len(CONSTRAINT_TYPES) == 8
    assert {normalize_constraint(name) for name in CONSTRAINT_TYPES} == set(CONSTRAINT_TYPES)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CS_MSO", "must_start_on"),
        ("CS_MEO", "must_finish_on"),
        ("CS_MANDSTART", "must_start_on"),
        ("CS_MANDFIN", "must_finish_on"),
        ("CS_MSOA", "start_no_earlier"),
        ("CS_MEOA", "finish_no_earlier"),
        ("CS_MSOB", "start_no_later"),
        ("CS_MEOB", "finish_no_later"),
        ("CS_ALAP", "as_late_as_possible"),
        ("CS_ASAP", None),
        ("", None),
        (None, None),
        ("cs_msoa", "start_no_earlier"),
        ("garbage", None),
    ],
)
def test_xer_codes_map_to_the_neutral_names(raw, expected):
    assert normalize_constraint(raw) == expected


def test_strict_mode_rejects_unknown_values():
    with pytest.raises(ValueError, match="unknown constraint"):
        normalize_constraint("whenever", strict=True)
