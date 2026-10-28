# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A holiday the engine cannot read is refused at the write, not dropped later.

``cpm._parse_exceptions`` used to swallow an unreadable exception date with a
bare ``except ValueError: pass``. The day was then scheduled as a working day,
and nothing downstream could tell it from a day nobody had marked. A user could
mark a holiday, have the request accepted, and watch the system work the day.

These tests pin the three parts of the answer:

* the engine still computes when it meets an unreadable entry, because its
  day-stepping loops have to terminate, but it now names the value it dropped,
* the write schema refuses the entry outright, beside the ``work_days`` check
  that already refuses its sibling field,
* the refusal is narrow. An unambiguous but untidy entry is normalised and
  accepted rather than rejected, because a date pasted from a spreadsheet
  carries a trailing space and an export writes an ISO datetime.

The control is the first test and it is load-bearing: a suite in which every
case raises looks identical to a suite in which every case is correctly refused,
so one valid holiday has to be shown moving a real finish date first.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.cpm import (
    ACCEPTED_EXCEPTION_FORMS,
    _parse_exceptions,
    calculate_cpm,
    canonical_exception_dates,
    normalise_exception_date,
)
from app.modules.schedule.schemas import ScheduleCreate

# 2026-04-27 is a Monday, so a five-day activity on a Mon-Fri week finishes at
# calendar-day offset 7. 2026-04-29 is the Wednesday inside it: marking it a
# holiday has to push the finish to 8, and that one day is the whole signal
# these tests are built on.
_PROJECT_START = "2026-04-27"
_HOLIDAY = date(2026, 4, 29)
_FINISH_WITHOUT_HOLIDAY = 7
_FINISH_WITH_HOLIDAY = 8


def _finish(exceptions: list) -> int:
    """Return the early finish of one five-day activity under ``exceptions``."""
    result = asyncio.run(
        calculate_cpm(
            [{"id": "A", "duration": 5, "name": "A"}],
            [],
            calendar={"work_days": [0, 1, 2, 3, 4], "exceptions": exceptions},
            project_start_date=_PROJECT_START,
        )
    )
    return result[0]["early_finish"]


def _schedule(exceptions: object) -> ScheduleCreate:
    """Build a schedule whose calendar override carries ``exceptions``."""
    return ScheduleCreate(
        project_id=uuid4(),
        name="S",
        metadata={"calendar": {"work_days": [0, 1, 2, 3, 4], "exceptions": exceptions}},
    )


# -- The control ---------------------------------------------------------------


def test_a_holiday_the_engine_can_read_moves_the_finish() -> None:
    """Without this, a suite where everything fails looks like a suite that passes."""
    assert _finish([]) == _FINISH_WITHOUT_HOLIDAY
    assert _finish([_HOLIDAY.isoformat()]) == _FINISH_WITH_HOLIDAY


def test_the_defect_itself_an_unreadable_holiday_is_worked() -> None:
    """The engine keeps scheduling, and the day is worked. This is why the write refuses."""
    assert _finish(["01/05/2026"]) == _FINISH_WITHOUT_HOLIDAY


# -- Accepted: unambiguous, however it was spelled -----------------------------


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param("2026-04-29", id="iso-date"),
        pytest.param("2026-04-29 ", id="trailing-space-from-a-spreadsheet"),
        pytest.param("  2026-04-29", id="leading-space"),
        pytest.param("2026-04-29T00:00:00", id="iso-datetime-t-separator"),
        pytest.param("2026-04-29 00:00:00", id="iso-datetime-space-separator"),
        pytest.param("20260429", id="basic-iso-already-parsed-before-this-change"),
        pytest.param(date(2026, 4, 29), id="date-object"),
        pytest.param(datetime(2026, 4, 29, 9, 30), id="datetime-object"),
    ],
)
def test_every_unambiguous_spelling_moves_the_finish(entry: object) -> None:
    """Each of these names 2026-04-29 and nothing else, so each has to count.

    The ``datetime`` case is a second silent miss that needed no malformed
    string at all: ``datetime`` subclasses ``date``, so the old parse stored it
    unchanged, and a ``datetime`` never compares equal to the ``date`` the
    engine tests membership against. It was dropped as quietly as bad text.
    """
    assert normalise_exception_date(entry) == _HOLIDAY
    assert _finish([entry]) == _FINISH_WITH_HOLIDAY


