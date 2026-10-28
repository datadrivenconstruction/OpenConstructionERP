# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠One rule, three places it has to hold: a weekday is 1..7, Monday to Sunday.

``I18nFoundationService.get_working_days`` counts a working week by matching
each date's ``isoweekday()`` against the calendar's ``work_days``. That call
returns 1 through 7 and never 0, so any other number in the column matches no
date at all and shortens the week without telling anyone.

The platform shipped exactly that. ``seed_data/work_calendars.json`` carried
Saudi Arabia as ``[0, 1, 2, 3, 4]`` - Sunday to Thursday, written with Sunday
as 0 the way JavaScript's ``getDay()`` and cron count - and every install
counted Saudi Arabia as a four-day week. Nothing was raised, nothing was
logged; a duration converted to a finish date simply stretched.

Two convictions worth carrying forward from how it survived. The trap itself
was already known and written down: ``tests/modules/i18n_foundation/
test_i18n_foundation_calendar.py`` has a test for a calendar declaring
weekday 0, naming the zero-based convention as the cause. It used DE as its
stand-in, so nobody grepping for SA ever found it. And the input validation
that test called for would not have caught this row anyway, because
``seed.py`` constructs ``WorkCalendar(...)`` straight on the ORM: the bad
value came in through the wall, not the door. So this file checks the wall
(the seed file), the door (the write schemas) and the repair for the installs
that already swallowed it (the migration), rather than any one of them.

The two zero-based conventions are both live in this repo, which is why the
seed file is checked rather than trusted. ``app/core/calendar.py``,
``app/core/cpm.py``, the schedule module and the work-calendar UI all count
Monday as 0 through ``date.weekday()``. This module counts Monday as 1. The
two disagree about ``[0, 1, 2, 3, 4]`` without either being obviously wrong on
its face, and that is exactly the kind of value a reviewer's eye slides over.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.i18n_foundation.schemas import (
    WorkCalendarCreate,
    WorkCalendarResponse,
    WorkCalendarUpdate,
)

_BACKEND = Path(__file__).resolve().parents[2]
_SEED = _BACKEND / "app" / "modules" / "i18n_foundation" / "seed_data" / "work_calendars.json"
_MIGRATION = _BACKEND / "alembic" / "versions" / "v3303_work_calendar_iso_weekdays.py"

# The tree carried 30 calendars of five days each when this was written. The
# floors are the vacuity guard: a file that stopped parsing, a survey that
# stopped surveying, or rows that lost their ``work_days`` would otherwise
# report a clean zero offenders over nothing at all. Two floors and not one,
# because a row with ``work_days: []`` passes a row count while contributing
# no value to inspect - the same blindness one level down.
_MIN_ROWS = 25
_MIN_WEEKDAY_VALUES = 100


# ── The wall: the seed file ──────────────────────────────────────────────────


def _seed_rows() -> list[dict[str, Any]]:
    return json.loads(_SEED.read_text(encoding="utf-8"))


def _survey(rows: list[dict[str, Any]]) -> tuple[int, list[str]]:
    """Return ``(weekday values inspected, offenders)`` for a set of seed rows.

    A plain function so the controls below can run the real check over
    perturbed input instead of re-implementing it and proving only that
    ``1 <= x <= 7`` works in Python.
    """
    inspected = 0
    offenders: list[str] = []

    for row in rows:
        country = row.get("country_code", "<no country_code>")
        work_days = row.get("work_days")

        if not isinstance(work_days, list) or not work_days:
            offenders.append(f"{country} declares no working week at all: work_days={work_days!r}")
            continue

        for day in work_days:
            inspected += 1
            if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 7:
                offenders.append(
                    f"{country} declares weekday {day!r} in work_days={work_days!r}, outside the ISO "
                    f"range 1..7. isoweekday() never returns it, so that day is silently dropped from "
                    f"the working week. Monday is 1 and Sunday is 7 - Sunday is not 0."
                )

    return inspected, offenders


def test_every_seeded_weekday_is_an_iso_weekday() -> None:
    """No seeded calendar may carry a weekday the counting code cannot match."""
    inspected, offenders = _survey(_seed_rows())

    print(f"\nInspected {inspected} weekday values across {len(_seed_rows())} seeded work calendars.")

    assert offenders == [], "work_calendars.json declares weekdays outside 1..7:\n" + "\n".join(offenders)


