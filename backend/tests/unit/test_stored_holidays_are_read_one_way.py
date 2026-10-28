# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every reader of a stored calendar reads a holiday the same way, and says so.

There used to be four conventions for the same stored column. One reader
truncated each entry to ten characters, one passed it through whole, one
truncated it again elsewhere, and the only parser that validated had no
production callers. A holiday written ``01/05/2026`` was worked as an ordinary
day by all of them, and because a truncation has no failure mode, none of them
logged anything about it.

Two properties are asserted here and they are different properties. That the
readers agree, which is what makes one stored value mean one thing. And that an
unreadable entry is reported, which is what makes the disagreement findable at
all rather than showing up as a schedule that is quietly one day out.
"""

import logging
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.core.cpm import _parse_exceptions, readable_exception_dates
from app.modules.schedule.progress_math import WorkCalendar, _parse_date
from app.modules.schedule_advanced.service import validate_commitment

#: The day under test throughout: a Friday, so an ordinary working day unless
#: the stored holiday is understood.
HOLIDAY = date(2026, 5, 1)

#: Spellings that name that day. A reader that understands the column reports
#: every one of them as a holiday.
SPELLINGS = [
    pytest.param("2026-05-01", id="iso"),
    pytest.param("20260501", id="compact"),
    pytest.param("2026-05-01T00:00:00", id="iso-datetime-T"),
    pytest.param("2026-05-01 00:00:00", id="iso-datetime-space"),
    pytest.param("2026-05-01T09:30:00", id="iso-datetime-with-time"),
    pytest.param(" 2026-05-01 ", id="untrimmed"),
    pytest.param(date(2026, 5, 1), id="date-object"),
    pytest.param(datetime(2026, 5, 1, 9, 30), id="datetime-object"),
]

#: Values that name no day. Every reader drops them, and says which it dropped.
UNREADABLE = [
    pytest.param("01/05/2026", id="slashed-ambiguous"),
    pytest.param("2026-5-1", id="unpadded"),
    pytest.param("2026-13-01", id="impossible-month"),
    pytest.param("next friday", id="prose"),
]


# ── The three live readers, each asked the same question ──────────────────


def _progress_reader(stored: list) -> bool:
    """Is the day worked, according to the progress engine's calendar?"""
    cal = WorkCalendar(holidays=frozenset(readable_exception_dates(stored, source="test calendar")))
    return cal.is_working_day(HOLIDAY.isoformat())


def _cpm_reader(stored: list) -> bool:
    """Is the day worked, according to the CPM engine?"""
    canonical = readable_exception_dates(stored, source="test calendar")
    return HOLIDAY not in _parse_exceptions({"work_days": [0, 1, 2, 3, 4], "exceptions": canonical})


def _commitment_reader(stored: list) -> bool:
    """Is the day worked, according to the commitment validator?"""
    ok, errors = validate_commitment(
        {"planned_start": HOLIDAY.isoformat(), "planned_finish": HOLIDAY.isoformat()},
        {"work_days": [0, 1, 2, 3, 4], "holidays": stored},
    )
    return not any("holiday" in e for e in errors)


READERS = [
    pytest.param(_progress_reader, id="progress-engine"),
    pytest.param(_cpm_reader, id="cpm-engine"),
    pytest.param(_commitment_reader, id="commitment-validator"),
]


# ── Control ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("reader", READERS)
def test_an_ordinary_friday_is_worked(reader) -> None:
    """Control. Every assertion below is that some day is *not* worked, so
    without this they would all pass against a reader that never works a day."""
    assert reader([]) is True


@pytest.mark.parametrize("reader", READERS)
def test_the_canonical_spelling_is_understood(reader) -> None:
    assert reader(["2026-05-01"]) is False


# ── One convention: every reader, every spelling ──────────────────────────


