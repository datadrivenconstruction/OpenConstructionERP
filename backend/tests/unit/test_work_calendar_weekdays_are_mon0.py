# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠No shipped Monday-zero calendar may carry a weekday the CPM engine cannot count.

This is the mirror of ``tests/unit/test_work_calendar_weekdays_are_iso.py``.

The i18n ``WorkCalendar`` counts ISO weekdays, Monday = 1 through Sunday = 7, and
shipped a Saudi row written as ``[0, 1, 2, 3, 4]`` under a zero-based convention.
``isoweekday()`` never returns 0, so that day was dropped and the country ran a
four-day week for as long as the row stood.

This platform's *other* work calendar counts the other way: ``date.weekday()``,
Monday = 0 through Sunday = 6. The same mistake in this direction is a 7. It is not
imagined - ``app/core/cpm.py`` records ``work_days=[7]`` as "a common Sunday = ISO 7
mistake" in the docstring of the very function that drops it. Dropping is deliberate:
it guarantees the engine's day-stepping loops terminate. But an emptied week then
falls back to Monday-Friday, so the schedule is computed against a week nobody asked
for and nothing raises. The tolerance stays; the refusal belongs at the writers.

What this file checks, and why each source is read the way it is:

* ``schedule.service.WORK_CALENDARS`` - 12 shipped regional presets, a module-level
  dict, so it is imported and surveyed directly.
* ``core.calendar._WORKING_WEEK`` - 18 shipped country weeks, likewise. **Read only.**
  That file belongs to another change in flight; this test imports it and never
  writes it.
* ``Calendar.work_days`` server default - what a row that omits the column gets, read
  off the column rather than off the source line.
* ``schedule_advanced/seed.py`` - the demo calendar is built straight on the ORM, so
  no schema sees it. It is the same bypass that let the Saudi row ship. Parsed
  narrowly: ``Calendar(...)`` keyword arguments in that one file, nothing wider. A
  repo-wide literal census was considered and rejected - most ``[0, 1, 2, 3, 4]``
  literals in these modules are defensive fallbacks inside coercion code, and
  flagging those would mean maintaining an allowlist of which literals count.

