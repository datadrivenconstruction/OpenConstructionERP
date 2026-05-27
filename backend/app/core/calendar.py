"""Working-days calendar engine — Wave 28 of the worldwide-parameterisation audit.

Provides:
    is_working_day(date, country_code) -> bool
    next_working_day(date, country_code) -> date

Per-country rules are defined inline (public holidays and working weeks) and
drawn from the regional-pack ``holidays`` config keys.

Easter computation uses ``dateutil.easter`` (already a project dependency).
Lunar holidays (Eid al-Fitr, Eid al-Adha, Diwali, Holi, Carnaval) are
approximated — see in-code TODO comments.  Real lunar-calendar support is a
separate epic requiring Hijri / Hindu calendar libraries.

Sources:
- DE: Bundesgesetzblatt, 2026 federal holidays for all states' common days
- UK: HM Government bank holidays list (published annually)
- US: 5 U.S.C. § 6103 (federal public holidays)
- AE/SA (Middle East): Federal Decree-Law No. 33/2021 (UAE); Saudi Ministry of HR
- IN: Gazette of India, 2026 gazetted holidays
- JP: Cabinet Office Japan, 2026 national holidays
- BR: Federal Law 9.093/95 and 10.607/02 (national holidays)
- RU: Labour Code of the Russian Federation, Art. 112
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from dateutil.easter import easter  # type: ignore[import]

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


# ── Per-country holiday calculators ──────────────────────────────────────────


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
        _nth_weekday(year, 1, 0, 3),  # MLK Day — 3rd Monday January
        _nth_weekday(year, 2, 0, 3),  # Presidents' Day — 3rd Monday February
        _nth_weekday(year, 5, 0, -1),  # Memorial Day — last Monday May
        _nth_weekday(year, 9, 0, 1),  # Labor Day — 1st Monday September
        _nth_weekday(year, 10, 0, 2),  # Columbus Day — 2nd Monday October
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving — 4th Thursday November
    ]
    return {_observed(d) for d in fixed} | set(computed)


def _holidays_me(year: int) -> set[date]:
    """GCC/Middle-East public holidays (UAE federal, Saudi national).

    Working week is Sunday–Thursday (weekdays 6, 0, 1, 2, 3).
    Eid al-Fitr and Eid al-Adha are lunar-calendar events.
    TODO: Replace stub with a proper Hijri→Gregorian converter when the
          lunar-calendar epic is implemented.  Stub conservatively marks
          the approximate window as non-working.
    """
    holidays: set[date] = {
        date(year, 1, 1),  # New Year's Day (Gregorian)
        date(year, 12, 2),  # UAE National Day
        date(year, 12, 3),  # UAE National Day (2nd day)
    }
    # Eid al-Fitr stub (end of Ramadan): approximately late March / early April
    # in 2026 the lunar calendar places it around ~March 30.
    # TODO: Use a Hijri library for accurate calculation.
    holidays.add(date(year, 3, 30))  # Eid al-Fitr approx Day 1
    holidays.add(date(year, 3, 31))  # Eid al-Fitr approx Day 2
    holidays.add(date(year, 4, 1))  # Eid al-Fitr approx Day 3

    # Eid al-Adha stub: approximately early June 2026.
    # TODO: Use a Hijri library for accurate calculation.
    holidays.add(date(year, 6, 6))  # Eid al-Adha approx Day 1
    holidays.add(date(year, 6, 7))  # Eid al-Adha approx Day 2
    holidays.add(date(year, 6, 8))  # Eid al-Adha approx Day 3
    holidays.add(date(year, 6, 9))  # Eid al-Adha approx Day 4

    return holidays


def _holidays_in(year: int) -> set[date]:
    """India gazetted national holidays (Central Government — Gazette of India).

    Regional state holidays are excluded (too many variations).
    Diwali and Holi are lunar/lunisolar — approximate dates used.
    TODO: Replace stubs with a proper Hindu panchang calculation.
    """
    holidays: set[date] = {
        date(year, 1, 26),  # Republic Day
        date(year, 8, 15),  # Independence Day
        date(year, 10, 2),  # Gandhi Jayanti
        date(year, 12, 25),  # Christmas Day
    }
    # Holi stub: ~approx March 13 for 2026 (Phalgun Purnima)
    # TODO: Replace with Hindu calendar computation.
    holidays.add(date(year, 3, 13))  # Holi (approx)

    # Diwali stub: ~approx Oct 20 for 2026 (Karthik Amavasya)
    # TODO: Replace with Hindu calendar computation.
    holidays.add(date(year, 10, 20))  # Diwali (approx)

    return holidays


def _holidays_jp(year: int) -> set[date]:
    """Japan national holidays (Cabinet Office, Act on National Holidays).

    Includes Golden Week cluster and special 2026 holidays.
    Substitution rule: when a holiday falls on Sunday, the next Monday
    is a substitute holiday.
    """

    def _sub(d: date) -> set[date]:
        if d.weekday() == 6:  # Sunday → substitute holiday on Monday
            return {d, d + timedelta(days=1)}
        return {d}

    days: set[date] = set()
    for d in [
        date(year, 1, 1),  # New Year's Day (元旦)
        _nth_weekday(year, 1, 0, 2),  # Coming of Age Day — 2nd Monday Jan
        date(year, 2, 11),  # National Foundation Day (建国記念の日)
        date(year, 2, 23),  # Emperor's Birthday (天皇誕生日)
        date(year, 4, 29),  # Showa Day (昭和の日) — start of Golden Week
        date(year, 5, 3),  # Constitution Memorial Day (憲法記念日)
        date(year, 5, 4),  # Greenery Day (みどりの日)
        date(year, 5, 5),  # Children's Day (こどもの日) — end of Golden Week
        _nth_weekday(year, 7, 0, 3),  # Marine Day — 3rd Monday July
        date(year, 8, 11),  # Mountain Day (山の日)
        _nth_weekday(year, 9, 0, 3),  # Respect for the Aged Day — 3rd Monday Sep
        date(year, 10, 14),  # Sports Day (スポーツの日) — 2nd Monday Oct (approx)
        date(year, 11, 3),  # Culture Day (文化の日)
        date(year, 11, 23),  # Labour Thanksgiving Day (勤労感謝の日)
    ]:
        days |= _sub(d)
    # Autumnal Equinox (秋分の日): approx Sep 22-23 — use 23 as a reasonable stub
    # TODO: Precise equinox calculation
    days |= _sub(date(year, 9, 22))
    # Vernal Equinox (春分の日): approx Mar 20
    days |= _sub(date(year, 3, 20))
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
        date(year, 2, 23),  # День защитника Отечества
        date(year, 3, 8),  # Международный женский день
        date(year, 5, 1),  # Праздник Весны и Труда
        date(year, 5, 9),  # День Победы
        date(year, 6, 12),  # День России
        date(year, 11, 4),  # День народного единства
    }


# ── Working-week definitions (ISO weekday: 0=Mon, 6=Sun) ─────────────────────
#
# Standard Mon–Fri work week: {0, 1, 2, 3, 4}
# GCC Sun–Thu work week: {6, 0, 1, 2, 3}

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
    # Middle East — Sunday through Thursday
    "AE": frozenset({6, 0, 1, 2, 3}),
    "SA": frozenset({6, 0, 1, 2, 3}),
    "QA": frozenset({6, 0, 1, 2, 3}),
    "KW": frozenset({6, 0, 1, 2, 3}),
    "BH": frozenset({6, 0, 1, 2, 3}),
    "OM": frozenset({6, 0, 1, 2, 3}),
}

_DEFAULT_WORKING_WEEK: frozenset[int] = frozenset({0, 1, 2, 3, 4})

_HOLIDAY_FUNCS: dict[str, Any] = {
    "DE": _holidays_de,
    "AT": _holidays_de,  # Austrian federal holidays closely mirror Germany's
    "CH": lambda y: {date(y, 1, 1), date(y, 8, 1), date(y, 12, 25)},  # simplified
    "GB": _holidays_uk,
    "UK": _holidays_uk,
    "US": _holidays_us,
    "CA": _holidays_us,  # simplified; close enough for MVP
    "AE": _holidays_me,
    "SA": _holidays_me,
    "QA": _holidays_me,
    "KW": _holidays_me,
    "IN": _holidays_in,
    "JP": _holidays_jp,
    "BR": _holidays_br,
    "RU": _holidays_ru,
}


# ── Cache (year-scoped per country) ───────────────────────────────────────────

_holiday_cache: dict[tuple[str, int], frozenset[date]] = {}


def _get_holidays(country_code: str, year: int) -> frozenset[date]:
    """Return the cached set of holiday dates for a country/year pair."""
    key = (country_code, year)
    if key not in _holiday_cache:
        func = _HOLIDAY_FUNCS.get(country_code)
        if func is None:
            _holiday_cache[key] = frozenset()
        else:
            try:
                _holiday_cache[key] = frozenset(func(year))
            except Exception:
                logger.exception("Holiday calculation failed for %s/%d", country_code, year)
                _holiday_cache[key] = frozenset()
    return _holiday_cache[key]


# ── Public API ────────────────────────────────────────────────────────────────


def is_working_day(d: date, country_code: str) -> bool:
    """Return True if ``d`` is a working day for the given country.

    A day is non-working when:
    * Its ISO weekday (0=Mon, 6=Sun) is not in the country's working week, OR
    * It falls on a public holiday.

    Args:
        d:            The date to check.
        country_code: ISO 3166-1 alpha-2 upper-case country code (e.g. ``"DE"``).
                      Unknown codes fall back to Mon–Fri with no holidays.

    Returns:
        bool — True when the date is a scheduled working day.

    Examples::

        assert is_working_day(date(2026, 12, 25), "DE") is False  # Christmas
        assert is_working_day(date(2026, 12, 24), "DE") is True   # Thursday
        assert is_working_day(date(2026, 1,  2), "AE") is False   # Friday (weekend)
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
        date — The first working day >= ``d``.

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
        date — The finish date (inclusive).
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
