# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Working-days calendar engine - Wave 28 of the worldwide-parameterisation audit.

Provides:
    is_working_day(date, country_code) -> bool
    next_working_day(date, country_code) -> date
    resolve_holidays(country_code, year) -> dict  (dates plus their provenance)

Per-country rules are defined inline (public holidays and working weeks) and
drawn from the regional-pack ``holidays`` config keys.

Easter computation uses ``dateutil.easter`` (already a project dependency).
Hijri (Islamic) holidays use the maintained ``hijridate`` library to convert
Eid al-Fitr (1 Shawwal) and Eid al-Adha (10 Dhu al-Hijjah) to Gregorian for
any requested year.  Japanese equinoxes use the standard integer
approximation valid for 1980-2099.  Hindu holidays (Diwali, Holi) have no
reliable lightweight panchang library, so they are served from a curated
multi-year lookup table; years outside the table skip those holidays rather
than crash.  Carnaval (Brazil) is derived from Easter.

Sources:
- DE: Bundesgesetzblatt, 2026 federal holidays for all states' common days
- UK: HM Government bank holidays list (published annually)
- US: 5 U.S.C. § 6103 (federal public holidays)
- CA: Canada Labour Code s.166 (federal general holidays). Provincial days such as
  Family Day and the August civic holiday are deliberately excluded.
- AE: Federal Decree-Law No. 33/2021, Art. 28 (UAE)
- SA: Saudi Ministry of Human Resources and Social Development
- QA: Qatar Labour Law No. 14/2004, Art. 74
- KW: Kuwait Civil Service Commission annual holiday circular
- BH: Bahrain Labour Law No. 36/2012, Art. 62
- OM: Oman Labour Law (Royal Decree 53/2023), Art. 68
- CN: State Council national holiday measures. Statutory days only; the annual
  working-day arrangement that bridges them is not modelled (see _holidays_cn).
- IN: Gazette of India, 2026 gazetted holidays
- JP: Cabinet Office Japan, 2026 national holidays
- BR: Federal Law 9.093/95 and 10.607/02 (national holidays)
- RU: Labour Code of the Russian Federation, Art. 112
- NG: Public Holidays Act, Cap. P40, LFN 2004, and the Islamic dates it leaves
  to Ministerial declaration. Two dates (Boxing Day, Democracy Day) rest on
  corroboration rather than a primary text read in full; see _holidays_ng.
- BG: Labour Code (Kodeks na truda), Art. 154. Art. 154(2) moves a holiday
  landing on a Saturday or Sunday, with the Easter block exempted.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from dateutil.easter import easter  # type: ignore[import]
from hijridate import Gregorian, Hijri  # type: ignore[import]