Fallback literals and Pydantic defaults are deliberately *not* surveyed. They are not
shipped calendar data; a wrong value there is a different bug with a different shape.
"""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.calendar import _WORKING_WEEK
from app.core.cpm import MAX_WEEKDAY, MIN_WEEKDAY, check_work_days_in_range
from app.modules.schedule.schemas import ScheduleCreate, ScheduleUpdate
from app.modules.schedule.service import WORK_CALENDARS
from app.modules.schedule_advanced.models import Calendar
from app.modules.schedule_advanced.schemas import CalendarCreate, CalendarResponse, CalendarUpdate

# Floors, so a source that shrinks to nothing cannot report clean. Four rather than
# one because these populations fail in different ways: a dict can lose entries while
# the survivors still offer plenty of values to inspect, and a week can be emptied
# while the entry count holds. Set just under what ships today (12 regions, 18
# countries, 159 weekday values, 1 seeded literal).
_MIN_REGIONS = 10
_MIN_COUNTRIES = 15
_MIN_WEEKDAY_VALUES = 130
_MIN_SEED_LITERALS = 1

_SEED_FILE = Path(__file__).resolve().parents[2] / "app" / "modules" / "schedule_advanced" / "seed.py"


def _is_whole_number(day: object) -> bool:
    """Report whether ``day`` is a plain integer.

    ``bool`` subclasses ``int``, so ``True`` would otherwise pass for weekday 1.
    """
    return isinstance(day, int) and not isinstance(day, bool)


def _survey_week(label: str, work_days: object) -> list[str]:
    """Report every weekday in one calendar that falls outside Monday=0..Sunday=6.

    The single implementation the gate tests and the controls both call, so a
    control can never pass by testing a re-implementation of the thing it guards.

    Args:
        label: How to name this calendar in an offender line.
        work_days: The calendar's weekday numbers, or anything else.

    Returns:
        One human-readable line per offending value, empty when the week is clean.
    """
    if not isinstance(work_days, (list, tuple, set, frozenset)):
        return [f"{label} declares work_days={work_days!r}, which is not a collection of weekdays."]
    if not work_days:
        return [f"{label} declares no working week at all, so every date is a day off."]

    # Whole numbers sort numerically and everything else sorts by repr. One sorted()
    # over the raw collection cannot do this: a mixed list raises TypeError comparing
    # str to int, and it would raise it inside the branch that only runs once there is
    # already a defect to report - the instrument would crash exactly when it works.
    # Sorting the whole thing by repr instead is no fix; it orders 12 before 7.
    # Split by predicate, never by "day not in numbers": that tests equality, and
    # True == 1, so a bool would be dropped from both halves whenever a 1 is present.
    numbers = sorted(day for day in work_days if _is_whole_number(day))
    ordered = [*numbers, *sorted((day for day in work_days if not _is_whole_number(day)), key=repr)]

    offenders = []
    for day in ordered:
        if not _is_whole_number(day):
            offenders.append(f"{label} declares {day!r} in work_days, which is not a whole number.")
        elif not MIN_WEEKDAY <= day <= MAX_WEEKDAY:
            offenders.append(
                f"{label} declares weekday {day} in work_days={ordered!r}, outside the range "
                f"{MIN_WEEKDAY}..{MAX_WEEKDAY}. date.weekday() never returns it, so that day is silently "
                f"dropped from the working week. Monday is {MIN_WEEKDAY} and Sunday is {MAX_WEEKDAY} - "
                f"Sunday is not 7."
            )
    return offenders


def _survey_mapping(mapping: dict[str, Any], *, kind: str, key: str | None = None) -> tuple[int, int, list[str]]:
    """Survey a mapping of name to calendar.

    Args:
        mapping: Name to week, where a week is either the collection itself or a
            dict carrying it under ``key``.
        kind: What the names are, for the offender lines.
        key: Where to find the week inside each value, when it is a dict.

    Returns:
        ``(entries inspected, weekday values inspected, offender lines)``.
    """
    values = 0
    offenders: list[str] = []
    for name, entry in sorted(mapping.items()):
        week = entry[key] if key is not None and isinstance(entry, dict) else entry
        if isinstance(week, (list, tuple, set, frozenset)):
            values += len(week)
        offenders.extend(_survey_week(f"{kind} {name}", week))
    return len(mapping), values, offenders


def _seeded_literals() -> list[list[int]]:
    """Read the ``work_days`` the demo seeder hands to ``Calendar(...)``.

    Narrow on purpose: this parses one file and looks only at keyword arguments of
    ``Calendar`` constructor calls. The seeder builds the ORM object directly, so no
    schema ever sees these values - the same door-versus-wall gap that let the Saudi
    row ship.
    """
    tree = ast.parse(_SEED_FILE.read_text(encoding="utf-8"))
    found: list[list[int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or getattr(node.func, "id", None) != "Calendar":
            continue
        for keyword in node.keywords:
            if keyword.arg == "work_days":
                found.append(ast.literal_eval(keyword.value))
    return found


# ── The wall: every shipped Monday-zero calendar ─────────────────────────────


def test_every_shipped_regional_preset_is_a_monday_zero_weekday() -> None:
    """The 12 regional presets the schedule module offers must all be countable."""
    regions, values, offenders = _survey_mapping(WORK_CALENDARS, kind="region", key="work_days")

    print(f"\nInspected {values} weekday values across {regions} regional presets.")

    assert offenders == [], "WORK_CALENDARS declares weekdays outside 0..6:\n" + "\n".join(offenders)
    assert regions >= _MIN_REGIONS, f"only {regions} regions inspected, expected at least {_MIN_REGIONS}"


def test_every_shipped_country_week_is_a_monday_zero_weekday() -> None:
    """The country weeks in the core calendar must all be countable.

    Imported read-only. This test never writes ``app/core/calendar.py``.
    """
    countries, values, offenders = _survey_mapping(_WORKING_WEEK, kind="country")

    print(f"\nInspected {values} weekday values across {countries} country weeks.")

    assert offenders == [], "_WORKING_WEEK declares weekdays outside 0..6:\n" + "\n".join(offenders)
    assert countries >= _MIN_COUNTRIES, f"only {countries} countries inspected, expected at least {_MIN_COUNTRIES}"


def test_the_stored_calendar_default_is_a_monday_zero_week() -> None:
    """What a row that omits ``work_days`` gets, read off the column itself."""
    server_default = Calendar.__table__.c.work_days.server_default
    assert server_default is not None, "the calendar column lost its server default"

    stored = json.loads(getattr(server_default.arg, "text", server_default.arg))
    offenders = _survey_week("Calendar.work_days server default", stored)

    assert offenders == [], "\n".join(offenders)


def test_the_seeded_demo_calendar_is_a_monday_zero_week() -> None:
    """The seeder bypasses the schemas, so its literal is read where it is written."""
    literals = _seeded_literals()

    offenders = [line for week in literals for line in _survey_week("seeded demo calendar", week)]

    assert offenders == [], "\n".join(offenders)
    assert len(literals) >= _MIN_SEED_LITERALS, (
        f"found {len(literals)} seeded calendars in {_SEED_FILE.name}, expected at least "
        f"{_MIN_SEED_LITERALS}. If the seeder moved or was renamed this check is now blind "
        f"and needs repointing, not relaxing."
    )


def test_the_survey_actually_surveyed_something() -> None:
    """The floor that stops an emptied source from reporting clean.

    Separate from the entry floors above: a dict could keep every entry and still
    offer nothing to inspect if the weeks themselves were emptied.
    """
    _, region_values, _ = _survey_mapping(WORK_CALENDARS, kind="region", key="work_days")
    _, country_values, _ = _survey_mapping(_WORKING_WEEK, kind="country")
    total = region_values + country_values

    assert total >= _MIN_WEEKDAY_VALUES, (
        f"only {total} weekday values inspected, expected at least {_MIN_WEEKDAY_VALUES}. "
        f"A shrinking population is how a check like this goes quietly blind."
    )


def test_the_sources_this_check_reads_still_exist() -> None:
    """Repointing is a decision; silently surveying nothing is not."""
    assert _SEED_FILE.exists(), f"{_SEED_FILE} moved; this check reads it by path"
    assert WORK_CALENDARS, "WORK_CALENDARS is empty"
    assert _WORKING_WEEK, "_WORKING_WEEK is empty"


# ── The controls: the checks above must be capable of going red ──────────────


def test_a_sunday_as_seven_region_is_caught() -> None:
    """The control: plant the mirror defect and the survey must report it.

    Every shipped week is already inside 0..6 and answers the same whether this
    check exists or not, so a green run over today's data is weak evidence. This is
    the evidence. Planted on a deep copy - the sources are shared state and other
    agents run tests against this same tree.
    """
    _, _, before = _survey_mapping(WORK_CALENDARS, kind="region", key="work_days")
    assert not before, (
        "a shipped regional preset already declares a weekday outside 0..6, so planting one "
        f"measures nothing - test_every_shipped_regional_preset_is_a_monday_zero_weekday is the "
        f"test that reports it, and this control cannot run until it is fixed: {before}"
    )

    planted_source = copy.deepcopy(WORK_CALENDARS)
    planted_source["GULF"]["work_days"] = {0, 1, 2, 3, 7}

    _, _, offenders = _survey_mapping(planted_source, kind="region", key="work_days")

    planted = [line for line in offenders if line not in before]
    assert len(offenders) == len(before) + 1, offenders
    assert len(planted) == 1, planted
    assert "GULF" in planted[0]
    assert "Sunday is not 7" in planted[0]


def test_a_sunday_as_seven_country_is_caught() -> None:
    """The same control on the country weeks, planted on a copy."""
    _, _, before = _survey_mapping(_WORKING_WEEK, kind="country")
    assert not before, (
        "a shipped country week already declares a weekday outside 0..6, so planting one "
        f"measures nothing and this control cannot run until it is fixed: {before}"
    )

    planted_source = copy.deepcopy(_WORKING_WEEK)
    planted_source["SA"] = frozenset({0, 1, 2, 3, 7})

    _, _, offenders = _survey_mapping(planted_source, kind="country")

    planted = [line for line in offenders if line not in before]
    assert len(planted) == 1, planted
    assert "SA" in planted[0]


def test_a_bad_weekday_in_the_seeder_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The control for the seed reader, run against a copy of the seeder.

    The other controls plant into an imported dict, which is private to this
    process. This one has to prove a *file* reader, so it copies the seeder to a
    temp path and plants there. The shipped file is never written - it is shared
    state, and other agents run tests against this same tree.
    """
    original = _SEED_FILE.read_text(encoding="utf-8")
    assert "work_days=[0, 1, 2, 3, 4]" in original, "the seeder's literal changed shape; repoint this control"

    planted_file = tmp_path / "seed.py"
    planted_file.write_text(
        original.replace("work_days=[0, 1, 2, 3, 4]", "work_days=[0, 1, 2, 3, 7]"), encoding="utf-8"
    )
    monkeypatch.setattr("tests.unit.test_work_calendar_weekdays_are_mon0._SEED_FILE", planted_file)

    literals = _seeded_literals()
    offenders = [line for week in literals for line in _survey_week("seeded demo calendar", week)]

    assert len(literals) >= _MIN_SEED_LITERALS, literals
    assert len(offenders) == 1, offenders
    assert "Sunday is not 7" in offenders[0]


