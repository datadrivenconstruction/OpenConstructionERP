# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every seeded working week must mean the same week the schedule resolver means.

The platform holds two weekday conventions at once, on purpose.
``oe_i18n_work_calendar.work_days`` counts Monday = 1 through Sunday = 7,
matching ``date.isoweekday()``, which is what
:func:`~app.modules.i18n_foundation.service.get_working_days` counts each date
with. ``schedule.WORK_CALENDARS`` and ``core.calendar._WORKING_WEEK`` count
Monday = 0 through Sunday = 6, matching ``date.weekday()``. Both are correct and
neither is going away; what is missing is anything that makes them agree.

Nothing converts at a boundary today, because the two never meet: no reader of
the seeded column is on the Monday-zero axis. That is what makes this worth a
gate rather than a fix. The failure mode is not a conversion going wrong, it is
a *week being written on the wrong axis in the first place*, and this table has
already shipped that once - Saudi Arabia went out as a four-day week and needed
migration ``v3303`` to repair it.

A range check cannot catch it. ``[1, 2, 3, 4, 5]`` for Saudi Arabia is five legal
ISO weekdays and the wrong week. Only Sunday and Friday tell the axes apart, so
the check has to be against something that already knows what each country's
week means, which is what the Monday-zero tables are.

This gate asserts weeks. It does not assert hours, and that gap is deliberate
rather than overlooked: ``work_hours_per_day`` disagrees with
``schedule.WORK_CALENDARS`` on five seeded rows - CH at 8.4, AU at 7.6, NO and
FI at 7.5, DK at 7.4 - and none of those is an axis question. Reading a green
run here as "the two calendar systems agree" would be reading more than it says.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.calendar import _WORKING_WEEK
from app.modules.schedule.service import get_work_calendar

#: The shipped file. Named once so a red-check can repoint it at a perturbed
#: copy and watch this gate fail, which is the only way to know it can.
_SEED = (
    Path(__file__).resolve().parents[2] / "app" / "modules" / "i18n_foundation" / "seed_data" / "work_calendars.json"
)

#: Countries whose seeded week and resolved week are both deliberate and differ
#: on *content* rather than on axis. Each ships Monday to Friday and resolves
#: Monday to Saturday, a sixth working day rather than a shifted one.
#:
#: This dict is the documentation of what disagrees, which is why it holds a
#: reason rather than being a set of codes to skip. It is also self-cancelling:
#: :func:`test_a_named_disagreement_still_disagrees` fails when one of these
#: starts agreeing, so closing a disagreement forces its removal from here
#: instead of leaving a stale exemption that quietly covers a future defect.
KNOWN_CONTENT_DISAGREEMENTS: dict[str, str] = {
    "CN": "seeded Mon-Fri; WORK_CALENDARS['CHINA'] resolves Mon-Sat",
    "IN": "seeded Mon-Fri; WORK_CALENDARS['INDIA'] resolves Mon-Sat",
    "BR": "seeded Mon-Fri; WORK_CALENDARS['BRAZIL'] resolves Mon-Sat, 44h/week legal",
}

#: A floor with headroom, not a census. Pinning the exact number would fail the
#: day somebody seeds Peru and would blame their change for it. The file carried
#: 36 rows when this was written; the floor is low enough that removing six
#: countries is what it takes to trip, and that is worth tripping on.
_MIN_SEEDED_ROWS = 30


def _seed_rows() -> list[dict]:
    with open(_SEED, encoding="utf-8") as handle:
        return json.load(handle)


def _to_monday_zero(iso_week: list[int]) -> set[int]:
    """An ISO week (Mon=1..Sun=7) on the Monday-zero axis (Mon=0..Sun=6)."""
    return {day - 1 for day in iso_week}


def _seeded_countries() -> list[str]:
    return sorted({row["country_code"] for row in _seed_rows()})


def test_the_seed_file_still_holds_a_population_worth_checking() -> None:
    """A gate over an empty file passes for the wrong reason."""
    rows = _seed_rows()
    assert len(rows) >= _MIN_SEEDED_ROWS, (
        f"{_SEED.name} holds {len(rows)} calendars, below the floor of {_MIN_SEEDED_ROWS}. "
        "It held 36 when this gate was written. Either a large number of calendars were "
        "removed, or this test is reading the wrong file."
    )


@pytest.mark.parametrize("country_code", _seeded_countries())
def test_the_seeded_week_converts_to_the_resolver_week(country_code: str) -> None:
    """The seeded ISO week is the resolver's Monday-zero week, day for day."""
    if country_code in KNOWN_CONTENT_DISAGREEMENTS:
        pytest.skip(f"{country_code}: {KNOWN_CONTENT_DISAGREEMENTS[country_code]}")

    row = next(r for r in _seed_rows() if r["country_code"] == country_code)
    converted = _to_monday_zero(row["work_days"])
    resolved = set(get_work_calendar(country_code)["work_days"])

    assert converted == resolved, (
        f"{country_code} is seeded as {sorted(row['work_days'])} on the ISO axis, which is "
        f"{sorted(converted)} on the Monday-zero axis, but the schedule resolver answers "
        f"{sorted(resolved)}. A week that differs by Sunday and Friday was written on the wrong "
        "axis; a week that differs by Saturday is a content disagreement and belongs in "
        "KNOWN_CONTENT_DISAGREEMENTS with its reason."
    )