@pytest.mark.parametrize("reader", READERS)
@pytest.mark.parametrize("stored", SPELLINGS)
def test_every_reader_takes_the_day_off(reader, stored) -> None:
    """The collapse, asserted directly.

    Before this, the leading-space spelling alone produced two answers: the CPM
    engine took the day off and the other two worked it, so one stored value
    meant two different schedules depending on which reader looked at it.
    """
    assert reader([stored]) is False, f"{stored!r} was read as an ordinary working day"


@pytest.mark.parametrize("stored", SPELLINGS)
def test_the_readers_agree_with_each_other(stored) -> None:
    """Stated as agreement rather than as three separate correct answers.

    A future reader that is wrong in the same way as the others would pass the
    test above only if it were also wrong; this one fails the moment any two
    of them differ.
    """
    verdicts = {reader.values[0]([stored]) for reader in READERS}
    assert len(verdicts) == 1, f"{stored!r} is read differently by different readers"


@pytest.mark.parametrize("reader", READERS)
@pytest.mark.parametrize("stored", UNREADABLE)
def test_a_value_naming_no_day_is_dropped_by_every_reader(reader, stored) -> None:
    """Dropped, not raised. The write schemas refuse these now, so a row
    carrying one was stored before that guard existed, and a read path that
    failed on it would hide the calendar an operator needs to see."""
    assert reader([stored]) is True


# ── Reported, which is the half that was missing ──────────────────────────


@pytest.mark.parametrize("stored", UNREADABLE)
def test_dropping_an_unreadable_entry_is_logged(stored, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="app.core.cpm"):
        readable_exception_dates([stored], source="calendar 7 holidays")
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert repr(stored) in message, "the log must name the entry that was dropped"
    assert "calendar 7 holidays" in message, "and which calendar to correct"
    assert "working day" in message, "and what happens as a result"


def test_a_readable_calendar_logs_nothing(caplog) -> None:
    """Negative control. Without it, a reader that warned on every entry would
    pass every assertion above."""
    with caplog.at_level(logging.WARNING, logger="app.core.cpm"):
        result = readable_exception_dates([p.values[0] for p in SPELLINGS], source="calendar 7 holidays")
    assert result == ["2026-05-01"] * len(SPELLINGS)
    assert caplog.records == []


def test_an_empty_entry_is_dropped_without_a_warning(caplog) -> None:
    """A documented decision, asserted so it stays one.

    A blank carries no date to misread. Warning about it would put a line in
    the log on every reschedule for the life of the row.
    """
    with caplog.at_level(logging.WARNING, logger="app.core.cpm"):
        result = readable_exception_dates(["", "   ", None, "2026-05-01"], source="calendar 7 holidays")
    assert result == ["2026-05-01"]
    assert caplog.records == []


# ── An unreadable COLUMN refuses, where an unreadable ENTRY drops ─────────


UNREADABLE_COLUMNS = [
    pytest.param("2026-05-01", id="bare-string"),
    pytest.param(5, id="number"),
    pytest.param({"2026-05-01": True}, id="mapping"),
]


@pytest.mark.parametrize("column", UNREADABLE_COLUMNS)
def test_a_column_that_is_not_a_list_is_refused(column) -> None:
    """Not a matter of degree with the entry case above.

    One bad entry loses one day. A column that is not a calendar loses every
    holiday in it, and the caller cannot tell, because a schedule computed from
    no holidays looks exactly like a schedule computed from a calendar that
    happened to have none. These dates are planned against.
    """
    with pytest.raises(ValueError):
        readable_exception_dates(column, source="calendar 7 holidays")


def test_the_refusal_names_the_calendar_and_what_it_found() -> None:
    with pytest.raises(ValueError) as err:
        readable_exception_dates("2026-05-01", source="calendar 7 holidays")
    message = str(err.value)
    assert "calendar 7 holidays" in message, "the operator cannot fix a row the error does not name"
    assert "str" in message, "and needs to know what was stored instead of a list"


