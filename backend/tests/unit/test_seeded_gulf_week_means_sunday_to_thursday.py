# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The seeded Gulf week must *mean* Sunday to Thursday, not merely be legal ISO.

How this differs from the two guards beside it, so neither gets deleted as a
duplicate of the other:

* ``test_work_calendar_weekdays_are_iso.py`` is a **range** guard. It asserts
  every value in the seed file, the write schemas and the v3303 migration falls
  inside 1..7. It would pass unchanged if Saudi Arabia were seeded
  ``[1, 2, 3, 4, 5]`` - perfectly legal ISO, and the wrong week.
* ``test_work_calendar_weekdays_are_mon0.py`` is the same range guard pointed at
  the platform's other axis, where the mistake is a 7 rather than a 0.
* This file is a **meaning** guard, and it is the only one of the three that
  runs the numbers against real dates. It asks what the seeded row does to a
  Sunday and to a Friday.

Why that shape and not "Saudi Arabia has five working days". Both readings of
``[7, 1, 2, 3, 4]`` are five days long. Read on the ISO axis it is Sunday to
Thursday, which is correct; read on the Monday-zero axis the 7 matches nothing
(``date.weekday()`` tops out at 6), Sunday leaves the week and Friday joins it,
and the count is four. A cardinality assertion passes under both and proves
nothing, which is exactly how the original defect survived review: the shipped
row was ``[0, 1, 2, 3, 4]``, five entries, and ``isoweekday()`` never returns 0,
so Saudi Arabia quietly ran a four-day week until ``v3303_work_calendar_iso_
weekdays`` repaired it. Sunday and Friday are the two days that tell the axes
apart, so they are what this file asserts on.

