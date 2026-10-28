# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A stored calendar holiday is canonical, and means the same as a CPM exception.

``work_days`` on these models has been constrained since the Monday-zero
convention was settled. ``holidays`` beside it was not, so the calendar write
schemas refused a week running to eight days while accepting a holiday written
``01/05/2026``. That entry reached three different readers and matched in none
of them, and the day was worked as ordinary without anything being logged.

The last group of tests is the one that matters most over time. A calendar
holiday and a CPM calendar exception are the same thing wearing two field
names, and they used to disagree about which spellings they accepted. They now
share one parser, and the agreement is asserted rather than assumed, so a
second parser written later shows up as a failure here instead of as two
schedules that differ by one day.
"""

from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from app.core.cpm import canonical_exception_dates
from app.modules.schedule.schemas import CPMCalculateRequest
from app.modules.schedule_advanced.cpm import normalise_holidays, offset_calendar_from_work_days
from app.modules.schedule_advanced.schemas import CalendarCreate, CalendarUpdate

#: Spellings that name one unambiguous day, all of them 2026-05-01.
ACCEPTED = [
    pytest.param("2026-05-01", id="iso"),
    pytest.param("20260501", id="compact"),
    pytest.param("2026-05-01T00:00:00", id="iso-datetime-T"),
    pytest.param("2026-05-01 00:00:00", id="iso-datetime-space"),
    pytest.param("2026-05-01T09:30:00", id="iso-datetime-with-time"),
]

#: Spellings that name no single day, or name one only by guessing which locale
#: convention the writer had in mind.
REFUSED = [
    pytest.param("01/05/2026", id="slashed-ambiguous"),
    pytest.param("2026-5-1", id="unpadded"),
    pytest.param("2026-13-01", id="impossible-month"),
    pytest.param("2026-02-30", id="impossible-day"),
    pytest.param("next friday", id="prose"),
    pytest.param("", id="empty"),
]


def _created(holidays: list[str]) -> list[str]:
    return CalendarCreate(project_id=uuid4(), name="Calendar under test", holidays=holidays).holidays


def _updated(holidays: list[str]) -> list[str] | None:
    return CalendarUpdate(holidays=holidays).holidays


WRITE_DOORS = [pytest.param(_created, id="calendar-create"), pytest.param(_updated, id="calendar-update")]


class _PreChangeCalendarCreate(BaseModel):
    """The calendar write schema's ``holidays`` field as it stood before.

    A plain ``list[str]``, which is what made every refusal below reachable.
    """

    holidays: list[str] = []


# ── Control ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("door", WRITE_DOORS)
def test_a_canonical_holiday_survives_the_write(door) -> None:
    """Control. Without it, every refusal below could pass by refusing all input."""
    assert door(["2026-05-01"]) == ["2026-05-01"]


@pytest.mark.parametrize("door", WRITE_DOORS)
def test_an_empty_calendar_is_not_a_refusal(door) -> None:
    assert door([]) == []


def test_an_omitted_holiday_list_stays_absent() -> None:
    """A patch that does not mention holidays must not invent an empty one."""
    assert CalendarUpdate(name="Renamed").holidays is None
    assert CalendarUpdate(holidays=None).holidays is None


# ── Accepted, and stored in one spelling ──────────────────────────────────


@pytest.mark.parametrize("door", WRITE_DOORS)
@pytest.mark.parametrize("spelling", ACCEPTED)
def test_an_unambiguous_day_is_accepted_and_stored_canonically(door, spelling) -> None:
    assert door([spelling]) == ["2026-05-01"]


@pytest.mark.parametrize("door", WRITE_DOORS)
def test_untidy_input_is_repaired_rather_than_refused(door) -> None:
    """A date pasted from a spreadsheet arrives padded. That is not an error.

    ``str_strip_whitespace`` on these models trims the element before the
    validator sees it, unlike the CPM request body where the same value arrives
    untouched. Both end at the same stored string, which is the point.
    """
    assert door([" 2026-05-01 "]) == ["2026-05-01"]


@pytest.mark.parametrize("door", WRITE_DOORS)
def test_every_accepted_spelling_collapses_to_one_string(door) -> None:
    stored = door([p.values[0] for p in ACCEPTED])
    assert set(stored) == {"2026-05-01"}


@pytest.mark.parametrize("door", WRITE_DOORS)
def test_normalising_does_not_deduplicate(door) -> None:
    """Documented behaviour, asserted so it is a decision rather than an accident.

    Callers that want a set build one; the readers downstream already do.
    """
    assert door(["2026-05-01", "20260501"]) == ["2026-05-01", "2026-05-01"]


# ── Refused ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("door", WRITE_DOORS)
@pytest.mark.parametrize("spelling", REFUSED)
def test_a_value_naming_no_single_day_is_refused(door, spelling) -> None:
    with pytest.raises(ValidationError) as err:
        door([spelling])
    assert "holidays" in str(err.value)


@pytest.mark.parametrize("door", WRITE_DOORS)
def test_the_refusal_names_the_entry_and_the_field(door) -> None:
    with pytest.raises(ValidationError) as err:
        door(["2026-05-01", "01/05/2026"])
    message = str(err.value)
    assert "01/05/2026" in message, "the writer cannot fix what the error does not name"
    assert "ISO 8601" in message
    assert "2026-12-25" in message, "the message shows the shape it wants"


# ── Negative control ──────────────────────────────────────────────────────


@pytest.mark.parametrize("spelling", REFUSED)
def test_the_write_door_used_to_accept_every_refused_spelling(spelling) -> None:
    """Every value now refused was stored verbatim before the guard existed."""
    assert _PreChangeCalendarCreate(holidays=[spelling]).holidays == [spelling]


def test_the_pre_change_fixture_is_not_secretly_guarded() -> None:
    assert not _PreChangeCalendarCreate.__pydantic_decorators__.field_validators
    assert not _PreChangeCalendarCreate.__pydantic_decorators__.model_validators


# ── One parser: the calendar door and the CPM door must agree ─────────────


def _cpm_accepts(spelling: str) -> bool:
    try:
        CPMCalculateRequest(calendar={"work_days": [0, 1, 2, 3, 4], "exceptions": [spelling]})
    except ValidationError:
        return False
    return True


def _calendar_accepts(spelling: str) -> bool:
    try:
        normalise_holidays([spelling])
    except ValueError:
        return False
    return True


#: Every spelling either door has an opinion about, accepted and refused mixed
#: deliberately so the agreement below cannot hold vacuously.
CORPUS = [p.values[0] for p in ACCEPTED] + [p.values[0] for p in REFUSED] + [" 2026-05-01 ", "2026-05-01Z"]


def test_the_corpus_is_not_one_sided() -> None:
    """Guards the agreement test. Two parsers that both accept everything, or
    both refuse everything, would agree for a reason that proves nothing."""
    verdicts = {_calendar_accepts(s) for s in CORPUS}
    assert verdicts == {True, False}, "the corpus must contain both accepted and refused spellings"


@pytest.mark.parametrize("spelling", CORPUS)
def test_a_holiday_and_a_cpm_exception_accept_the_same_spellings(spelling) -> None:
    """A coupling test, not a discovery.

    Both sides delegate to one parser, so this holds by construction today. It
    is asserted so that it stops holding loudly if someone writes a second one.
    """
    assert _calendar_accepts(spelling) == _cpm_accepts(spelling), (
        f"{spelling!r} is accepted by one calendar door and refused by the other"
    )


@pytest.mark.parametrize("spelling", ACCEPTED)
def test_both_doors_store_the_same_canonical_string(spelling) -> None:
    """Agreeing to accept is not enough; they must also agree what was meant."""
    via_calendar = normalise_holidays([spelling])
    via_cpm = canonical_exception_dates([spelling], source="calendar.exceptions")
    assert via_calendar == via_cpm == ["2026-05-01"]


def test_the_engine_factory_still_refuses_a_locale_ordered_date() -> None:
    """The one spelling that must stay refused however wide the accept gets.

    Reading 01/05/2026 correctly means guessing whether the writer meant the
    first of May or the fifth of January, and the engine does not guess.
    """
    with pytest.raises(ValueError, match="ISO 8601"):
        offset_calendar_from_work_days([0, 1, 2, 3, 4], ["25/12/2026"])


def test_the_engine_factory_accepts_what_the_write_door_now_stores() -> None:
    """The write door canonicalises, so the factory only ever sees YYYY-MM-DD.

    It is asserted on the wider set anyway: the factory reads calendars stored
    before the guard existed, and narrowing it would turn old rows into errors.
    """
    stored: Any = normalise_holidays(["2026-12-25T00:00:00", "20261225"])
    cal = offset_calendar_from_work_days([0, 1, 2, 3, 4], stored)
    assert cal.holidays == frozenset({"2026-12-25"})
