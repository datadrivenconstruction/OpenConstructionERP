# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Nigeria and Bulgaria join the calendar engine as covered jurisdictions.

Written before _holidays_ng and _holidays_bg exist, per the fleet rule that
the standing test lands before the change it stands for. Every assertion
below is expected to fail until both functions and their _WORKING_WEEK
entries are added to app/core/calendar.py, and each failure is the right one:
neither country is in _HOLIDAY_FUNCS yet, so a statutory date such as
Nigerian Independence Day currently resolves as an ordinary Thursday rather
than a holiday.

What each test is checking, and why it is not a data dump:

- A known statutory date is a non-working day. Chosen to be a date that needs
  no substitution logic to land on a weekday on its own, so the assertion is
  about the date being present at all, not about a substitution rule working.
- An ordinary weekday with nothing on it is still a working day. Without this,
  a bug that marked every day non-working would pass the first assertion too.
- The control that matters: a jurisdiction this module deliberately does not
  cover reports itself as such through resolve_holidays provenance, rather
  than silently answering like an ordinary working week. Kenya is used here
  as a real ISO code with no entry in _HOLIDAY_FUNCS, chosen only because
  nobody in the current cohort is working on it, the same reasoning
  test_calendar_provenance.py uses "XX" for, spelled with a country that will
  not quietly start passing because an unrelated commit by someone else
  covers it.

The Bulgaria substitution test exists because Bulgaria is not just a longer
date list than Nigeria. Labour Code Art. 154(2) moves a holiday that falls on
a Saturday or Sunday onto the following working day, or, when a Saturday
holiday and a Sunday holiday are adjacent, onto the following two working
days, with the Easter block explicitly exempted. A flat set of dates gets
this wrong twice over: it misses the substitute days entirely, and if the
exemption were missed instead, Holy Saturday and Easter Sunday would
manufacture two substitute days after every single Easter, because those two
are on a weekend every year by construction. 2022 is used because 24 December
that year is a Saturday, so Christmas Eve, Christmas Day and the Second Day
of Christmas (24-26 December) run Saturday, Sunday, Monday, and the two
substitute days chain onto 27 and 28 December rather than colliding with a
holiday already there.

What is deliberately not asserted: the exact Nigerian Minister-declared Eid
and Mawlid dates, because those are policy announcements the calendar engine
approximates from the Islamic calendar the same way it does for the Gulf
countries, not statutory Gregorian dates a test can pin down in advance. Also
not asserted: the Nigerian working week as a legal certainty, because the
Labour Act does not fix one economy-wide - see the sourcing note carried in
_holidays_ng and the _WORKING_WEEK comment once they land.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core import calendar as cal
from app.core.calendar import AXIS_JURISDICTION, HolidayCalculationError, resolve_holidays
from app.core.provenance import Source

# A real ISO code with no entry in _HOLIDAY_FUNCS at the time this file was
# written. Not a synthetic placeholder like "XX": the point of this control is
# that a jurisdiction nobody has covered reports itself as uncovered, and a
# code that could never be real would not demonstrate that.
_UNCOVERED_CONTROL = "KE"


@pytest.mark.unit
def test_nigerian_independence_day_is_a_non_working_day() -> None:
    """1 October, fixed in the Public Holidays Act own Schedule.

    2026 is used because 1 October falls on a Thursday that year, so the
    assertion is about the date being recognised at all rather than about the
    Nigerian no-substitute default (Public Holidays Act s.5) doing anything.
    """
    assert cal.is_working_day(date(2026, 10, 1), "NG") is False


@pytest.mark.unit
def test_bulgarian_independence_day_is_a_non_working_day() -> None:
    """22 September, fixed in Labour Code Art. 154(1).

    2026 is used for the same reason as the Nigerian case: 22 September is a
    Tuesday that year, so no substitution is in play.
    """
    assert cal.is_working_day(date(2026, 9, 22), "BG") is False


@pytest.mark.unit
@pytest.mark.parametrize("country", ["NG", "BG"])
def test_an_ordinary_tuesday_is_a_working_day(country: str) -> None:
    """Control for the two tests above: not every day is non-working."""
    assert cal.is_working_day(date(2026, 6, 16), country) is True


@pytest.mark.unit
def test_a_deliberately_uncovered_jurisdiction_reports_itself_as_such() -> None:
    """The control that matters: absence must be visible, not silent.

    A jurisdiction with no holiday function still answers, working week, no
    holidays, which is the honest international-default reading. What this
    asserts is that the answer says it is a fallback rather than looking like
    a jurisdiction whose own rules were found and applied.
    """
    prov = resolve_holidays(_UNCOVERED_CONTROL, 2026)[AXIS_JURISDICTION]
    assert prov.source is Source.FALLBACK
    assert prov.answered is False
    assert prov.usable is True

    # And the two countries this file is actually about must not share that
    # fate once they land: a covered country is declared on its own terms,
    # not folded into the same international default the control exercises.
    for country in ("NG", "BG"):
        own = resolve_holidays(country, 2026)[AXIS_JURISDICTION]
        assert own.source is Source.DECLARED, f"{country} must answer on its own terms, not as a fallback"