def test_an_absent_column_is_an_empty_calendar_rather_than_an_unreadable_one() -> None:
    """``None`` means there is no calendar, not one that cannot be read. The
    column itself is ``nullable=False``, so this is the caller's own default."""
    assert readable_exception_dates(None, source="calendar 7 holidays") == []


def test_the_pre_change_form_shredded_a_bare_string_in_silence() -> None:
    """Negative control, and a correction to the record.

    The old readers did not fail on a bare string. A generator over one walks it
    character by character, so ten junk entries silently replaced the calendar
    and nothing was logged. There was no honest failure here to restore, which
    is why this is a new refusal rather than a reinstated one.
    """
    shredded = [str(h)[:10] for h in "2026-05-01"]
    assert len(shredded) == 10
    assert all(len(c) == 1 for c in shredded)
    assert "2026-05-01" not in shredded


def test_the_refusal_survives_the_trip_through_a_reader() -> None:
    """A guard is worth nothing if the reader flattens the column before it."""
    with pytest.raises(ValueError):
        validate_commitment(
            {"planned_start": HOLIDAY.isoformat(), "planned_finish": HOLIDAY.isoformat()},
            {"work_days": [0, 1, 2, 3, 4], "holidays": "2026-05-01"},
        )


def test_a_stored_column_is_not_flattened_before_the_guard_sees_it() -> None:
    """The ORM branch called ``list()`` on the column first.

    That turned a bare string into ten characters before the guard could refuse
    it, so the whole-column case was unreachable by that route and one corrupt
    row produced ten separate warnings instead of one refusal.
    """
    cal = SimpleNamespace(work_days=[0, 1, 2, 3, 4], holidays="2026-05-01")
    with pytest.raises(ValueError):
        validate_commitment({"planned_start": HOLIDAY.isoformat(), "planned_finish": HOLIDAY.isoformat()}, cal)


def test_a_stored_list_still_reads_normally_through_the_orm_branch() -> None:
    """Control for the two above, which would pass against a branch that had
    simply been broken."""
    cal = SimpleNamespace(work_days=[0, 1, 2, 3, 4], holidays=["2026-05-01"])
    _, errors = validate_commitment({"planned_start": HOLIDAY.isoformat(), "planned_finish": HOLIDAY.isoformat()}, cal)
    assert any("holiday" in e for e in errors)


# ── The latent trap, given a tripwire ─────────────────────────────────────


def _pre_change_parse_date(iso):
    """``_parse_date`` exactly as it stood, kept as the control below."""
    if isinstance(iso, date):
        return iso
    return date.fromisoformat(str(iso)[:10])


def test_a_datetime_is_narrowed_to_the_day_it_falls_on() -> None:
    assert _parse_date(datetime(2026, 5, 1, 9, 30)) == HOLIDAY


def test_a_holiday_holds_when_the_day_arrives_as_a_datetime() -> None:
    """The defect this guards is unreachable today and cheap to keep guarded.

    Activity dates are string columns, so nothing hands the progress engine a
    ``datetime`` now. The day one of those columns becomes a real date column,
    every holiday would silently stop being a holiday, and without this test
    nothing anywhere would fail.
    """
    cal = WorkCalendar(holidays=frozenset({"2026-05-01"}))
    assert cal.is_working_day(datetime(2026, 5, 1, 9, 30)) is False
    assert cal.is_working_day(date(2026, 5, 1)) is False


def test_the_pre_change_form_really_did_get_this_wrong() -> None:
    """Negative control for the two-line fix above.

    ``datetime`` subclasses ``date``, so the old order returned the datetime
    untouched and the ISO string it produced could never match a stored
    ``YYYY-MM-DD``. Without this, the fix would look like a tidy-up.
    """
    moment = datetime(2026, 5, 1, 9, 30)
    assert _pre_change_parse_date(moment) is moment
    assert _pre_change_parse_date(moment).isoformat() == "2026-05-01T09:30:00"
    assert _pre_change_parse_date(moment).isoformat() not in {"2026-05-01"}
    assert _parse_date(moment).isoformat() == "2026-05-01"