def test_a_calendar_with_no_working_week_is_caught() -> None:
    """An empty week is an offender, not an abstention.

    Without this branch a source could clear the entry floor while giving the
    survey nothing to inspect, which is how a shrinking population reports clean.
    """
    _, _, before = _survey_mapping(WORK_CALENDARS, kind="region", key="work_days")

    planted_source = copy.deepcopy(WORK_CALENDARS)
    emptied = sorted(planted_source)[0]
    planted_source[emptied]["work_days"] = set()

    _, _, offenders = _survey_mapping(planted_source, kind="region", key="work_days")

    planted = [line for line in offenders if line not in before]
    assert len(planted) == 1, planted
    assert "no working week at all" in planted[0]
    assert emptied in planted[0]


# ── The instrument itself: it must survive the week it is reporting on ───────


def test_the_survey_reports_offending_weekdays_in_numeric_order() -> None:
    """A two-digit weekday must not sort ahead of a single-digit one.

    Sorting a mixed collection by ``repr`` orders 12 before 7, which reads as a bug
    in the report rather than a bug in the data.
    """
    offenders = _survey_week("region X", [0, 1, 12, 7])

    assert len(offenders) == 2, offenders
    assert " weekday 7 " in offenders[0], offenders[0]
    assert " weekday 12 " in offenders[1], offenders[1]
    assert "work_days=[0, 1, 7, 12]" in offenders[0], offenders[0]