def test_the_survey_actually_surveyed_something() -> None:
    """Guards the vacuous pass: zero offenders over zero values proves nothing."""
    rows = _seed_rows()
    inspected, _ = _survey(rows)

    assert len(rows) >= _MIN_ROWS, (
        f"only {len(rows)} work calendars in the seed file - it held 30 when this check was written. "
        f"Either the file stopped parsing or the check is now reading almost nothing."
    )
    assert inspected >= _MIN_WEEKDAY_VALUES, (
        f"only {inspected} weekday values inspected across {len(rows)} rows - the rows are there but "
        f"their working weeks are not, so the check has gone vacuous one level down."
    )


def test_a_zero_based_saudi_week_is_caught() -> None:
    """The control: put the shipped defect back and the check must go red.

    Every other row is ``[1, 2, 3, 4, 5]`` and answers the same whether this
    check exists or not, so a green run over today's data is weak evidence.
    This is the evidence.

    Measured as a delta rather than as "exactly one offender", so that this
    control keeps testing its own subject if some other row in the file is
    ever wrong too.
    """
    inspected_before, before = _survey(_seed_rows())
    # A control that plants a defect needs its subject clean to begin with. If
    # SA is already an offender the delta below is zero and this test fails
    # with arithmetic instead of a reason, so say the reason out loud.
    assert not [line for line in before if line.startswith("SA ")], (
        "the seed file already declares a non-ISO Saudi week, so planting one measures nothing. "
        "That is the shipped defect itself - test_every_seeded_weekday_is_an_iso_weekday is the "
        f"test that reports it, and this control cannot run until it is fixed: {before}"
    )

    rows = copy.deepcopy(_seed_rows())
    saudi = [row for row in rows if row["country_code"] == "SA"]
    assert len(saudi) == 1, "expected exactly one SA calendar in the seed file"
    saudi[0]["work_days"] = [0, 1, 2, 3, 4]

    inspected, offenders = _survey(rows)

    planted = [line for line in offenders if line not in before]
    assert len(offenders) == len(before) + 1, offenders
    assert len(planted) == 1, planted
    assert "SA" in planted[0]
    assert "0" in planted[0]
    # Planting a bad value must not change how much was inspected.
    assert inspected == inspected_before


def test_a_calendar_with_no_working_week_is_caught() -> None:
    """The second control: an empty week is an offender, not an abstention.

    Without this branch a row could pass the row-count floor while offering
    nothing to check, which is how a shrinking population reports clean.
    """
    _, before = _survey(_seed_rows())

    rows = copy.deepcopy(_seed_rows())
    emptied = rows[0]["country_code"]
    rows[0]["work_days"] = []

    _, offenders = _survey(rows)

    planted = [line for line in offenders if line not in before]
    assert len(planted) == 1, planted
    assert "no working week" in planted[0]
    assert emptied in planted[0]


def test_the_seed_file_this_check_reads_still_exists() -> None:
    """A moved or renamed seed file must break the check rather than empty it."""
    assert _SEED.is_file(), f"{_SEED} is gone; this check is reading nothing"


# ── The door: the write schemas ──────────────────────────────────────────────


@pytest.mark.parametrize("bad_day", [0, 8, -1, 12])
def test_creating_a_calendar_with_a_non_iso_weekday_is_refused(bad_day: int) -> None:
    """The API refuses what the counting code cannot read, instead of storing it."""
    with pytest.raises(ValidationError) as excinfo:
        WorkCalendarCreate(
            country_code="SA",
            name="Saudi Arabia Standard 2026",
            year="2026",
            work_days=[bad_day, 1, 2, 3],
        )

    assert "work_days" in str(excinfo.value)


@pytest.mark.parametrize("bad_day", [0, 8, -1])
def test_updating_a_calendar_to_a_non_iso_weekday_is_refused(bad_day: int) -> None:
    """The update path is the one an operator actually reaches for."""
    with pytest.raises(ValidationError):
        WorkCalendarUpdate(work_days=[bad_day, 1, 2, 3])


def test_sunday_to_thursday_is_accepted_as_seven_one_two_three_four() -> None:
    """The negative control: the guard must not refuse the week SA actually has.

    A range check that rejected Sunday would be a second defect wearing the
    first one's clothes, and every other seeded row would still pass.
    """
    created = WorkCalendarCreate(
        country_code="SA",
        name="Saudi Arabia Standard 2026",
        year="2026",
        work_days=[7, 1, 2, 3, 4],
    )
    updated = WorkCalendarUpdate(work_days=[7, 1, 2, 3, 4])

    assert created.work_days == [7, 1, 2, 3, 4]
    assert updated.work_days == [7, 1, 2, 3, 4]