@pytest.mark.unit
@pytest.mark.parametrize("year", [2020, 2026, 2070])
def test_neither_country_has_a_curated_year_window(year: int) -> None:
    """Neither is served from a curated table, so neither has interior gaps.

    Unlike China and India, neither Nigeria nor Bulgaria is read out of a
    curated lunisolar table that names particular years. This is the check for
    the mistake it was written to catch: a country whose holidays are only
    sourced for some years reading as complete because the dates it does have
    are correct.

    The upper probe year used to be 2099, on the reasoning that a year far in
    the future is as good a check as one nearby. That reasoning holds for
    Bulgaria, whose holidays are Easter-relative arithmetic with no horizon,
    and does not hold for Nigeria, whose Islamic holidays are converted by a
    library whose window ends in 2077. See the test below, which is the half
    that assumption was hiding.
    """
    for country in ("NG", "BG"):
        result = resolve_holidays(country, year)
        assert result["effective_year"].source is Source.DECLARED
        assert result["omitted"] == ()


@pytest.mark.unit
def test_bulgaria_answers_for_any_year_and_nigeria_stops_at_the_converter() -> None:
    """The two countries differ on the year axis and it is worth stating.

    Bulgaria is arithmetic and has no horizon. Nigeria inherits the horizon of
    the Hijri converter, so a year past it is unanswerable rather than a year
    with fewer holidays, which is what it used to look like: Eid al-Fitr, Eid
    al-Kabir and the Prophet's Birthday simply disappeared and the year read as
    fully covered.
    """
    assert resolve_holidays("BG", 2099)["effective_year"].source is Source.DECLARED

    with pytest.raises(HolidayCalculationError):
        resolve_holidays("NG", 2099)


@pytest.mark.unit
def test_bulgarian_christmas_cluster_chains_its_substitute_days() -> None:
    """Labour Code Art. 154(2): the pairwise case, not just the single-day one.

    24 December 2022 is a Saturday. Christmas Eve, Christmas Day and the
    Second Day of Christmas run 24 (Sat), 25 (Sun), 26 (Mon), so the first two
    working days after that run are the substitutes: 27 and 28 December, not
    26 and 27, because 26 December is already a holiday and the loop that
    finds a substitute must skip a day already claimed rather than land on it.
    """
    for working_day in (date(2022, 12, 27), date(2022, 12, 28)):
        assert cal.is_working_day(working_day, "BG") is False, f"{working_day} should be a substitute day"

    # The Tuesday after the substitutes is an ordinary working day again.
    assert cal.is_working_day(date(2022, 12, 29), "BG") is True


@pytest.mark.unit
def test_bulgarian_easter_block_is_exempt_from_substitution() -> None:
    """Art. 154(2) names the Easter holidays as the one exception.

    Holy Saturday and Easter Sunday are on a weekend every year by
    construction, since Easter Sunday is by definition a Sunday. Applying the
    substitution rule to them regardless would manufacture two extra
    non-working days after every single Easter. Easter Monday in 2026 is
    6 April; the Tuesday after it must be an ordinary working day.
    """
    assert cal.is_working_day(date(2026, 4, 7), "BG") is True


@pytest.mark.unit
@pytest.mark.parametrize("country", ["NG", "BG"])
def test_the_working_week_is_monday_to_friday(country: str) -> None:
    """Checked rather than assumed, per the working week being a separate map.

    Both read as Monday-Friday from the sources available, but for different
    reasons. The Bulgarian entry is a direct statutory maximum (Labour Code
    Art. 136: 40 hours a week, 8 hours a day). The Nigerian Labour Act s.13
    does not fix an economy-wide week at all, hours are left to agreement,
    collective bargaining or an industrial wages board, so Monday-Friday here
    records the near-universal practical convention rather than a statute
    naming those five days the way the Bulgarian one does. That distinction
    belongs in the sourcing comment on _WORKING_WEEK once the entry exists,
    not only in this test.
    """
    assert country in cal._WORKING_WEEK, f"{country} needs its own _WORKING_WEEK entry, not the default by omission"
    assert cal._WORKING_WEEK[country] == frozenset({0, 1, 2, 3, 4})


def test_bulgarian_easter_block_follows_the_orthodox_easter() -> None:
    """Bulgaria keeps the Orthodox Easter: 12 April 2026, not the Western 5 April."""
    from datetime import date

    from app.core.calendar import resolve_holidays

    dates = set(resolve_holidays("BG", 2026)["dates"])
    assert {date(2026, 4, 10), date(2026, 4, 11), date(2026, 4, 12), date(2026, 4, 13)} <= dates
    assert date(2026, 4, 3) not in dates