@pytest.mark.parametrize("country_code", sorted(KNOWN_CONTENT_DISAGREEMENTS))
def test_a_named_disagreement_still_disagrees(country_code: str) -> None:
    """A named disagreement that has been resolved must leave this list.

    Without this, the dict above would go on exempting a country long after the
    reason for it was gone, and would be exempting it from the axis check too.
    """
    row = next((r for r in _seed_rows() if r["country_code"] == country_code), None)
    assert row is not None, (
        f"{country_code} is named in KNOWN_CONTENT_DISAGREEMENTS but is not seeded any more. Remove the entry."
    )
    converted = _to_monday_zero(row["work_days"])
    resolved = set(get_work_calendar(country_code)["work_days"])
    assert converted != resolved, (
        f"{country_code} now agrees: both say {sorted(converted)}. Remove it from "
        "KNOWN_CONTENT_DISAGREEMENTS so the axis check covers it again."
    )


@pytest.mark.parametrize("country_code", sorted(KNOWN_CONTENT_DISAGREEMENTS))
def test_a_named_disagreement_is_content_and_not_a_disguised_axis_error(country_code: str) -> None:
    """The exempted countries differ by a working Saturday, not by a shifted week.

    This is the check that keeps the exemption list honest. An axis error shows
    as Sunday and Friday swapping sides; a content disagreement shows as the
    resolver holding every seeded day and one more. If one of these three ever
    turns into the first shape, it is a defect wearing an exemption.
    """
    row = next(r for r in _seed_rows() if r["country_code"] == country_code)
    converted = _to_monday_zero(row["work_days"])
    resolved = set(get_work_calendar(country_code)["work_days"])

    sunday, friday = 6, 4
    assert converted < resolved, (
        f"{country_code} is exempted as a content disagreement, but the resolver's "
        f"{sorted(resolved)} does not contain the seeded {sorted(converted)}. That is a shifted "
        "week, not an extra working day."
    )
    assert sunday not in resolved and sunday not in converted, (
        f"{country_code} is exempted as a content disagreement, but Sunday appears in "
        "one of the two weeks, which is the day that tells the axes apart."
    )
    assert friday in converted and friday in resolved, (
        f"{country_code} is exempted as a content disagreement, but Friday is not a working day "
        "on both sides, which is the other day that tells the axes apart."
    )


@pytest.mark.parametrize("country_code", _seeded_countries())
def test_the_seeded_week_matches_the_core_calendar_table_where_it_defines_one(country_code: str) -> None:
    """The other Monday-zero table agrees too, for the countries it covers.

    ``core.calendar._WORKING_WEEK`` is a second, independently written table on
    the same axis, and it names 19 of the seeded countries. It has no content
    disagreements at all, so it needs no exemptions - which is worth asserting
    separately rather than folding into the check above, because two tables
    agreeing with the seed for different reasons is stronger evidence than one.
    """
    if country_code not in _WORKING_WEEK:
        pytest.skip(f"core.calendar._WORKING_WEEK defines no week for {country_code}")

    row = next(r for r in _seed_rows() if r["country_code"] == country_code)
    converted = _to_monday_zero(row["work_days"])
    resolved = set(_WORKING_WEEK[country_code])

    assert converted == resolved, (
        f"{country_code} is seeded as {sorted(row['work_days'])} on the ISO axis, which is "
        f"{sorted(converted)} on the Monday-zero axis, but core.calendar._WORKING_WEEK holds "
        f"{sorted(resolved)}."
    )


def test_control_the_conversion_is_not_the_identity() -> None:
    """A conversion that returned its input would make every assertion above pass.

    ISO Sunday is 7 and Monday-zero Sunday is 6, so the one day that distinguishes
    the axes is the one that moves furthest. Asserted directly so that a
    conversion quietly rewritten to ``set(iso_week)`` is caught here, where the
    message says what happened, rather than in thirty parametrised failures that
    each blame a country.
    """
    gulf_iso = [7, 1, 2, 3, 4]
    assert _to_monday_zero(gulf_iso) == {6, 0, 1, 2, 3}
    assert _to_monday_zero(gulf_iso) != set(gulf_iso)
    assert _to_monday_zero([1, 2, 3, 4, 5]) == {0, 1, 2, 3, 4}


def test_control_a_week_written_on_the_wrong_axis_is_caught() -> None:
    """The negative control: perturb a real seeded week and watch the check fail.

    Saudi Arabia written as ``[6, 0, 1, 2, 3]`` is the exact defect ``v3303``
    repaired - a Monday-zero week sitting in an ISO column. It is five plausible
    numbers, four of them inside 1..7, and a range check waves it through. This
    asserts the comparison this gate is built on rejects it, so a green run above
    is evidence the weeks are right rather than evidence the comparison is inert.
    """
    wrong_axis = [6, 0, 1, 2, 3]
    converted = _to_monday_zero(wrong_axis)
    resolved = set(get_work_calendar("SA")["work_days"])

    assert converted != resolved, (
        "A Monday-zero Gulf week placed in the ISO column compared equal to the resolver's week. "
        "The comparison this gate rests on cannot tell the axes apart."
    )