def test_the_survey_survives_a_week_that_mixes_numbers_and_text() -> None:
    """Reporting an offender must not crash on the week that produced it.

    A bare ``sorted()`` over ``[7, "monday"]`` raises TypeError comparing str to
    int, and it would raise it only in the branch that runs when a defect exists -
    so the instrument would fail exactly when it finally had something to say.
    """
    offenders = _survey_week("region X", [7, "monday"])

    assert len(offenders) == 2, offenders
    assert " weekday 7 " in offenders[0], offenders[0]
    assert "'monday'" in offenders[1], offenders[1]


def test_the_survey_does_not_mistake_a_boolean_for_a_weekday() -> None:
    """``True`` is not Monday-plus-one.

    ``bool`` subclasses ``int`` and ``True == 1``, so a boolean can be dropped by
    any split that tests membership rather than type.
    """
    offenders = _survey_week("region X", [1, True])

    assert len(offenders) == 1, offenders
    assert "True" in offenders[0], offenders[0]
    assert "not a whole number" in offenders[0], offenders[0]


# ── The door, entrance one: the named calendar write schemas ─────────────────


@pytest.mark.parametrize("bad_day", [7, 8, -1, 12])
def test_creating_a_calendar_with_a_non_monday_zero_weekday_is_refused(bad_day: int) -> None:
    """A 7 here is the mirror of the 0 the ISO calendar shipped."""
    with pytest.raises(ValidationError) as excinfo:
        CalendarCreate(project_id=uuid4(), name="Site week", work_days=[bad_day, 0, 1, 2])

    assert "work_days" in str(excinfo.value)