def test_reading_back_a_row_written_before_the_guard_still_works() -> None:
    """Deliberate asymmetry: the response schema stays unconstrained.

    A database seeded before the guard existed still holds the old value.
    Refusing to serialise it would turn a wrong number into a 500 on the very
    screen an operator would use to correct it.
    """
    from uuid import uuid4

    response = WorkCalendarResponse(
        id=uuid4(),
        country_code="SA",
        name="Saudi Arabia Standard 2026",
        name_translations=None,
        year="2026",
        work_hours_per_day="8",
        work_days=[0, 1, 2, 3, 4],
        exceptions=[],
        metadata_={},
        created_at="2026-08-23T00:00:00",
        updated_at="2026-08-23T00:00:00",
    )

    assert response.work_days == [0, 1, 2, 3, 4]


# ── The repair: what existing installs get ───────────────────────────────────


def _migration() -> Any:
    """Side-load ``v3303`` - ``alembic/versions`` is not a package.

    Same approach as ``tests/unit/test_epic_c_backfill.py``. The module imports
    ``alembic`` and ``sqlalchemy`` and nothing else, so it loads without a
    database, which is what lets the repair rule be tested shape by shape.
    """
    spec = importlib.util.spec_from_file_location("v3303_work_calendar_iso_weekdays", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_shipped_saudi_row_is_repaired_to_sunday_through_thursday() -> None:
    repair, warning = _migration()._classify("SA", [0, 1, 2, 3, 4])

    assert repair == [7, 1, 2, 3, 4]
    assert warning is None


def test_the_repair_matches_what_the_seed_file_now_says() -> None:
    """The migration and the seed must agree, or new and old installs diverge."""
    repair, _ = _migration()._classify("SA", [0, 1, 2, 3, 4])
    seeded = next(row["work_days"] for row in _seed_rows() if row["country_code"] == "SA")

    assert repair == seeded


def test_running_the_repair_twice_changes_nothing_the_second_time() -> None:
    """Idempotence, on the data rather than on a version marker."""
    module = _migration()
    repair, _ = module._classify("SA", [0, 1, 2, 3, 4])

    again, warning = module._classify("SA", repair)

    assert again is None
    assert warning is None


@pytest.mark.parametrize("work_days", [[1, 2, 3, 4, 5], [7, 1, 2, 3, 4], [1, 2, 3, 4], [1, 2, 3, 4, 5, 6, 7]])
def test_a_valid_calendar_is_left_alone(work_days: list[int]) -> None:
    """Whatever a deployment edited its calendars to, if it is ISO it stays."""
    repair, warning = _migration()._classify("DE", work_days)

    assert repair is None
    assert warning is None


@pytest.mark.parametrize(
    ("country_code", "work_days"),
    [
        ("QA", [0, 1, 2, 3, 4]),  # Same broken week, a country we never shipped it for.
        ("SA", [6, 0, 1, 2, 3]),  # Saudi, but not the value the seeder wrote.
        ("SA", [8]),
        ("DE", [-1, 1, 2]),
        ("SA", []),
        ("SA", "not json at all"),
        ("SA", [True, 2, 3]),
    ],
)
def test_an_unreadable_week_is_reported_and_not_guessed_at(country_code: str, work_days: object) -> None:
    """Anything else out of range is named in the upgrade output, never rewritten.

    Two zero-based conventions are live in this platform at once, so an
    unknown row's number does not say which week was meant. Guessing would
    swap one silently wrong week for another.
    """
    repair, warning = _migration()._classify(country_code, work_days)

    assert repair is None
    assert warning is not None
    assert country_code in warning


def test_a_json_column_arriving_as_text_is_still_repaired() -> None:
    """Some drivers hand back the text of a JSON column rather than the value."""
    repair, warning = _migration()._classify("SA", "[0, 1, 2, 3, 4]")

    assert repair == [7, 1, 2, 3, 4]
    assert warning is None


def test_the_migration_this_check_reads_still_exists() -> None:
    assert _MIGRATION.is_file(), f"{_MIGRATION} is gone; the repair check is reading nothing"