def test_the_write_stores_one_canonical_spelling() -> None:
    """Normalising at the boundary is what settles the ISO-string reader elsewhere.

    ``progress_math._is_working`` tests ``d.isoformat() not in self.holidays``,
    a string comparison with no parse in it, so a stored ``"2026-04-29 "`` would
    match no date there however tolerant the CPM engine became.
    """
    stored = _schedule(["2026-04-29 ", "20260430", datetime(2026, 5, 1, 8, 0)])
    assert stored.metadata["calendar"]["exceptions"] == ["2026-04-29", "2026-04-30", "2026-05-01"]


# -- Refused: ambiguous or unreadable ------------------------------------------


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param("01/05/2026", id="ambiguous-day-first-or-month-first"),
        pytest.param("29/04/2026", id="ambiguous-even-when-only-one-reading-is-a-real-date"),
        pytest.param("2026-04-32", id="no-such-day"),
        pytest.param("2026-4-29", id="unpadded-is-not-an-iso-form"),
        pytest.param("next tuesday", id="prose"),
        pytest.param("", id="empty"),
        pytest.param(None, id="null"),
        pytest.param(20260429, id="int"),
    ],
)
def test_the_write_refuses_what_names_no_single_day(entry: object) -> None:
    assert normalise_exception_date(entry) is None
    with pytest.raises(ValidationError) as caught:
        _schedule([entry])
    assert "metadata.calendar.exceptions" in str(caught.value)


def test_the_refusal_names_the_offending_value_and_the_accepted_forms() -> None:
    """A bare 'invalid date' teaches a spreadsheet user nothing. The message has to do both."""
    with pytest.raises(ValidationError) as caught:
        _schedule(["01/05/2026"])
    message = str(caught.value)
    assert "'01/05/2026'" in message
    assert ACCEPTED_EXCEPTION_FORMS in message


def test_a_bare_string_is_refused_rather_than_read_character_by_character() -> None:
    """``"2026-04-29"`` in the slot iterates to ten characters, each one unreadable."""
    with pytest.raises(ValidationError) as caught:
        _schedule("2026-04-29")
    assert "not a list" in str(caught.value)


def test_a_valid_list_is_accepted_so_the_refusals_above_are_not_vacuous() -> None:
    assert canonical_exception_dates(["2026-04-29"], source="s") == ["2026-04-29"]
    assert canonical_exception_dates(None, source="s") is None


# -- Rows already stored: findable rather than fixed ---------------------------


def test_the_engine_names_the_value_it_dropped(caplog: pytest.LogCaptureFixture) -> None:
    """A write-time refusal does nothing for rows already in the database.

    Nothing revalidates them, so the log line is the only thing that tells a
    dropped holiday apart from a day nobody marked. It does not repair the row;
    it makes the row findable, which is the difference between a defect and a
    mystery.
    """
    with caplog.at_level(logging.WARNING, logger="app.core.cpm"):
        assert _parse_exceptions({"exceptions": ["01/05/2026", "2026-04-29"]}) == {_HOLIDAY}
    assert len(caplog.records) == 1
    assert "01/05/2026" in caplog.records[0].getMessage()


def test_a_stored_bare_string_warns_once_rather_than_once_per_character(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.core.cpm"):
        assert _parse_exceptions({"exceptions": "2026-04-29"}) == set()
    assert len(caplog.records) == 1


def test_a_readable_calendar_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    """The negative control for the two tests above."""
    with caplog.at_level(logging.WARNING, logger="app.core.cpm"):
        assert _parse_exceptions({"exceptions": ["2026-04-29"]}) == {_HOLIDAY}
    assert caplog.records == []