@pytest.mark.parametrize("bad_day", [7, 8, -1])
def test_updating_a_calendar_to_a_non_monday_zero_weekday_is_refused(bad_day: int) -> None:
    """The update path is the one an operator actually reaches for."""
    with pytest.raises(ValidationError):
        CalendarUpdate(work_days=[bad_day, 0, 1, 2])


def test_sunday_is_accepted_as_six() -> None:
    """The negative control: the guard must not refuse the week it exists to protect.

    A range check that rejected Sunday would be a second defect wearing the first
    one's clothes, and every shipped Monday-Friday week would still pass.
    """
    sunday_to_thursday = CalendarCreate(project_id=uuid4(), name="Sun-Thu", work_days=[6, 0, 1, 2, 3])
    monday_to_saturday = CalendarCreate(project_id=uuid4(), name="Mon-Sat", work_days=[0, 1, 2, 3, 4, 5])

    assert sunday_to_thursday.work_days == [6, 0, 1, 2, 3]
    assert monday_to_saturday.work_days == [0, 1, 2, 3, 4, 5]


def test_reading_back_a_calendar_written_before_the_guard_still_works() -> None:
    """Deliberate asymmetry: the response schema stays unconstrained.

    A calendar stored before the guard existed still holds the old value. Refusing
    to serialise it would turn a wrong number into a 500 on the very screen an
    operator would use to correct it.
    """
    response = CalendarResponse(
        id=uuid4(),
        project_id=uuid4(),
        name="Legacy",
        work_days=[7, 0, 1, 2, 3],
        holidays=[],
        special_shifts={},
        is_default=False,
        created_at="2026-08-23T00:00:00",
        updated_at="2026-08-23T00:00:00",
    )

    assert response.work_days == [7, 0, 1, 2, 3]


# ── The door, entrance two: the free-form schedule metadata override ─────────
#
# A schedule's metadata is stored as given and resolve_calendar() reads
# metadata["calendar"]["work_days"] straight into the CPM engine, so this is a
# second way into the same convention that never touches CalendarCreate.


@pytest.mark.parametrize("bad_day", [7, 8, -1])
def test_a_schedule_calendar_override_with_a_bad_weekday_is_refused(bad_day: int) -> None:
    """The override reaches the engine without passing the calendar schemas."""
    with pytest.raises(ValidationError) as excinfo:
        ScheduleCreate(
            project_id=uuid4(),
            name="Master",
            metadata={"calendar": {"work_days": [bad_day, 0, 1, 2]}},
        )

    assert "metadata.calendar.work_days" in str(excinfo.value)