from app.core.provenance import Provenance, declared, fell_back, unavailable, weakest

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _fixed_holiday(month: int, day: int, year: int) -> date:
    """Return the date for a fixed-date holiday in ``year``."""
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the n-th occurrence (1-based) of ``weekday`` in ``month``/``year``.

    ``weekday`` follows Python's ``date.weekday()`` convention:
    0=Monday, 6=Sunday.  ``n`` may be negative for last-occurrence (e.g. -1).
    """
    first = date(year, month, 1)
    # How many days until the first occurrence of weekday?
    offset = (weekday - first.weekday()) % 7
    first_occurrence = first + timedelta(days=offset)
    if n > 0:
        return first_occurrence + timedelta(weeks=n - 1)
    # Last occurrence: go to next month - 1 day, find last weekday
    if month == 12:
        last_of_month = date(year, 12, 31)
    else:
        last_of_month = date(year, month + 1, 1) - timedelta(days=1)
    # Walk back to the weekday
    diff = (last_of_month.weekday() - weekday) % 7
    last_occurrence = last_of_month - timedelta(days=diff)
    return last_occurrence + timedelta(weeks=n + 1)


class HijriRangeError(RuntimeError):
    """The Hijri converter cannot reach the requested Gregorian year at all.

    Raised rather than returned as an empty list, because returning one made
    every Islamic holiday vanish and the year read as a shorter calendar rather
    than an unanswerable one.

    The original argument for raising was weaker than that and was wrong. It
    held that an empty list is also a legitimate answer, for a year in which an
    Islamic date genuinely does not fall, and that a failure returning one would
    be indistinguishable from it. That second case does not exist. The Hijri
    year is about 354 days against 365, so consecutive occurrences of a fixed
    Hijri date are always closer together than a Gregorian year is long and
    cannot straddle one. Measured across the converter's whole window, 1925 to
    2076, the four dates this module converts land once or twice in every year
    and never zero. The eleven-day gap is the reason an empty result cannot
    happen, not the reason it can, which makes raising simply correct rather
    than a choice between two readings.
    """

    def __init__(self, year: int) -> None:
        super().__init__(f"the Hijri converter does not cover {year}")
        self.year = year


#: The whole requested year converts, so every occurrence in it is visible and
#: an empty result cannot happen. See :class:`HijriRangeError` for why not.
HIJRI_COVERED = "covered"
#: Only part of the year converts, so an Islamic date falling in the rest of it
#: cannot be seen. The converter's window ends mid-November 2077 and begins in
#: August 1924, so exactly those two years straddle it.
#:
#: This is the state worth understanding, not the one past the window. A year
#: fully outside it lost every Islamic holiday and was obvious: the UAE
#: returned four against a healthy thirteen. A straddling year returned twelve,
#: which sits inside the ten to seventeen band ordinary lunar drift produces,
#: so the year that was already wrong is the one that looked healthy. The cliff
#: was findable by counting and the edge never was, because the edge is where
#: the defect and the healthy signal overlap. Any instrument tuned to catch the
#: obvious part of a defect reports that overlap as fine.
HIJRI_EDGE = "edge"
#: No part of the year converts. Nothing Islamic can be computed.
HIJRI_OUT_OF_RANGE = "out_of_range"


def _hijri_year_coverage(year: int) -> str:
    """How much of a Gregorian year the Hijri converter can actually reach.

    Asked of the year's two boundaries rather than of a hardcoded window, so the
    answer tracks whatever range the installed converter actually supports
    instead of a copy of it that would rot the next time it is upgraded.
    """
    reachable = 0
    for boundary in (date(year, 1, 1), date(year, 12, 31)):
        try:
            Gregorian(boundary.year, boundary.month, boundary.day).to_hijri()
        except (OverflowError, ValueError):
            continue
        reachable += 1
    if reachable == 2:
        return HIJRI_COVERED
    return HIJRI_EDGE if reachable == 1 else HIJRI_OUT_OF_RANGE


def _hijri_dates_in_gregorian_year(month: int, day: int, year: int) -> list[date]:
    """Return every Gregorian date matching a fixed Hijri month/day in ``year``.

    Converts the given Islamic-calendar day (e.g. 1 Shawwal for Eid al-Fitr,
    10 Dhu al-Hijjah for Eid al-Adha) to Gregorian for each Hijri year that
    can overlap the requested Gregorian year.

    Because the Islamic (lunar) year is about 11 days shorter than the
    Gregorian year, a single Islamic date lands in the requested Gregorian year
    once or twice (the latter near the start/end of a year, e.g. Eid al-Fitr
    falls in both January and December of 2033). All matches are returned so
    callers can mark each one.

    Never zero, and that is load-bearing rather than trivia. Consecutive
    occurrences are about 354 days apart and a Gregorian year is 365, so they
    cannot straddle one. This docstring used to claim zero was possible, which
    is what made an empty return look like it might be an answer; measured over
    the converter's whole window it never happens. So inside the window an
    empty result has no innocent meaning, and outside it the function raises.

    Args:
        month: Hijri month (1-12), e.g. ``10`` for Shawwal.
        day:   Hijri day of month (1-30), e.g. ``1`` for the 1st.
        year:  Gregorian year to search.

    Returns:
        list[date] - Gregorian dates landing in ``year``, one or two of them.
        This return used to be documented as empty when the year was outside the
        converter's range *or* no match existed, which is one value standing for
        a defect and an answer at the same time. The second case does not exist,
        so the first one raises and this list is never empty.

    Raises:
        HijriRangeError: the converter cannot reach ``year`` at all.
    """
    if _hijri_year_coverage(year) == HIJRI_OUT_OF_RANGE:
        raise HijriRangeError(year)

    candidate_hijri_years: set[int] = set()
    for boundary in (date(year, 1, 1), date(year, 12, 31)):
        try:
            hijri_year = Gregorian(boundary.year, boundary.month, boundary.day).to_hijri().year
        except (OverflowError, ValueError):
            # One boundary of an edge year. The other one answered, or the
            # guard above would have raised, so this is a partial view of a
            # reachable year rather than a failure. resolve_holidays reports it
            # as a fallback on the year axis.
            continue
        candidate_hijri_years.update({hijri_year - 1, hijri_year, hijri_year + 1})

    matches: list[date] = []
    for hijri_year in sorted(candidate_hijri_years):
        try:
            g = Hijri(hijri_year, month, day).to_gregorian()
        except (OverflowError, ValueError):
            # Speculative candidate: the years either side of the requested one
            # are probed on purpose and the outermost of them can fall off the
            # end of the window. The year-level verdict came from the
            # boundaries above, so this cannot hide an unreachable year.
            continue
        converted = date(g.year, g.month, g.day)
        if converted.year == year:
            matches.append(converted)
    return matches


def _equinox_day(year: int, *, spring: bool) -> int:
    """Return the day-of-month of the Japanese spring or autumn equinox.

    Uses the well-known integer approximation that is accurate for the years
    1980-2099 (the range Japan's holiday law is published against):

        spring = floor(20.8431 + 0.242194 * (year - 1980) - floor((year - 1980) / 4))
        autumn = floor(23.2488 + 0.242194 * (year - 1980) - floor((year - 1980) / 4))

    The equinox months are fixed: March for spring, September for autumn.

    Args:
        year:   Gregorian year (intended range 1980-2099).
        spring: True for the vernal (March) equinox, False for the autumnal
                (September) equinox.

    Returns:
        int - The day of the month on which the equinox falls.
    """
    base = 20.8431 if spring else 23.2488
    offset = year - 1980
    return int(base + 0.242194 * offset - offset // 4)


# Curated Hindu festival dates (Gregorian). There is no reliable lightweight
# panchang library, so these are taken from widely published almanac dates for
# India. Holi is the day of Holika Dahan's following morning (Phalguna
# Purnima); Diwali is the main Lakshmi Puja day (Kartik Amavasya). Years
# outside this table skip the holiday rather than guessing. Extend the table as
# authoritative dates are published.
_HINDU_HOLIDAYS: dict[int, dict[str, tuple[int, int]]] = {
    2024: {"holi": (3, 25), "diwali": (11, 1)},
    2025: {"holi": (3, 14), "diwali": (10, 21)},
    2026: {"holi": (3, 4), "diwali": (11, 8)},
    2027: {"holi": (3, 22), "diwali": (10, 29)},
    2028: {"holi": (3, 11), "diwali": (10, 17)},
    2029: {"holi": (3, 1), "diwali": (11, 5)},
    2030: {"holi": (3, 20), "diwali": (10, 26)},
    2031: {"holi": (3, 9), "diwali": (11, 14)},
    2032: {"holi": (3, 27), "diwali": (11, 2)},
    2033: {"holi": (3, 16), "diwali": (10, 22)},
    2034: {"holi": (3, 5), "diwali": (11, 10)},
    2035: {"holi": (3, 24), "diwali": (10, 30)},
}

# Chinese festival dates, curated for the same reason ``_HINDU_HOLIDAYS`` is.
# Spring Festival, Dragon Boat and Mid-Autumn are lunisolar, Qingming follows a
# solar term, and none of the four can be computed from the standard library or
# from the two date libraries this project already depends on.
#
# Each row holds the FIRST day of Spring Festival (lunar 1/1), Qingming, Dragon
# Boat (lunar 5/5) and Mid-Autumn (lunar 8/15). New Year's Eve is derived as the
# day before Spring Festival rather than stored, so the pair cannot drift apart.
#
# The window ends deliberately and ``_holidays_cn`` says so out loud rather than
# returning a quietly shorter set for a year it does not cover. Extending it
# means sourcing the dates, not extrapolating them: the festivals do not sit at a
# fixed Gregorian offset year to year, and a leap month moves Mid-Autumn by about
# thirty days without moving Dragon Boat at all. ``test_calendar.py`` asserts the
# offsets every row must satisfy, which will catch a guessed row but cannot catch
# a whole table shifted the same way.
_CN_FESTIVALS: dict[int, dict[str, tuple[int, int]]] = {
    2024: {"spring_festival": (2, 10), "qingming": (4, 4), "dragon_boat": (6, 10), "mid_autumn": (9, 17)},
    2025: {"spring_festival": (1, 29), "qingming": (4, 4), "dragon_boat": (5, 31), "mid_autumn": (10, 6)},
    2026: {"spring_festival": (2, 17), "qingming": (4, 5), "dragon_boat": (6, 19), "mid_autumn": (9, 25)},
    2027: {"spring_festival": (2, 6), "qingming": (4, 5), "dragon_boat": (6, 9), "mid_autumn": (9, 15)},
    2028: {"spring_festival": (1, 26), "qingming": (4, 4), "dragon_boat": (5, 28), "mid_autumn": (10, 3)},
    2029: {"spring_festival": (2, 13), "qingming": (4, 4), "dragon_boat": (6, 16), "mid_autumn": (9, 22)},
    2030: {"spring_festival": (2, 3), "qingming": (4, 5), "dragon_boat": (6, 5), "mid_autumn": (9, 12)},
}

_CN_FIRST_YEAR = min(_CN_FESTIVALS)
_CN_LAST_YEAR = max(_CN_FESTIVALS)

# The State Council raised the statutory total from 11 days to 13 with effect
# from 1 January 2025: Spring Festival went from three days to four by making New
# Year's Eve statutory, and Labour Day from one day to two.
_CN_HOLIDAY_REFORM_YEAR = 2025


# ── Per-country holiday calculators ──────────────────────────────────────────


_SATURDAY_INDEX = 5


def _holidays_de(year: int) -> set[date]:
    """German federal holidays (common to all 16 Bundesländer).

    Source: German Civil Code + Federal holiday statutes.
    State-specific holidays (e.g. Tag der Deutschen Einheit for some only
    vs all) are excluded; only *nationwide* fixed holidays are included.
    """
    e = easter(year)
    return {
        date(year, 1, 1),  # Neujahrstag
        e - timedelta(days=2),  # Karfreitag (Good Friday)
        e + timedelta(days=1),  # Ostermontag (Easter Monday)
        date(year, 5, 1),  # Tag der Arbeit
        e + timedelta(days=39),  # Christi Himmelfahrt (Ascension)
        e + timedelta(days=50),  # Pfingstmontag (Whit Monday)
        date(year, 10, 3),  # Tag der Deutschen Einheit
        date(year, 12, 25),  # 1. Weihnachtstag
        date(year, 12, 26),  # 2. Weihnachtstag
    }


def _holidays_uk(year: int) -> set[date]:
    """England & Wales public (bank) holidays.

    Source: GOV.UK bank holidays list (2026).
    Scotland and Northern Ireland have minor differences; common set used.
    """
    e = easter(year)
    # Early May bank holiday: first Monday in May
    early_may = _nth_weekday(year, 5, 0, 1)
    # Spring bank holiday: last Monday in May
    spring_bank = _nth_weekday(year, 5, 0, -1)
    # Summer bank holiday: last Monday in August
    summer_bank = _nth_weekday(year, 8, 0, -1)

    return {
        date(year, 1, 1),  # New Year's Day
        e - timedelta(days=2),  # Good Friday
        e + timedelta(days=1),  # Easter Monday
        early_may,  # Early May bank holiday
        spring_bank,  # Spring bank holiday
        summer_bank,  # Summer bank holiday
        date(year, 12, 25),  # Christmas Day
        date(year, 12, 26),  # Boxing Day
    }


def _holidays_us(year: int) -> set[date]:
    """US federal public holidays (5 U.S.C. § 6103).

    When a fixed holiday falls on Saturday, observed on Friday.
    When on Sunday, observed on Monday.
    """

    def _observed(d: date) -> date:
        if d.weekday() == 5:  # Saturday → Friday
            return d - timedelta(days=1)
        if d.weekday() == 6:  # Sunday → Monday
            return d + timedelta(days=1)
        return d

    fixed = [
        date(year, 1, 1),  # New Year's Day
        date(year, 6, 19),  # Juneteenth
        date(year, 7, 4),  # Independence Day
        date(year, 11, 11),  # Veterans Day
        date(year, 12, 25),  # Christmas Day
    ]
    computed = [
        _nth_weekday(year, 1, 0, 3),  # MLK Day - 3rd Monday January
        _nth_weekday(year, 2, 0, 3),  # Presidents' Day - 3rd Monday February
        _nth_weekday(year, 5, 0, -1),  # Memorial Day - last Monday May
        _nth_weekday(year, 9, 0, 1),  # Labor Day - 1st Monday September
        _nth_weekday(year, 10, 0, 2),  # Columbus Day - 2nd Monday October
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving - 4th Thursday November
    ]
    return {_observed(d) for d in fixed} | set(computed)


def _holidays_ca(year: int) -> set[date]:
    """Canadian federal statutory holidays (Canada Labour Code, Part III).

    Federally regulated workplaces. Family Day and the August civic holiday are
    **provincial**, are observed on different days in different provinces, and
    are deliberately out of scope for a function named for the country: an
    accurate national list with a stated limit beats a fuller list that is wrong
    in seven provinces. A caller needing provincial days has to supply them.

    Weekend substitution moves **forward** to the next free weekday, which is
    where this differs from :func:`_holidays_us` and the difference is
    deliberate. The US rule observes a Saturday holiday on the preceding Friday;
    Canada moves to the following working day in both directions, so Canada Day
    on a Saturday is observed on the Monday rather than the Friday before it.
    Applying the US rule here would put a checkable Canadian date three days
    early, which is the precise failure this function exists to remove.

    Christmas and Boxing Day are adjacent, so a substitution can land on a day
    already taken. The later one then moves on to the next free weekday instead
    of collapsing into its neighbour, which would silently cost the year a
    holiday and overcount working days.
    """
    e = easter(year)
    may_24 = date(year, 5, 24)

    # Never fall on a weekend by construction, so no substitution applies.
    days = {
        e - timedelta(days=2),  # Good Friday
        may_24 - timedelta(days=may_24.weekday()),  # Victoria Day - Monday before 25 May
        _nth_weekday(year, 9, 0, 1),  # Labour Day - 1st Monday September
        _nth_weekday(year, 10, 0, 2),  # Thanksgiving - 2nd Monday October
    }

    # Fixed dates, in calendar order so that an earlier holiday claims its
    # observed day before a later one has to work around it.
    for fixed in (
        date(year, 1, 1),  # New Year's Day
        date(year, 7, 1),  # Canada Day
        date(year, 9, 30),  # National Day for Truth and Reconciliation
        date(year, 11, 11),  # Remembrance Day
        date(year, 12, 25),  # Christmas Day
        date(year, 12, 26),  # Boxing Day
    ):
        observed = fixed
        while observed.weekday() >= _SATURDAY_INDEX or observed in days:
            observed += timedelta(days=1)
        days.add(observed)

    return days


# Islamic observances that are a single day, given as (Hijri month, day). Only the
# two Eids carry a multi-day span, and that span is policy rather than calendar.
_HIJRI_NEW_YEAR = (1, 1)  # 1 Muharram
_PROPHETS_BIRTHDAY = (3, 12)  # 12 Rabi al-Awwal


def _gcc_eids(year: int) -> set[date]:
    """The two Eids, converted from the Islamic calendar, shared by every Gulf country.

    What is shared here is a calendar fact, not a national one. 1 Shawwal and 10
    Dhu al-Hijjah fall on the same Gregorian day everywhere, the conversion via
    ``hijridate`` has no policy content, and there is nothing per-country to split.
    National days are the opposite, and each country states its own.

    Known limitation, and it is the seam in this split: the *length* of each Eid
    is policy. It is announced annually by each government, and the 3 and 4 day
    spans below are one placeholder applied to all six countries. The spans are
    closest to correct for the UAE, whose set they were originally written for,
    and too short for Saudi Arabia, where both Eids routinely run longer.
    Per-country spans are deliberately not invented here: an approximation that
    says so is worth more than a fabricated number that does not.

    Either Eid can occur once or twice within one Gregorian year, so every
    converted occurrence is expanded rather than the first one only. Twice
    happens because the Islamic year is ~11 days shorter; that same gap is why
    it can never be zero, which is what lets the converter raise on a year it
    cannot reach instead of returning an empty set nobody could tell apart from
    an answer.
    """
    days: set[date] = set()
    for start in _hijri_dates_in_gregorian_year(10, 1, year):  # Eid al-Fitr, 1 Shawwal
        days.update(start + timedelta(days=offset) for offset in range(3))
    for start in _hijri_dates_in_gregorian_year(12, 10, year):  # Eid al-Adha, 10 Dhu al-Hijjah
        days.update(start + timedelta(days=offset) for offset in range(4))
    return days


def _holidays_ae(year: int) -> set[date]:
    """United Arab Emirates federal public holidays.

    The working week is Monday-Friday and is not defined here: see ``_WORKING_WEEK``.

    Commemoration Day on 1 December and National Day on 2 and 3 December run
    together but are separate holidays. Commemoration Day moved to 1 December in
    2019, from 30 November.
    """
    days = _gcc_eids(year)
    days.update(_hijri_dates_in_gregorian_year(*_HIJRI_NEW_YEAR, year))
    days.update(_hijri_dates_in_gregorian_year(*_PROPHETS_BIRTHDAY, year))
    days.update(
        {
            date(year, 1, 1),  # New Year's Day (Gregorian)
            date(year, 12, 1),  # Commemoration Day
            date(year, 12, 2),  # National Day
            date(year, 12, 3),  # National Day (2nd day)
        }
    )
    return days


def _holidays_sa(year: int) -> set[date]:
    """Saudi Arabia national public holidays.

    The working week is Sunday-Thursday: see ``_WORKING_WEEK``.

    Saudi Arabia does **not** observe Gregorian New Year, and the shared set this
    function replaces gave it one, along with the UAE's National Day. Both are
    gone. This is the only country in the split whose set gets shorter, so it is
    the only one where an existing caller can see a date disappear.

    The Saudi public calendar is unusually short by design: the two Eids and the
    two national days are the whole of it. Neither the Islamic New Year nor the
    Prophet's Birthday is a public holiday, which is why they are absent here
    while its neighbours have them.

    Founding Day, 22 February, was established in 2022 and is a different holiday
    from National Day, 23 September, which marks the 1932 unification.
    """
    days = _gcc_eids(year)
    days.update(
        {
            date(year, 2, 22),  # Founding Day
            date(year, 9, 23),  # National Day
        }
    )
    return days


def _holidays_qa(year: int) -> set[date]:
    """Qatar national public holidays.

    The working week is Sunday-Thursday: see ``_WORKING_WEEK``.

    Qatar does not observe Gregorian New Year as a public holiday, and the shared
    set this function replaces gave it one along with the UAE's National Day.
    National Sports Day is the second Tuesday of February, so it is computed
    rather than fixed.
    """
    days = _gcc_eids(year)
    days.update(
        {
            _nth_weekday(year, 2, 1, 2),  # National Sports Day - 2nd Tuesday February
            date(year, 12, 18),  # National Day
        }
    )
    return days


def _holidays_kw(year: int) -> set[date]:
    """Kuwait national public holidays.

    The working week is Sunday-Thursday: see ``_WORKING_WEEK``.

    National Day on 25 February and Liberation Day on 26 February, which marks the
    end of the 1990-91 occupation, are adjacent but separate. Neither is the UAE
    National Day that the shared set used to return for this country.
    """
    days = _gcc_eids(year)
    days.update(_hijri_dates_in_gregorian_year(*_HIJRI_NEW_YEAR, year))
    days.update(_hijri_dates_in_gregorian_year(*_PROPHETS_BIRTHDAY, year))
    days.update(
        {
            date(year, 1, 1),  # New Year's Day (Gregorian)
            date(year, 2, 25),  # National Day
            date(year, 2, 26),  # Liberation Day
        }
    )
    return days


def _holidays_bh(year: int) -> set[date]:
    """Bahrain national public holidays.

    The working week is Sunday-Thursday: see ``_WORKING_WEEK``.

    This is new coverage rather than a split. Bahrain had a working week here and
    no entry in ``_HOLIDAY_FUNCS`` at all, so every day that was not a weekend
    counted as a working day and no Eid was ever reachable for it.

    Stated limitation: Ashura, 9 and 10 Muharram, is a public holiday in Bahrain
    and is **not** included, because its observed span is not sourced confidently
    enough here to compute. The set is therefore short by two days rather than
    wrong by two. Short is the direction that overcounts working days, which pulls
    a derived deadline earlier, so this limitation is worth closing.
    """
    days = _gcc_eids(year)
    days.update(_hijri_dates_in_gregorian_year(*_HIJRI_NEW_YEAR, year))
    days.update(_hijri_dates_in_gregorian_year(*_PROPHETS_BIRTHDAY, year))
    days.update(
        {
            date(year, 1, 1),  # New Year's Day (Gregorian)
            date(year, 5, 1),  # Labour Day
            date(year, 12, 16),  # National Day
            date(year, 12, 17),  # National Day (2nd day)
        }
    )
    return days


def _holidays_om(year: int) -> set[date]:
    """Oman national public holidays.

    The working week is Sunday-Thursday: see ``_WORKING_WEEK``.

    New coverage rather than a split, on the same terms as Bahrain: Oman had a
    working week and no holiday function behind it.

    Stated limitation: the National Day holiday has been observed across both 18
    and 19 November in some years and on 18 November alone in others, and
    Renaissance Day has itself been moved. Only 18 November is claimed here, so
    this set is short rather than wrong in a year that observed both.
    """
    days = _gcc_eids(year)
    days.update(_hijri_dates_in_gregorian_year(*_HIJRI_NEW_YEAR, year))
    days.update(_hijri_dates_in_gregorian_year(*_PROPHETS_BIRTHDAY, year))
    days.update(
        {
            date(year, 1, 1),  # New Year's Day (Gregorian)
            date(year, 11, 18),  # National Day
        }
    )
    return days


def _holidays_in(year: int) -> set[date]:
    """India gazetted national holidays (Central Government - Gazette of India).

    Regional state holidays are excluded (too many variations). Diwali and
    Holi are lunisolar; their Gregorian dates are served from the curated
    ``_HINDU_HOLIDAYS`` table. Years outside the table simply omit those two
    festivals rather than guessing an incorrect date.
    """
    holidays: set[date] = {
        date(year, 1, 26),  # Republic Day
        date(year, 8, 15),  # Independence Day
        date(year, 10, 2),  # Gandhi Jayanti
        date(year, 12, 25),  # Christmas Day
    }
    hindu = _HINDU_HOLIDAYS.get(year)
    if hindu is not None:
        holidays.add(date(year, *hindu["holi"]))  # Holi (Phalguna Purnima)
        holidays.add(date(year, *hindu["diwali"]))  # Diwali (Kartik Amavasya)
    else:
        logger.info("No curated Hindu holiday dates for %d; Holi/Diwali omitted", year)

    return holidays


def _holidays_cn(year: int) -> set[date]:
    """China statutory public holidays (State Council, national holiday measures).

    Returns the STATUTORY days only, which is 13 a year from 2025 and 11 before
    it. Read the limitation at the end of this docstring before using the result
    to derive a deadline, because it does not err in the direction the other
    stated limitations in this file do.

    New Year's Day, Labour Day and the three National Day days are fixed
    Gregorian. Spring Festival, Qingming, Dragon Boat and Mid-Autumn come from
    ``_CN_FESTIVALS``, which covers 2024-2030 only. A year outside that window
    logs a warning and returns just the fixed days, which is a deliberate and
    documented shape rather than a silent shortfall.

    Festivals can coincide with fixed days, so the set is sometimes smaller than
    the statutory count without anything being wrong: in 2028 Mid-Autumn falls on
    3 October, the third day of National Day, and China observes the two as one
    longer break.

    Known limitation, and it is the point of this docstring: China moves working
    days. The State Council publishes an arrangement each year that stretches
    these statutory days into longer breaks and pays for them by turning
    particular Saturdays and Sundays into working days. It is announced annually,
    it is not derivable, and it is not modelled here.

    That omission does **not** have a safe direction, and this is where China
    differs from the short Bahrain and Oman sets, which are conservative because
    they can only overcount working days. The arrangement is a swap rather than a
    grant, so it has two halves pulling opposite ways:

    * The borrowed days off are not modelled, so days that are actually holidays
      count as working. That overcounts working days and pulls a derived deadline
      EARLIER, which is the dangerous direction.
    * The bridging weekends are not modelled, so days that are actually working
      count as weekend. That undercounts and pushes a deadline LATER.

    Because the arrangement borrows roughly what it spends, the two approximately
    cancel over a full year. What is wrong is therefore less the total than which
    days carry it, and the sign of the error on any one span depends on where
    that span begins and ends relative to a festival. Do not assume this function
    is conservative.
    """
    holidays: set[date] = {
        date(year, 1, 1),  # New Year's Day
        date(year, 5, 1),  # Labour Day
        date(year, 10, 1),  # National Day
        date(year, 10, 2),  # National Day (2nd day)
        date(year, 10, 3),  # National Day (3rd day)
    }
    if year >= _CN_HOLIDAY_REFORM_YEAR:
        holidays.add(date(year, 5, 2))  # Labour Day (2nd day), added by the 2025 reform

    festivals = _CN_FESTIVALS.get(year)
    if festivals is None:
        logger.warning(
            "No curated Chinese festival dates for %d (table covers %d-%d); Spring Festival, "
            "Qingming, Dragon Boat and Mid-Autumn are omitted and only the %d fixed Gregorian "
            "days are returned",
            year,
            _CN_FIRST_YEAR,
            _CN_LAST_YEAR,
            len(holidays),
        )
        return holidays

    spring_festival = date(year, *festivals["spring_festival"])
    if year >= _CN_HOLIDAY_REFORM_YEAR:
        holidays.add(spring_festival - timedelta(days=1))  # New Year's Eve, statutory from 2025
    holidays.update(spring_festival + timedelta(days=offset) for offset in range(3))

    holidays.add(date(year, *festivals["qingming"]))  # Qingming (solar term)
    holidays.add(date(year, *festivals["dragon_boat"]))  # Dragon Boat (lunar 5/5)
    holidays.add(date(year, *festivals["mid_autumn"]))  # Mid-Autumn (lunar 8/15)

    return holidays


def _holidays_jp(year: int) -> set[date]:
    """Japan national holidays (Cabinet Office, Act on National Holidays).

    Includes Golden Week cluster and special 2026 holidays.
    Substitution rule: when a holiday falls on Sunday, the next Monday
    is a substitute holiday.

    Four holidays move under the Happy Monday System and are computed as an
    n-th Monday rather than a fixed date: Coming of Age Day, Marine Day,
    Respect for the Aged Day and Sports Day. Because they can never land on a
    Sunday, the substitution rule above never fires for them.

    Known limitation: the one-off moves for the 2020 Olympics, which shifted
    Marine Day, Sports Day and Mountain Day in 2020 and again in 2021, are not
    modelled. Those two years therefore return the standing rule rather than
    the dates actually observed.
    """

    def _sub(d: date) -> set[date]:
        if d.weekday() == 6:  # Sunday → substitute holiday on Monday
            return {d, d + timedelta(days=1)}
        return {d}

    days: set[date] = set()
    for d in [
        date(year, 1, 1),  # New Year's Day (元旦)
        _nth_weekday(year, 1, 0, 2),  # Coming of Age Day - 2nd Monday Jan
        date(year, 2, 11),  # National Foundation Day (建国記念の日)
        date(year, 2, 23),  # Emperor's Birthday (天皇誕生日)
        date(year, 4, 29),  # Showa Day (昭和の日) - start of Golden Week
        date(year, 5, 3),  # Constitution Memorial Day (憲法記念日)
        date(year, 5, 4),  # Greenery Day (みどりの日)
        date(year, 5, 5),  # Children's Day (こどもの日) - end of Golden Week
        _nth_weekday(year, 7, 0, 3),  # Marine Day - 3rd Monday July
        date(year, 8, 11),  # Mountain Day (山の日)
        _nth_weekday(year, 9, 0, 3),  # Respect for the Aged Day - 3rd Monday Sep
        _nth_weekday(year, 10, 0, 2),  # Sports Day - 2nd Monday Oct
        date(year, 11, 3),  # Culture Day (文化の日)
        date(year, 11, 23),  # Labour Thanksgiving Day (勤労感謝の日)
    ]:
        days |= _sub(d)
    # Vernal Equinox (春分の日) and Autumnal Equinox (秋分の日): computed via the
    # standard integer approximation (accurate for 1980-2099). See _equinox_day.
    days |= _sub(date(year, 3, _equinox_day(year, spring=True)))
    days |= _sub(date(year, 9, _equinox_day(year, spring=False)))
    return days


def _holidays_br(year: int) -> set[date]:
    """Brazil national holidays (Lei 9.093/95 + Lei 10.607/02).

    Carnaval is calculated relative to Easter (47 days before Easter Sunday).
    """
    e = easter(year)
    carnaval_monday = e - timedelta(days=48)  # Monday
    carnaval_tuesday = e - timedelta(days=47)  # Tuesday (Mardi Gras)
    return {
        date(year, 1, 1),  # Confraternização Universal (New Year's)
        carnaval_monday,  # Carnaval (segunda-feira)
        carnaval_tuesday,  # Carnaval (terça-feira)
        e - timedelta(days=2),  # Paixão de Cristo (Good Friday)
        date(year, 4, 21),  # Tiradentes
        date(year, 5, 1),  # Dia do Trabalho
        date(year, 9, 7),  # Independência do Brasil
        date(year, 10, 12),  # Nossa Senhora Aparecida
        date(year, 11, 2),  # Finados
        date(year, 11, 15),  # Proclamação da República
        date(year, 11, 20),  # Consciência Negra (national since 2023)
        date(year, 12, 25),  # Natal
    }


def _holidays_ru(year: int) -> set[date]:
    """Russian federal non-working days (Labour Code Art. 112)."""
    return {
        # New Year holidays (1–8 January)
        date(year, 1, 1),
        date(year, 1, 2),
        date(year, 1, 3),
        date(year, 1, 4),
        date(year, 1, 5),
        date(year, 1, 6),
        date(year, 1, 7),  # Orthodox Christmas
        date(year, 1, 8),
        date(year, 2, 23),  # Defender of the Fatherland Day
        date(year, 3, 8),  # International Women's Day
        date(year, 5, 1),  # Spring and Labour Day
        date(year, 5, 9),  # Victory Day
        date(year, 6, 12),  # Russia Day
        date(year, 11, 4),  # День народного единства
    }


def _holidays_ng(year: int) -> set[date]:
    """Nigerian federal public holidays (Public Holidays Act, Cap. P40, LFN 2004).

    Six of the nine base dates in the Act's own Schedule are fixed or
    Easter-relative: New Year's Day, Good Friday, Easter Monday, Workers' Day
    (1 May), National Day (1 October) and Christmas Day. The remaining three -
    Eid al-Fitr, Eid al-Kabir (Eid al-Adha) and the Prophet's Birthday - are
    Minister-declared under the Act rather than fixed by statute, so this
    function converts them from the Islamic calendar the same way
    ``_gcc_eids`` does for the Gulf states. The Act leaves duration to that
    declaration entirely, and a single converted day is what this function
    asserts, which is a fact about the statute rather than a hedge: unlike
    ``_gcc_eids``, no multi-day span is applied here, because there is no
    sourced convention to apply one from.

    Two dates are current practice but are not in the base 1979 Schedule text
    this function's sourcing could retrieve directly. Both rest on
    corroboration from multiple independent secondary sources rather than on
    a primary instrument read in full:

    - Boxing Day, 26 December, observed alongside Christmas Day.
    - Democracy Day. Originally 29 May from 1999, moved to 12 June by
      presidential proclamation in 2018 to mark the anniversary of the
      annulled 12 June 1993 election, and understood to have been added to
      the Schedule by the Public Holidays (Amendment) Act 2019. That
      amendment's own text could not be retrieved for this function - its
      source no longer resolves - so 12 June rests on corroboration, not on
      the amending instrument having been read directly. A future reader with
      access to the 2019 amendment's text can close this gap.

    Section 5 of the Act is unusual among the countries in this file: a
    single holiday falling on a Saturday or Sunday gets no substitute day by
    default. Adjacent-pair rules exist in the Act for a Friday+Saturday,
    Saturday+Sunday or Sunday+Monday holiday combination, and ad hoc
    substitute days can be declared by the President or a state Governor
    under Section 2, but neither is computed here. Short is the direction
    that overcounts working days, which pulls a derived deadline earlier -
    the same direction of error ``_holidays_bh`` names for its own
    Minister-declared days.

    Children's Day, 27 May, is deliberately excluded. It is a holiday for
    primary and secondary school pupils, not a non-working day under the
    Public Holidays Act, and answers a different question than this function
    does.
    """
    days: set[date] = set()
    days.update(_hijri_dates_in_gregorian_year(10, 1, year))  # Eid al-Fitr, 1 Shawwal
    days.update(_hijri_dates_in_gregorian_year(12, 10, year))  # Eid al-Kabir, 10 Dhu al-Hijjah
    days.update(_hijri_dates_in_gregorian_year(*_PROPHETS_BIRTHDAY, year))
    e = easter(year)
    days.update(
        {
            date(year, 1, 1),  # New Year's Day
            e - timedelta(days=2),  # Good Friday
            e + timedelta(days=1),  # Easter Monday
            date(year, 5, 1),  # Workers' Day
            date(year, 6, 12),  # Democracy Day (moved from 29 May in 2018; see docstring)
            date(year, 10, 1),  # National Day (Independence Day)
            date(year, 12, 25),  # Christmas Day
            date(year, 12, 26),  # Boxing Day (see docstring)
        }
    )
    return days


def _holidays_bg(year: int) -> set[date]:
    """Bulgarian public holidays (Labour Code, Art. 154).

    Art. 154(1) lists the holidays; the four Easter-relative ones (Good
    Friday, Holy Saturday, Easter Sunday, Easter Monday) always include a
    Saturday and a Sunday by construction, since Easter Sunday is by
    definition a Sunday.

    Art. 154(2) moves every other holiday that falls on a Saturday or Sunday
    forward: the first working day when one weekend day is occupied, the
    first two working days when both are. The Easter block is explicitly
    carved out of this ("with the exception of the Easter holidays") -
    applying the rule to it regardless would add two non-working days after
    every single Easter, every year, since two of the four days are on a
    weekend by definition.

    The substitute for each occupied date is found the same way
    ``_holidays_ca`` finds one: scan forward, skipping weekend days and days
    already claimed. Processing the fixed holidays in calendar order and
    letting each substitute chain off the last is what turns "one weekend day
    occupied" into one added day and "two occupied" into two, without
    special-casing the pair: 24-26 December in a year where 24 December is a
    Saturday puts Christmas Eve and Christmas Day's substitutes on 27 and 28
    December, after Boxing Day, which is already a Monday holiday.
    """
    e = easter(year)
    easter_block = {
        e - timedelta(days=2),  # Good Friday
        e - timedelta(days=1),  # Holy Saturday
        e,  # Easter Sunday
        e + timedelta(days=1),  # Easter Monday
    }

    fixed = [
        date(year, 1, 1),  # New Year's Day
        date(year, 3, 3),  # Liberation Day
        date(year, 5, 1),  # Labour Day
        date(year, 5, 6),  # St George's Day, Day of the Bulgarian Army
        date(year, 5, 24),  # Day of Bulgarian Education and Culture and of Slavonic Literature
        date(year, 9, 6),  # Unification Day
        date(year, 9, 22),  # Independence Day
        date(year, 12, 24),  # Christmas Eve
        date(year, 12, 25),  # Christmas Day
        date(year, 12, 26),  # Second Day of Christmas
    ]

    days: set[date] = set(easter_block) | set(fixed)

    for holiday in fixed:
        if holiday.weekday() < _SATURDAY_INDEX:
            continue
        observed = holiday + timedelta(days=1)
        while observed.weekday() >= _SATURDAY_INDEX or observed in days:
            observed += timedelta(days=1)
        days.add(observed)

    return days


# ── Working-week definitions (date.weekday(): 0=Mon, 6=Sun) ──────────────────
#
# Standard Mon–Fri work week: {0, 1, 2, 3, 4}
# GCC Sun–Thu work week: {6, 0, 1, 2, 3}
#
# This is not the ISO numbering, which starts at Monday = 1. The platform holds
# both conventions at once: i18n_foundation's ``WorkCalendar.work_days`` counts
# Monday = 1 through Sunday = 7, and this table counts Monday = 0 through
# Sunday = 6, because ``is_working_day`` below asks ``date.weekday()``. Reaching
# for ``isoweekday()`` against this table shifts every day by one and pushes
# Sunday out of the set entirely. Calling both of them ISO is the one word that
# makes the two tables look interchangeable when they are not, and a Saudi row
# written under the wrong one has already shipped a four-day week once.
# ``tests/unit/test_work_calendar_weekdays_are_mon0.py`` guards the data. This
# comment guards the reader.

_WORKING_WEEK: dict[str, frozenset[int]] = {
    "DE": frozenset({0, 1, 2, 3, 4}),
    "AT": frozenset({0, 1, 2, 3, 4}),
    "CH": frozenset({0, 1, 2, 3, 4}),
    "GB": frozenset({0, 1, 2, 3, 4}),
    "UK": frozenset({0, 1, 2, 3, 4}),
    "US": frozenset({0, 1, 2, 3, 4}),
    "CA": frozenset({0, 1, 2, 3, 4}),
    "IN": frozenset({0, 1, 2, 3, 4}),
    "BR": frozenset({0, 1, 2, 3, 4}),
    "RU": frozenset({0, 1, 2, 3, 4}),
    "JP": frozenset({0, 1, 2, 3, 4}),
    "CN": frozenset({0, 1, 2, 3, 4}),
    # The UAE moved from Sunday-Thursday to Monday-Friday in 2022, with a half-day
    # Friday for the public sector. It is the only GCC state to have done so, so it
    # sits here rather than in the block below.
    "AE": frozenset({0, 1, 2, 3, 4}),
    # Middle East - Sunday through Thursday
    "SA": frozenset({6, 0, 1, 2, 3}),
    "QA": frozenset({6, 0, 1, 2, 3}),
    "KW": frozenset({6, 0, 1, 2, 3}),
    "BH": frozenset({6, 0, 1, 2, 3}),
    "OM": frozenset({6, 0, 1, 2, 3}),
    # Bulgaria: Labour Code Art. 136, 40 hours a week, 8 hours a day, a
    # direct statutory maximum rather than a convention.
    "BG": frozenset({0, 1, 2, 3, 4}),
    # Nigeria: Labour Act s.13 does not fix an economy-wide week; hours are
    # left to agreement, collective bargaining or an industrial wages board.
    # Monday-Friday here is the near-universal practical convention, not a
    # statute naming these five days the way Bulgaria's does.
    "NG": frozenset({0, 1, 2, 3, 4}),
}

_DEFAULT_WORKING_WEEK: frozenset[int] = frozenset({0, 1, 2, 3, 4})

_HOLIDAY_FUNCS: dict[str, Any] = {
    "DE": _holidays_de,
    "AT": _holidays_de,  # Austrian federal holidays closely mirror Germany's
    "CH": lambda y: {date(y, 1, 1), date(y, 8, 1), date(y, 12, 25)},  # simplified
    "GB": _holidays_uk,
    "UK": _holidays_uk,
    "US": _holidays_us,
    "CA": _holidays_ca,
    "AE": _holidays_ae,
    "SA": _holidays_sa,
    "QA": _holidays_qa,
    "KW": _holidays_kw,
    "BH": _holidays_bh,
    "OM": _holidays_om,
    "CN": _holidays_cn,
    "IN": _holidays_in,
    "JP": _holidays_jp,
    "BR": _holidays_br,
    "RU": _holidays_ru,
    "NG": _holidays_ng,
    "BG": _holidays_bg,
}


# ── Cache (year-scoped per country) ───────────────────────────────────────────

_holiday_cache: dict[tuple[str, int], dict[str, Any]] = {}


#: The axes a holiday answer is resolved on. They fail independently - a fully
#: covered country can still be asked for a year outside its curated lunisolar
#: table - so they are reported separately and a caller wanting a single verdict
#: asks :func:`app.core.provenance.weakest` rather than picking one.
AXIS_JURISDICTION = "jurisdiction"
AXIS_EFFECTIVE_YEAR = "effective_year"
AXIS_HOLIDAY_EXTENT = "holiday_extent"

#: What answers when no country table does: a working week with no public
#: holidays at all. Named rather than left blank because an uncovered country is
#: not ``UNAVAILABLE``. It has an answer, and the answer is simply not its own.
#:
#: Named for what the caller is holding rather than for the slot it fills. An
#: earlier spelling of this was ``INTERNATIONAL``, which named a category: it
#: would have been equally true of every international default in the tree, and
#: it asserted a standard behind what is really an absence. There is no
#: international convention that nobody has public holidays.
NO_PUBLIC_HOLIDAYS = "NO_PUBLIC_HOLIDAYS"

#: What answers for a year outside a curated lunisolar table: that country's
#: fixed Gregorian days, without the moveable feasts.
GREGORIAN_ONLY = "GREGORIAN_ONLY"

#: What answers for the length of each Eid across the Gulf: one shared span,
#: because the real length is announced annually by each government.
SHARED_GCC_EID_SPAN = "SHARED_GCC_EID_SPAN"

#: What answers for Switzerland: three fixed national days, under a function
#: whose own comment reads "simplified".
THREE_FIXED_DAYS = "THREE_FIXED_DAYS"

#: What answers in a year that straddles the end of the Hijri converter's
#: window: the part of the year the converter could still reach. An Islamic
#: holiday falling in the rest of it is invisible rather than absent.
HIJRI_WINDOW_EDGE = "HIJRI_WINDOW_EDGE"

#: What answers for a Japanese equinox outside 1980-2099: the same integer
#: formula, used beyond the range it was fitted to. Named for the extrapolation
#: rather than for the size of the error, which is not something this module
#: knows.
EXTRAPOLATED_EQUINOX = "EXTRAPOLATED_EQUINOX"

# Codes that are two spellings of one jurisdiction, as against one country
# served by another's table. GB and UK name the same state, so neither is a
# fallback for the other. AT is served by Germany's function under a comment
# saying Austrian holidays "closely mirror" Germany's, which is an
# approximation rather than a synonym, and is reported as one.
_CODE_SYNONYMS: tuple[frozenset[str], ...] = (frozenset({"GB", "UK"}),)


class HolidayCalculationError(RuntimeError):
    """A holiday computation for a covered country failed.

    Raised rather than returned as an empty set. An empty set is the honest
    answer for a country nothing covers, so a failure that returned one would
    be indistinguishable from it, and every non-weekend day of the year would
    quietly count as working.

    Carries the :class:`~app.core.provenance.Provenance` a caller needs to
    record what happened, so that catching this does not mean rebuilding it by
    hand and getting the source wrong. It is ``UNAVAILABLE`` and never
    ``FALLBACK``: there is no answer here to compute dates from.

    That last sentence was ruled on rather than assumed, and the argument for
    it was not the obvious one. A shipped test used to assert the opposite
    behaviour and its docstring called it degrading gracefully, so somebody did
    notice and did choose. What decides it against them is that
    :func:`is_working_day` is the only production consumer and it returns a
    bare ``bool``. A ``FALLBACK`` here would be a correct label on an answer
    that nothing in production reads, attached to a Gulf year missing every
    Eid, so nobody downstream could act on the degradation being flagged.

    What would reverse it: if :func:`is_working_day` ever grows a way to
    surface a degraded answer to its caller, ``FALLBACK`` becomes the honest
    choice and this should be reopened deliberately rather than re-derived from
    nothing.
    """

    def __init__(self, country_code: str, year: int, detail: str = "") -> None:
        super().__init__(f"Holiday calculation failed for {country_code}/{year}")
        self.country_code = country_code
        self.year = year
        self.provenance = unavailable(
            AXIS_JURISDICTION,
            country_code,
            detail or f"the holiday computation for {country_code} raised for {year}",
        )


# Countries whose holidays include lunisolar dates served from a curated table.
# Membership is tested against the table itself rather than against its first
# and last year: a range would call an interior gap complete, and the bounds
# would be a second copy of a fact the table already states. The names are the
# ones the per-country function leaves out when the year is not curated.
_CURATED_TABLES: dict[str, tuple[dict[int, Any], tuple[str, ...]]] = {
    "CN": (_CN_FESTIVALS, ("Spring Festival", "Qingming", "Dragon Boat", "Mid-Autumn")),
    "IN": (_HINDU_HOLIDAYS, ("Holi", "Diwali")),
}

#: Holidays whose dates are computed but whose length is not. ``_gcc_eids``
#: applies one span of three and four days to every Gulf country, because the
#: length of each Eid is announced annually by each government; the span is a
#: stand-in, not a measurement.
#:
#: This is a sibling of the ``omitted`` names and not a kind of coverage.
#: ``omitted`` says a row is missing from our data. This says a row is present
#: with an extent we did not work out. Both are facts about what the producing
#: function did.
#:
#: Named for the mechanism rather than for how wrong the result is, and the name
#: is load-bearing. "Placeholder" has an absence meaning "no placeholder we know
#: of", which is modest and true. A field called "approximate" or "unverified"
#: would have an absence meaning "verified", and nothing here has been verified,
#: least of all the tables nobody has ever questioned. How far off a given
#: country's span runs is not recorded, because that is a judgement and this is
#: not: closest to correct is still not computed.
_GCC_PLACEHOLDER_SPANS: tuple[str, ...] = ("Eid al-Fitr", "Eid al-Adha")
_PLACEHOLDER_SPANS: dict[str, tuple[str, ...]] = dict.fromkeys(
    ("AE", "SA", "QA", "KW", "BH", "OM"), _GCC_PLACEHOLDER_SPANS
)

#: The stand-in that answered for how far a country's holidays extend, for the
#: countries where nothing computed it. This is the third axis, and it is a
#: fallback rather than a kind of coverage: the dates are an answer and can be
#: computed with, they are simply not worked out. Switzerland sits here beside
#: the Gulf because a hardcoded three-date roster is as uncomputed as a
#: hardcoded span, and marking one while leaving the other would make the
#: absence of the mark mean less than it should.
#:
#: A country not listed here reports ``DECLARED`` on this axis, which says no
#: stand-in we know of, not that anybody checked. Nobody has checked the German
#: roster either.
_EXTENT_STANDINS: dict[str, str] = {
    **dict.fromkeys(("AE", "SA", "QA", "KW", "BH", "OM"), SHARED_GCC_EID_SPAN),
    "CH": THREE_FIXED_DAYS,
}

#: Countries whose holidays are computed through the Hijri converter, and which
#: therefore inherit its window. Hand-written, and held to the source by a test
#: that finds every holiday function reaching the converter either directly or
#: through ``_gcc_eids``. That test is the point of the pair: Nigeria joined
#: this set the day it was added and would have been missed by anybody writing
#: the list from memory of which countries are "the Gulf ones".
_HIJRI_DEPENDENT: frozenset[str] = frozenset({"AE", "BH", "KW", "NG", "OM", "QA", "SA"})

#: Countries whose dates come from a formula fitted to a stated range, and the
#: range. Japan's equinox approximation states 1980-2099 in ``_equinox_day`` and
#: was previously enforced nowhere.
#:
#: A window, not a membership table, and the difference is deliberate. A curated
#: table can be missing a year in the middle, so ``_CURATED_TABLES`` is tested
#: for membership and never for bounds. A formula's validity is continuous and
#: cannot have an interior gap, so here the bound is the fact rather than a
#: second copy of one. Do not unify these two on the grounds that they look
#: alike.
_FORMULA_WINDOWS: dict[str, tuple[int, int]] = {"JP": (1980, 2099)}

_EXTENT_DETAIL: dict[str, str] = {
    SHARED_GCC_EID_SPAN: (
        "Eid lengths are announced annually by each government; one shared span of three and four days "
        "stands in for all six Gulf countries"
    ),
    THREE_FIXED_DAYS: "three fixed national days stand in for the full Swiss calendar",
}


def _canonical_holiday_country(country_code: str) -> str:
    """Return the country whose holiday function actually answers for this code.

    ``_HOLIDAY_FUNCS`` points some codes at another country's function: AT is
    served by Germany's, GB and UK share one. A caller told only what it asked
    for cannot see that. Derived from the function's own name so that adding or
    removing an alias needs no second edit here, and so a lambda (which carries
    no country in its name) reports the code as asked for rather than guessing.
    """
    func = _HOLIDAY_FUNCS.get(country_code)
    name = getattr(func, "__name__", "")
    if name.startswith("_holidays_"):
        return name.removeprefix("_holidays_").upper()
    return country_code


def _year_standin(resolved: str, year: int, partial: bool, omitted_names: tuple[str, ...]) -> tuple[str, str] | None:
    """What stood in on the year axis, and why, or ``None`` if nothing did.

    Three mechanisms can limit a year, and they are checked in a fixed order so
    that the answer is stable rather than depending on which test happens to run
    first. They do not overlap today, because no country is served both by a
    curated lunisolar table and by the Hijri converter, and the order exists so
    that one which someday is still answers the same way on every call.
    """
    if partial:
        return GREGORIAN_ONLY, (
            f"{year} is outside {resolved}'s curated lunisolar table; {', '.join(omitted_names)} omitted"
        )

    if resolved in _HIJRI_DEPENDENT and _hijri_year_coverage(year) == HIJRI_EDGE:
        return HIJRI_WINDOW_EDGE, (
            f"{year} straddles the end of the Hijri converter's window, so an Islamic holiday falling "
            "in the part of the year it cannot reach is invisible rather than absent"
        )

    window = _FORMULA_WINDOWS.get(resolved)
    if window is not None and not window[0] <= year <= window[1]:
        # Two separate defects share this token and this axis, so they are two
        # clauses a reader can tell apart rather than one sentence with a long
        # explanation. The extrapolation applies at both ends of the window.
        # The roster is only wrong below it, and asserting it for a year above
        # it would be a true sentence about the wrong year.
        detail = (
            f"the equinox approximation was fitted to {window[0]}-{window[1]}, so {year}'s equinox "
            "days are extrapolated past the range it was fitted to"
        )
        if year < window[0]:
            detail += (
                "; separately, the modern holiday roster is applied whole to a year that predates it, "
                "rather than the roster as the law stood that year"
            )
        return EXTRAPOLATED_EQUINOX, detail

    return None


def _same_jurisdiction(requested: str, used: str) -> bool:
    """True when two codes name one state rather than one borrowing the other.

    The distinction decides whether sharing a holiday function is reported as a
    fallback. Britain answering to both GB and UK is a spelling; Austria
    answered by Germany's table is an approximation, and only the second is
    something a caller should be told about.
    """
    if requested == used:
        return True
    pair = {requested, used}
    return any(pair <= group for group in _CODE_SYNONYMS)


def resolve_holidays(country_code: str, year: int) -> dict[str, Any]:
    """Resolve public holidays for a country and year, with how they were found.

    The dates alone cannot answer the question a caller actually has, which is
    whether a short or empty set means "there are no more holidays" or "we could
    not work them out". The shape follows
    :func:`app.modules.carbon.service.resolve_grid_factor`: the value sits beside
    the fields describing where it came from, rather than inside a wrapper.

    There are three provenances rather than one because the axes fail
    independently. A country fully covered can still be asked for a year
    outside its curated lunisolar table, and a country covered for both can
    still hold a holiday whose length nobody computed. A single flag keyed on
    the country would have painted all three of those green.

    Args:
        country_code: ISO 3166-1 alpha-2 code, case-insensitive.
        year:         Gregorian year.

    Returns:
        A mapping of:

        ``dates``           frozenset of holiday dates, possibly empty.
        ``jurisdiction``    provenance on the country axis. ``DECLARED`` when a
                            table answered for the country asked about,
                            ``FALLBACK`` when another country's table answered
                            or when nothing covers it at all.
        ``effective_year``  provenance on the year axis. ``FALLBACK`` when the
                            year falls outside a curated lunisolar table and the
                            fixed Gregorian days answered alone.
        ``holiday_extent``  provenance on the span axis. ``FALLBACK`` when a
                            stand-in answered for how far the holidays extend
                            rather than a computation: the Gulf Eid lengths,
                            which are announced annually per country, and the
                            simplified Swiss roster. The dates are still an
                            answer and can be computed with, which is why this
                            is a fallback and not a failure, and why coverage
                            stays ``DECLARED`` on the other two axes.
        ``omitted``         names of the holidays such a year leaves out. Empty
                            unless ``effective_year`` is a fallback.
        ``placeholder_spans``
                            names of the holidays whose length is a stand-in.
                            Data beside ``holiday_extent``, the way ``omitted``
                            sits beside ``effective_year``. Branch on the
                            provenance, never on this.
        ``year``            the year asked for.

        A caller wanting one verdict passes all three to
        :func:`app.core.provenance.weakest` rather than reading whichever field
        it happens to remember; :func:`holiday_provenance` does that for it.
        That matters for the rule that nothing publishes as jurisdiction
        specific while a dimension it uses falls back: without the third axis,
        Saudi Arabia answered fully covered on a span its own source says runs
        short, and the rule read the answer rather than the caveat.

        Three empty sets mean three different things and are kept apart. A
        country with genuinely no public holidays is ``DECLARED`` with no dates,
        which is an answer. A country nothing covers is a ``FALLBACK`` to a week
        with no public holidays, which is a weaker answer. A failed computation
        is neither: it raises.

    Raises:
        HolidayCalculationError: the country is covered but its computation
            failed. Never reported as an empty set, and never cached.
    """
    cc = (country_code or "").upper().strip()
    key = (cc, year)
    cached = _holiday_cache.get(key)
    if cached is not None:
        return cached

    func = _HOLIDAY_FUNCS.get(cc)
    if func is None:
        result: dict[str, Any] = {
            "dates": frozenset(),
            "jurisdiction": fell_back(
                AXIS_JURISDICTION,
                cc,
                NO_PUBLIC_HOLIDAYS,
                detail="no holiday table for this country; a working week with no public holidays answered",
            ),
            "effective_year": declared(AXIS_EFFECTIVE_YEAR, str(year)),
            "holiday_extent": declared(AXIS_HOLIDAY_EXTENT, cc),
            "omitted": (),
            "placeholder_spans": (),
            "year": year,
        }
        _holiday_cache[key] = result
        return result

    try:
        dates = frozenset(func(year))
    except Exception as exc:
        # Deliberately not cached. Memoising a failure would make the first call
        # raise and every later one hand back a plausible empty set, so the
        # defect would present as a holiday-free year to everything downstream.
        logger.exception("Holiday calculation failed for %s/%d", cc, year)
        raise HolidayCalculationError(cc, year) from exc

    resolved = _canonical_holiday_country(cc)
    table, omitted_names = _CURATED_TABLES.get(resolved, (None, ()))
    partial = table is not None and year not in table

    if _same_jurisdiction(cc, resolved):
        jurisdiction = declared(AXIS_JURISDICTION, cc)
    else:
        jurisdiction = fell_back(
            AXIS_JURISDICTION,
            cc,
            resolved,
            detail=f"no holiday table for {cc}; {resolved}'s table answered",
        )

    # The curated window is described by naming what is missing rather than by
    # quoting the table's first and last year. Bounds there would be a second
    # copy of a fact the table already states, and would call an interior gap a
    # covered year. The other two limits are true windows and do quote bounds;
    # see _FORMULA_WINDOWS for why that is not a contradiction.
    year_standin = _year_standin(resolved, year, partial, omitted_names)
    if year_standin is None:
        effective_year = declared(AXIS_EFFECTIVE_YEAR, str(year))
    else:
        token, year_detail = year_standin
        effective_year = fell_back(AXIS_EFFECTIVE_YEAR, str(year), token, detail=year_detail)

    standin = _EXTENT_STANDINS.get(resolved)
    if standin is None:
        holiday_extent = declared(AXIS_HOLIDAY_EXTENT, cc)
    else:
        holiday_extent = fell_back(
            AXIS_HOLIDAY_EXTENT,
            cc,
            standin,
            detail=_EXTENT_DETAIL[standin],
        )

    result = {
        "dates": dates,
        "jurisdiction": jurisdiction,
        "effective_year": effective_year,
        "holiday_extent": holiday_extent,
        "omitted": omitted_names if partial else (),
        "placeholder_spans": _PLACEHOLDER_SPANS.get(resolved, ()),
        "year": year,
    }
    _holiday_cache[key] = result
    return result


def holiday_provenance(country_code: str, year: int) -> Provenance:
    """The weaker of the two axes, for a caller that wants a single verdict.

    A holiday set is only as trustworthy as its worst axis, so a caller deciding
    whether to present something as specific to a country asks this rather than
    reading whichever field it happens to remember.

    Raises:
        HolidayCalculationError: as :func:`resolve_holidays`. There is no
            provenance to weigh when nothing was computed.
    """
    resolved = resolve_holidays(country_code, year)
    return weakest(
        resolved[AXIS_JURISDICTION],
        resolved[AXIS_EFFECTIVE_YEAR],
        resolved[AXIS_HOLIDAY_EXTENT],
    )


def _get_holidays(country_code: str, year: int) -> frozenset[date]:
    """Return the holiday dates for a country/year pair.

    A narrow accessor over :func:`resolve_holidays`, for callers that only need
    the dates. Anything that has to decide what a short set *means* must call
    ``resolve_holidays`` and read its two provenance fields, or
    :func:`holiday_provenance` for the weaker of them.

    Deliberately still a ``frozenset`` rather than the mapping. Callers assert
    on the truthiness of this return to prove a country has holidays at all, and
    a non-empty mapping is truthy however empty the dates inside it are.
    """
    return resolve_holidays(country_code, year)["dates"]


# ── Public API ────────────────────────────────────────────────────────────────


def is_working_day(d: date, country_code: str) -> bool:
    """Return True if ``d`` is a working day for the given country.

    A day is non-working when:
    * Its ``date.weekday()`` (0=Mon, 6=Sun, not ISO) is not in the country's working week, OR
    * It falls on a public holiday.

    Args:
        d:            The date to check.
        country_code: ISO 3166-1 alpha-2 upper-case country code (e.g. ``"DE"``).
                      Unknown codes fall back to Mon–Fri with no holidays.

    A country nothing covers is a different thing from a country whose holidays
    could not be computed. The first is answered here as a working week with no
    holidays, which is the honest reading of data we do not have. The second
    raises, because answering it the same way would turn a broken computation
    into a year in which every weekday is a working day. Callers that need to
    tell a complete answer from a partial one should ask
    :func:`resolve_holidays` directly.

    Returns:
        bool - True when the date is a scheduled working day.

    Raises:
        HolidayCalculationError: the country is covered but its holiday
            computation failed.

    Examples::

        assert is_working_day(date(2026, 12, 25), "DE") is False  # Christmas
        assert is_working_day(date(2026, 12, 24), "DE") is True   # Thursday
        assert is_working_day(date(2026, 1,  4), "AE") is False   # Sunday (weekend)
    """
    cc = (country_code or "").upper().strip()
    working_week = _WORKING_WEEK.get(cc, _DEFAULT_WORKING_WEEK)
    if d.weekday() not in working_week:
        return False
    holidays = _get_holidays(cc, d.year)
    return d not in holidays


def next_working_day(d: date, country_code: str) -> date:
    """Return the next working day at or after ``d``.

    If ``d`` itself is a working day, ``d`` is returned unchanged.

    Args:
        d:            Starting date.
        country_code: ISO 3166-1 alpha-2 country code.

    Returns:
        date - The first working day >= ``d``.

    Examples::

        # Saturday → Monday
        next_working_day(date(2026, 1, 3), "DE") == date(2026, 1, 5)
        # Monday that is a holiday → next working day
        next_working_day(date(2026, 12, 25), "DE") == date(2026, 12, 28)
    """
    current = d
    # Safety cap: no country has more than 14 consecutive non-working days
    for _ in range(60):
        if is_working_day(current, country_code):
            return current
        current += timedelta(days=1)
    # Should be unreachable; return the cap boundary
    return current


def add_working_days(start: date, working_days: int, country_code: str) -> date:
    """Advance ``start`` by exactly ``working_days`` working days.

    Used by the CPM engine when scheduling task finish dates.

    Args:
        start:        The start date (must itself be a working day; if not,
                      the first working day from ``start`` is used).
        working_days: Number of working days to add (must be >= 0).
        country_code: ISO 3166-1 alpha-2 country code.

    Returns:
        date - The finish date (inclusive).
    """
    if working_days < 0:
        raise ValueError("working_days must be >= 0")
    current = next_working_day(start, country_code)
    remaining = working_days
    while remaining > 0:
        current += timedelta(days=1)
        current = next_working_day(current, country_code)
        remaining -= 1
    return current
