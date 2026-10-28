# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every reader of a stored working week reads it the same way, or refuses it.

Four readers used to wrap the whole conversion in ``except (TypeError,
ValueError)`` and fall back to Monday through Friday. That guard is ornamental
against the malformation that actually happens: a bare digit string does not
raise, it iterates one character at a time.

That makes this worse than the holiday defect one level up rather than merely
parallel to it. Ten junk date strings produce no holidays, which is at least a
calendar somebody might question. ``"12345"`` produces a clean five day week
nobody would look at twice, and ``"0123456"`` produces a seven day week in
which no date is ever non-working, so every duration computes short and every
finish date lands early. The wrong answer is indistinguishable from the right
one, which is why the guard has to be a type check before the iteration rather
than an except around it.
"""

import logging
from datetime import date
from types import SimpleNamespace

import pytest

from app.core.cpm import readable_work_days
from app.modules.schedule.progress_math import WorkCalendar
from app.modules.schedule.service import resolve_calendar

#: 2026-05-01 is a Friday, so this is the Saturday after it. Whether it is a
#: working day is what separates a five day week from a seven day one.
SATURDAY = date(2026, 5, 2)

#: The correct stored value for a Monday to Friday week.
MON_FRI = [0, 1, 2, 3, 4]


# ── The finding: the old form did not fail, it answered plausibly ─────────


def _pre_change_work_days(stored):
    """The conversion exactly as all four readers had it."""
    try:
        return [int(d) for d in (stored or [])]
    except (TypeError, ValueError):
        return []


def test_the_old_guard_never_fired_on_the_malformation_it_looked_like_it_caught() -> None:
    """A bare digit string is iterable, so the except branch was unreachable."""
    assert _pre_change_work_days("12345") == [1, 2, 3, 4, 5]
    assert _pre_change_work_days("0123456") == [0, 1, 2, 3, 4, 5, 6]


def test_a_corrupt_column_used_to_answer_identically_to_a_correct_one() -> None:
    """The whole case for this change, in one assertion.

    Nothing downstream could tell these apart, because after the comprehension
    they are the same object. A log line cannot help either; there was no branch
    to put one in.
    """
    assert _pre_change_work_days("12345") == _pre_change_work_days([1, 2, 3, 4, 5])


def test_the_seven_day_reading_makes_every_day_a_working_day() -> None:
    """Why "0123456" is the dangerous one rather than merely wrong."""
    week = frozenset(_pre_change_work_days("0123456"))
    assert all(day in week for day in range(7))
    assert SATURDAY.weekday() in week


# ── The guard: an unreadable column is refused ────────────────────────────


UNREADABLE_COLUMNS = [
    pytest.param("12345", id="digit-string-plausible"),
    pytest.param("0123456", id="digit-string-seven-day"),
    pytest.param("monday", id="prose"),
    pytest.param(5, id="number"),
    pytest.param({"0": True}, id="mapping"),
]


@pytest.mark.parametrize("column", UNREADABLE_COLUMNS)
def test_a_column_that_is_not_a_list_is_refused(column) -> None:
    with pytest.raises(ValueError):
        readable_work_days(column, source="calendar 7 work days")


def test_the_refusal_names_the_calendar_and_what_it_found() -> None:
    with pytest.raises(ValueError) as err:
        readable_work_days("12345", source="calendar 7 work days")
    message = str(err.value)
    assert "calendar 7 work days" in message, "the operator cannot fix a row the error does not name"
    assert "str" in message, "and needs to know what was stored instead of a list"


# ── Leniency that must survive, kept on its own branch ────────────────────


def test_an_empty_week_is_not_a_refusal() -> None:
    """``default=list`` means an ORM row with no explicit work days genuinely
    arrives as ``[]``. That is a real population, and callers default it."""
    assert readable_work_days([], source="calendar 7 work days") == []


def test_an_absent_column_is_an_empty_week_rather_than_an_unreadable_one() -> None:
    assert readable_work_days(None, source="calendar 7 work days") == []


def test_an_empty_week_and_a_refused_column_do_not_share_a_branch() -> None:
    """Stated as a property rather than left to the reader of the diff.

    Folding them back together would rebuild the collapse this removes, one
    level up: an unreadable column would once again become the default week.
    """
    assert readable_work_days([], source="s") == []
    with pytest.raises(ValueError):
        readable_work_days("", source="s")


# ── Entries drop individually, which the blanket except also cost ─────────


def test_one_unreadable_entry_no_longer_discards_the_readable_ones() -> None:
    """The old except caught this and threw the whole week away."""
    assert _pre_change_work_days([0, "monday", 4]) == []
    assert readable_work_days([0, "monday", 4], source="calendar 7 work days") == [0, 4]


def test_dropping_an_entry_is_logged(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="app.core.cpm"):
        readable_work_days([0, "monday", 4], source="calendar 7 work days")
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "'monday'" in message
    assert "calendar 7 work days" in message


def test_a_readable_week_logs_nothing(caplog) -> None:
    """Negative control. A reader that warned on everything would otherwise
    pass the assertion above."""
    with caplog.at_level(logging.WARNING, logger="app.core.cpm"):
        assert readable_work_days(MON_FRI, source="calendar 7 work days") == MON_FRI
    assert caplog.records == []


def test_a_weekday_number_out_of_range_is_kept() -> None:
    """Documented decision. A number nothing matches never marks a day working,
    so dropping it would change dates where keeping it cannot. The write side
    owns the range check."""
    assert readable_work_days([0, 9], source="calendar 7 work days") == [0, 9]


# ── The readers agree ─────────────────────────────────────────────────────


def _helper_reader(stored) -> bool:
    """Is Saturday worked, according to the shared reader?"""
    week = frozenset(readable_work_days(stored, source="test calendar")) or frozenset(MON_FRI)
    return SATURDAY.weekday() in week


def _progress_reader(stored) -> bool:
    """Is Saturday worked, according to the progress engine?"""
    week = frozenset(readable_work_days(stored, source="test calendar")) or frozenset(MON_FRI)
    return WorkCalendar(work_weekdays=week, holidays=frozenset()).is_working_day(SATURDAY.isoformat())


def _metadata_reader(stored) -> bool:
    """Is Saturday worked, according to the schedule metadata resolver?"""
    schedule = SimpleNamespace(metadata_={"calendar": {"work_days": stored}})
    return SATURDAY.weekday() in resolve_calendar(schedule)["work_days"]


READERS = [
    pytest.param(_helper_reader, id="shared-reader"),
    pytest.param(_progress_reader, id="progress-engine"),
    pytest.param(_metadata_reader, id="schedule-metadata"),
]


@pytest.mark.parametrize("reader", READERS)
def test_a_five_day_week_does_not_work_saturday(reader) -> None:
    """Control. Every assertion below would pass against a reader that never
    works a Saturday."""
    assert reader(MON_FRI) is False


@pytest.mark.parametrize("reader", READERS)
def test_a_six_day_week_works_saturday(reader) -> None:
    assert reader([0, 1, 2, 3, 4, 5]) is True


@pytest.mark.parametrize("reader", READERS)
def test_no_reader_invents_a_week_from_a_digit_string(reader) -> None:
    """The defect, asserted at every door rather than only at the shared one."""
    with pytest.raises(ValueError):
        reader("0123456")


@pytest.mark.parametrize("stored", [MON_FRI, [0, 1, 2, 3, 4, 5], [], [0, 9]])
def test_the_readers_agree_with_each_other(stored) -> None:
    """Agreement, not three separate right answers, so a fourth reader that is
    wrong in the same way as the others still fails."""
    verdicts = {reader.values[0](stored) for reader in READERS}
    assert len(verdicts) == 1, f"{stored!r} is read differently by different readers"


# ── The last exception reader joins the convention ────────────────────────


def test_the_metadata_resolver_now_reads_exceptions_the_shared_way() -> None:
    """This was the one reader still passing exception values through whole.

    It sat one line below the work_days conversion, so the collapse to one
    convention was not actually complete until it moved too.
    """
    schedule = SimpleNamespace(
        metadata_={"calendar": {"work_days": MON_FRI, "exceptions": [" 2026-05-01 ", "20260502"]}}
    )
    assert resolve_calendar(schedule)["exceptions"] == ["2026-05-01", "2026-05-02"]


def test_the_metadata_resolver_refuses_an_exceptions_column_that_is_not_a_list() -> None:
    schedule = SimpleNamespace(metadata_={"calendar": {"work_days": MON_FRI, "exceptions": "2026-05-01"}})
    with pytest.raises(ValueError):
        resolve_calendar(schedule)


def test_a_schedule_without_calendar_metadata_still_resolves() -> None:
    """Control for the two above. The resolver's whole job is to have an answer
    when there is no calendar at all."""
    assert resolve_calendar(SimpleNamespace(metadata_=None)) == {"work_days": MON_FRI, "exceptions": []}