``test_control_the_same_row_read_on_the_monday_zero_axis_inverts_it`` is a
deliberate negative control, not a defect: it feeds the seeded list to a
``date.weekday()`` matcher and shows the week come back inverted. Without it the
assertions above would pass over any row at all and this file would be vacuous.
"""

from __future__ import annotations

import ast
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
_SEED = _BACKEND / "app" / "modules" / "i18n_foundation" / "seed_data" / "work_calendars.json"
_CONSUMER = _BACKEND / "app" / "modules" / "i18n_foundation" / "service.py"

#: Saudi Arabia is the row the defect actually hit and the only Gulf calendar in
#: the seed file as committed, so it is checked unconditionally: it is this
#: file's floor against going vacuous.
_GULF_REQUIRED = ("SA",)

#: The other four Gulf states. Checked when present and skipped by name when
#: not, deliberately. They are not in the seed file at HEAD; a working tree that
#: carries them is carrying somebody's unfinished change, and a test that
#: demanded them would be green on that tree and red on a clean checkout of the
#: same commit - the failure would then read "the population shrank" and send
#: the next reader hunting a deletion that never happened. Their absence is a
#: missing-country question and belongs to the coverage probes in
#: ``app/core/country_coverage.py``; their *axis*, once they exist, is this
#: file's business.
_GULF_OPTIONAL = ("QA", "KW", "BH", "OM")

_GULF = _GULF_REQUIRED + _GULF_OPTIONAL

#: Anchor dates in the seeded year. Chosen in January because no seeded Gulf
#: calendar carries a January holiday, so a holiday cannot mask a weekday.
_SUNDAY = date(2026, 1, 4)
_FRIDAY = date(2026, 1, 2)
_SATURDAY = date(2026, 1, 3)
_MONDAY = date(2026, 1, 5)
_THURSDAY = date(2026, 1, 8)

#: Vacuity floor. The file carried 32 calendars at HEAD when this was written;
#: a file that stopped parsing, or a survey that stopped surveying, would
#: otherwise report clean over nothing.
_MIN_ROWS = 30


def _seed_rows() -> list[dict[str, Any]]:
    return json.loads(_SEED.read_text(encoding="utf-8"))


def _week_for(country_code: str) -> set[int] | None:
    """The seeded working week for a country, or ``None`` if it has no calendar."""
    for row in _seed_rows():
        if row["country_code"] == country_code:
            return set(row["work_days"])
    return None


def _get_working_days_source() -> str:
    """The source of ``I18nFoundationService.get_working_days``, by AST.

    Located by name rather than by matching the counting line as a string: a
    rename of a local, or a reflow, would make a literal match fail while
    announcing that the consumer had switched axes, which is the wrong reason
    and would send the next reader after a defect that is not there.
    """
    source = _CONSUMER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "get_working_days":
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(
        "get_working_days is no longer defined in i18n_foundation/service.py. It is the only thing "
        "that computes a date from a seeded work_days row, so if it moved, find where it went and "
        "point this test at it - do not delete this test."
    )


def test_the_seed_file_still_carries_a_population_worth_surveying() -> None:
    rows = _seed_rows()
    assert len(rows) >= _MIN_ROWS, f"only {len(rows)} seeded calendars, below the {_MIN_ROWS} floor"
    assert {row["country_code"] for row in rows} >= set(_GULF_REQUIRED)


def _gulf_week_or_skip(country_code: str) -> set[int]:
    week = _week_for(country_code)
    if week is None:
        if country_code in _GULF_REQUIRED:
            raise AssertionError(
                f"{country_code} has no seeded work calendar. It is in the seed file as committed, "
                "so this is a deletion, not a tree that predates the other Gulf rows."
            )
        pytest.skip(f"{country_code} has no seeded work calendar in this tree; nothing to check its axis on")
    return week


@pytest.mark.parametrize("country_code", _GULF)
def test_seeded_gulf_week_puts_sunday_in_and_friday_out(country_code: str) -> None:
    """Sunday works, Friday does not - the two days that tell the axes apart."""
    week = _gulf_week_or_skip(country_code)

    assert _SUNDAY.isoweekday() in week, (
        f"{country_code} seeds {sorted(week)}, which does not make Sunday a working day. "
        "A Gulf week that drops Sunday has been read on the wrong axis."
    )
    assert _FRIDAY.isoweekday() not in week, (
        f"{country_code} seeds {sorted(week)}, which makes Friday a working day. "
        "Friday is the Gulf weekend; it appears only when the week is read on the wrong axis."
    )
    assert _SATURDAY.isoweekday() not in week
    for working in (_MONDAY, _THURSDAY):
        assert working.isoweekday() in week, f"{country_code} does not work on {working:%A}"


@pytest.mark.parametrize("country_code", _GULF)
def test_control_the_same_row_read_on_the_monday_zero_axis_inverts_it(country_code: str) -> None:
    """Negative control. Not a defect - a demonstration that the test above discriminates.

    The very same stored list, matched against ``date.weekday()`` instead of
    ``date.isoweekday()``, is the crossed-axis failure mode: the 7 matches no
    day at all, Sunday falls out of the week and Friday falls into it. If this
    control ever stops inverting, the assertions above have stopped being able
    to tell the two axes apart and this file no longer guards anything.
    """
    week = _gulf_week_or_skip(country_code)

    assert _SUNDAY.weekday() not in week, "control is not inverting: Sunday survived the Monday-zero reading"
    assert _FRIDAY.weekday() in week, "control is not inverting: Friday did not appear under the Monday-zero reading"
    assert len({d for d in range(7) if d in week}) == 4, (
        "control is not inverting: the Monday-zero reading should count four days, not five"
    )


def test_a_monday_to_friday_country_is_not_what_makes_the_gulf_assertions_pass() -> None:
    """Germany, the same assertions, the opposite answers.

    Guards against an assertion that would hold for every row in the file - if
    Germany also passed the Gulf shape, the shape would be measuring nothing.
    """
    week = _week_for("DE")
    assert week is not None, "DE has no seeded work calendar; the control has nothing to contrast against"

    assert _MONDAY.isoweekday() in week
    assert _FRIDAY.isoweekday() in week
    assert _SUNDAY.isoweekday() not in week
    assert _SATURDAY.isoweekday() not in week


def test_the_consumer_still_counts_these_numbers_with_isoweekday() -> None:
    """The axis is a property of the reader, so pin the reader, not a copy of it.

    ``I18nFoundationService.get_working_days`` is the only thing that computes a
    date from ``WorkCalendar.work_days``. The assertions above reimplement its
    one-line match because the method is async and needs a database; this test
    is what keeps that reimplementation honest. Switch the consumer to
    ``weekday()`` and the seeded rows become wrong without a single one of them
    changing, so a guard that only reads the data would stay green.
    """
    body = _get_working_days_source()

    assert ".isoweekday()" in body, (
        "get_working_days in i18n_foundation/service.py no longer mentions isoweekday(). Either it "
        "switched to the Monday-zero axis - in which case every seeded work_days row is now on the "
        "wrong axis - or the counting loop was refactored out of this method. Read it before "
        "believing either; this assertion cannot tell the two apart."
    )
    assert ".weekday()" not in body.replace(".isoweekday()", ""), (
        "get_working_days now calls date.weekday() as well as isoweekday(). The seeded work_days "
        "column is ISO (Monday = 1 .. Sunday = 7); a weekday() call against it shifts every day by "
        "one and drops Sunday out of the week entirely."
    )