def test_updating_a_schedule_calendar_override_is_refused_too() -> None:
    """The update path carries the same override and needs the same refusal."""
    with pytest.raises(ValidationError):
        ScheduleUpdate(metadata={"calendar": {"work_days": [7, 0, 1]}})


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"calendar": {"work_days": [0, 1, 2, 3, 4]}},
        {"calendar": {"work_days": [6, 0, 1, 2, 3]}},
        {"calendar": {"exceptions": ["2026-01-01"]}},
        {"calendar": "not a mapping"},
        {"source": "xer_import"},
    ],
)
def test_a_schedule_without_a_bad_override_is_accepted(metadata: dict[str, Any]) -> None:
    """The negative control for entrance two.

    Metadata is free-form and carries unrelated things. A check that refused any of
    these would break schedule creation for everyone to guard one nested key.
    """
    schedule = ScheduleCreate(project_id=uuid4(), name="Master", metadata=metadata)

    assert schedule.metadata == metadata


def test_a_non_numeric_override_is_left_to_the_resolver() -> None:
    """Only the range is refused here, not the shape.

    ``resolve_calendar`` already coerces defensively and has to keep doing so for
    schedules written before this guard. Refusing shapes here as well would move
    that decision to a second place and let the two disagree.
    """
    schedule = ScheduleCreate(
        project_id=uuid4(),
        name="Master",
        metadata={"calendar": {"work_days": ["monday", None]}},
    )

    assert schedule.metadata["calendar"]["work_days"] == ["monday", None]


# ── The core check both doors call ──────────────────────────────────────────


@pytest.mark.parametrize(
    "work_days",
    [
        [7],
        [0, 1, 2, 3, 7],
        (8,),
        {-1, 0},
        frozenset({0, 1, 12}),
    ],
)
def test_the_core_check_refuses_a_weekday_outside_the_range(work_days: object) -> None:
    """Both doors delegate here, so the refusal is one decision in one place."""
    with pytest.raises(ValueError, match="Sunday is 6, not 7"):
        check_work_days_in_range(work_days, source="test")


@pytest.mark.parametrize(
    "work_days",
    [
        [0, 1, 2, 3, 4],
        [6, 0, 1, 2, 3],
        [0, 1, 2, 3, 4, 5, 6],
        [],
        None,
        "not a list",
        {"work_days": [7]},
        ["monday", None],
        [True, False],
    ],
)
def test_the_core_check_passes_everything_that_is_not_an_out_of_range_weekday(work_days: object) -> None:
    """It guards the range and nothing else.

    Shapes are the engine's business - :func:`app.core.cpm._parse_work_days`
    already drops what it cannot read, and that tolerance is what keeps its
    day-stepping loops terminating. Booleans are integers in Python and are
    ignored here rather than being read as weekday 0 or 1.
    """
    check_work_days_in_range(work_days, source="test")


def test_the_core_check_names_every_offending_value() -> None:
    """The message has to be enough to fix the row without reading the code."""
    with pytest.raises(ValueError) as excinfo:
        check_work_days_in_range([7, 0, 9, 1], source="metadata.calendar.work_days")

    message = str(excinfo.value)
    assert "[7, 9]" in message
    assert "metadata.calendar.work_days" in message
    assert "0..6" in message


# ── The two conventions must not quietly become one ─────────────────────────


def test_the_two_calendars_still_disagree_about_what_a_weekday_is() -> None:
    """The guards are mirrors, not copies, and neither may drift into the other.

    If this ever fails, one of the two ranges has been changed to match the other,
    which would silently make one calendar's valid weeks invalid.
    """
    assert (MIN_WEEKDAY, MAX_WEEKDAY) == (0, 6), "the Monday-zero range moved"

    # Sunday is 6 here and 7 in the ISO calendar; 0 is a valid weekday here and
    # never valid there. The two ranges overlap on 1..6 and must not be conflated.
    assert MIN_WEEKDAY == 0, "0 is Monday in this convention, not an error"
    assert MAX_WEEKDAY != 7, "7 is Sunday in the ISO calendar, never in this one"
