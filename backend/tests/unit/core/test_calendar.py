"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the working-days calendar engine's multi-year holiday computation.

These exercise the three holiday families that used to be single-year (2026)
stubs and are now computed for any year:

* Hijri (Islamic) holidays - Eid al-Fitr / Eid al-Adha via ``hijridate``.
* Japanese equinoxes - the standard integer approximation (1980-2099).
* Hindu holidays - Diwali / Holi from a curated multi-year lookup table.

Assertions cover 2026, 2027 and 2028 so a regression to a fixed-year stub
would fail immediately, plus graceful behaviour for years outside the curated
Hindu table.
"""

from __future__ import annotations

import logging
from datetime import date

import pytest

from app.core import calendar as cal
from app.core.calendar import (
    _CN_FESTIVALS,
    HijriRangeError,
    HolidayCalculationError,
    _equinox_day,
    _get_holidays,
    _hijri_dates_in_gregorian_year,
    is_working_day,
)

# ── Hijri (Eid al-Fitr / Eid al-Adha) ────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("year", "eid_al_fitr_start", "eid_al_adha_start"),
    [
        (2026, date(2026, 3, 20), date(2026, 5, 27)),
        (2027, date(2027, 3, 9), date(2027, 5, 16)),
        (2028, date(2028, 2, 26), date(2028, 5, 5)),
    ],
)
def test_eid_dates_multi_year(year: int, eid_al_fitr_start: date, eid_al_adha_start: date) -> None:
    """Eid al-Fitr (3 days) and Eid al-Adha (4 days) land on the Hijri dates."""
    holidays = _get_holidays("AE", year)
    ordinals = {d.toordinal() for d in holidays}

    # Eid al-Fitr spans 3 days from 1 Shawwal.
    for offset in range(3):
        assert (eid_al_fitr_start.toordinal() + offset) in ordinals, f"Eid al-Fitr day {offset} missing for {year}"

    # Eid al-Adha spans 4 days from 10 Dhu al-Hijjah.
    for offset in range(4):
        assert (eid_al_adha_start.toordinal() + offset) in ordinals, f"Eid al-Adha day {offset} missing for {year}"


@pytest.mark.unit
def test_eid_2026_not_using_2025_stub_dates() -> None:
    """Guard against the old hardcoded 2025-era dates leaking back in.

    The previous stub marked 30-31 March and 1 April plus 6-9 June 2026 as
    Eid. Those are actually the 2025 dates; the real 2026 Eids are 20 March
    and 27 May. This locks in the corrected values.
    """
    holidays = _get_holidays("AE", 2026)
    assert date(2026, 3, 20) in holidays
    assert date(2026, 5, 27) in holidays
    # Old wrong stub dates must NOT be present.
    assert date(2026, 3, 30) not in holidays
    assert date(2026, 6, 6) not in holidays


@pytest.mark.unit
def test_eid_can_occur_twice_in_one_gregorian_year() -> None:
    """A lunar holiday can fall twice in a Gregorian year (year is ~11d short).

    Eid al-Fitr (1 Shawwal) lands in both January and December of 2033.
    """
    fitr = _hijri_dates_in_gregorian_year(10, 1, 2033)
    assert len(fitr) == 2
    assert fitr[0].month == 1
    assert fitr[1].month == 12


@pytest.mark.unit
def test_hijri_out_of_range_year_refuses_instead_of_degrading_quietly() -> None:
    """Years beyond hijridate's range are unanswerable, not holiday-free.

    This test used to assert the opposite, that such a year degraded to the
    fixed Gregorian holidays without an exception, and it was right that the
    behaviour was deliberate rather than accidental. What made it the wrong
    contract is that the degradation was invisible: every Eid vanished, the
    year reported itself fully covered, and ``is_working_day`` counted Eid
    al-Fitr as a working day. Silence that a caller cannot detect is not
    graceful.

    hijridate supports Gregorian dates up to 2077-11-16.
    """
    with pytest.raises(HolidayCalculationError):
        _get_holidays("AE", 2099)
    with pytest.raises(HijriRangeError):
        _hijri_dates_in_gregorian_year(10, 1, 2099)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("label", "month", "day"),
    [
        ("Eid al-Fitr", 10, 1),
        ("Eid al-Adha", 12, 10),
        ("Hijri New Year", 1, 1),
        ("Prophet's Birthday", 3, 12),
    ],
)
def test_an_in_range_year_always_has_at_least_one_occurrence(label: str, month: int, day: int) -> None:
    """Inside the window an empty result never happens, which is why it can raise.

    The docstring used to say a fixed Hijri date can fall in a Gregorian year
    zero, one or two times, and the zero is wrong. The Hijri year is about 354
    days and the Gregorian 365, so consecutive occurrences are always closer
    together than a Gregorian year is long and cannot straddle one. Measured
    across the converter's whole window, 1925 to 2076, every one of these four
    dates lands once or twice in every year and never zero.

    That is what makes raising on an empty result safe rather than merely
    preferable: inside the window there is no legitimate empty for it to be
    confused with.
    """
    counts = {len(_hijri_dates_in_gregorian_year(month, day, year)) for year in range(1925, 2077)}
    assert counts <= {1, 2}, f"{label} produced an unexpected occurrence count: {sorted(counts)}"
    assert 0 not in counts, f"{label} fell zero times in some in-range year"


# ── Japanese equinoxes ────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("year", "spring_day", "autumn_day"),
    [
        (2026, 20, 23),
        (2027, 21, 23),
        (2028, 20, 22),
    ],
)
def test_equinox_days_multi_year(year: int, spring_day: int, autumn_day: int) -> None:
    """Vernal (March) and autumnal (September) equinox days match the almanac."""
    assert _equinox_day(year, spring=True) == spring_day
    assert _equinox_day(year, spring=False) == autumn_day


@pytest.mark.unit
@pytest.mark.parametrize(
    ("year", "spring", "autumn"),
    [
        (2026, date(2026, 3, 20), date(2026, 9, 23)),
        (2027, date(2027, 3, 21), date(2027, 9, 23)),
        (2028, date(2028, 3, 20), date(2028, 9, 22)),
    ],
)
def test_japan_equinox_holidays_present(year: int, spring: date, autumn: date) -> None:
    """The computed equinox dates appear in Japan's holiday set each year."""
    holidays = _get_holidays("JP", year)
    assert spring in holidays
    assert autumn in holidays
    # The old fixed Sep 22 stub was wrong for 2026/2027 (should be Sep 23).
    if year in (2026, 2027):
        assert date(year, 9, 22) not in holidays


# ── Hindu (Diwali / Holi) ─────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("year", "holi", "diwali"),
    [
        (2026, date(2026, 3, 4), date(2026, 11, 8)),
        (2027, date(2027, 3, 22), date(2027, 10, 29)),
        (2028, date(2028, 3, 11), date(2028, 10, 17)),
    ],
)
def test_hindu_holidays_multi_year(year: int, holi: date, diwali: date) -> None:
    """Holi and Diwali come from the curated table for covered years."""
    holidays = _get_holidays("IN", year)
    assert holi in holidays
    assert diwali in holidays


@pytest.mark.unit
def test_hindu_out_of_table_year_does_not_raise() -> None:
    """Years outside the curated table omit Holi/Diwali without crashing."""
    holidays = _get_holidays("IN", 2099)  # Far beyond the curated table.
    # Fixed gazetted holidays still present.
    assert date(2099, 1, 26) in holidays  # Republic Day
    assert date(2099, 12, 25) in holidays  # Christmas
    # No March/October lunisolar guesses for an uncovered year.
    march_or_october = {d for d in holidays if d.month in (3, 10) and d.day not in (2,)}
    # Gandhi Jayanti (Oct 2) is excluded above; nothing else should remain.
    assert march_or_october == set()


# ── End-to-end via the public API ─────────────────────────────────────────────


@pytest.mark.unit
def test_is_working_day_reflects_computed_holidays() -> None:
    """The public is_working_day API honours the computed lunar/equinox dates."""
    # Eid al-Adha 2027 runs 16-19 May. The 17th is a Monday, so it is a working day
    # by weekday and can only be non-working because the Eid is computed - which is
    # the point of the assertion. The 16th, a Sunday, used to be the anchor here and
    # stopped testing anything when the UAE week moved to Monday-Friday.
    assert is_working_day(date(2027, 5, 17), "AE") is False
    # Diwali 2028 (17 Oct, a Tuesday) is an India holiday → not working.
    assert is_working_day(date(2028, 10, 17), "IN") is False
    # Japan autumnal equinox 2028 (22 Sep, a Friday) → not working.
    assert is_working_day(date(2028, 9, 22), "JP") is False


@pytest.mark.unit
def test_holiday_cache_isolated_per_year() -> None:
    """Different years produce distinct holiday sets (no stale single-year cache)."""
    cal._holiday_cache.clear()
    h2026 = _get_holidays("AE", 2026)
    h2027 = _get_holidays("AE", 2027)
    assert h2026 != h2027


# ── Canada ────────────────────────────────────────────────────────────────────
#
# ``_HOLIDAY_FUNCS["CA"]`` was an alias to ``_holidays_us`` carrying the comment
# "simplified; close enough for MVP", so Canada was served US federal holidays.
# Nothing in the product called it with "CA", which is why it survived: these
# tests are the caller that did not exist. Every assertion below is chosen to
# flip under the alias rather than merely to pass now.


@pytest.mark.unit
def test_canada_gets_canadian_holidays_and_not_american_ones() -> None:
    """Canada Day is a holiday and Independence Day is a working day.

    This is the discriminating test. Under the old ``"CA": _holidays_us`` alias
    every one of these four assertions returns the opposite answer, and 2025 is
    chosen because 1 July and 4 July are both midweek that year, so a weekend
    cannot mask the difference.
    """
    # Canada Day, a Tuesday. Not in the US federal set at all.
    assert is_working_day(date(2025, 7, 1), "CA") is False
    # Independence Day, a Friday. A working day in Canada.
    assert is_working_day(date(2025, 7, 4), "CA") is True
    # Victoria Day, a Monday, which has no US counterpart.
    assert is_working_day(date(2025, 5, 19), "CA") is False
    # US Memorial Day, a Monday. An ordinary working day in Canada.
    assert is_working_day(date(2025, 5, 26), "CA") is True


@pytest.mark.unit
def test_provincial_holidays_are_out_of_scope_for_the_federal_set() -> None:
    """Family Day is provincial and is not smuggled into a national list.

    16 February 2026 is Ontario's Family Day *and* US Presidents' Day, so this
    also flips under the old alias. It is asserted as a working day because the
    federal set deliberately excludes days that differ between provinces.
    """
    assert is_working_day(date(2026, 2, 16), "CA") is True


@pytest.mark.unit
def test_a_statutory_day_on_a_weekend_moves_forward_not_back() -> None:
    """Canada moves an observed holiday to the following working day.

    1 July 2028 is a Saturday. Canada observes it on Monday the 3rd; the US rule
    in :func:`_holidays_us` would move it back to Friday the 30th. Asserting both
    sides pins the direction rather than only the presence of a substitution.
    """
    holidays = _get_holidays("CA", 2028)
    assert date(2028, 7, 3) in holidays
    assert date(2028, 6, 30) not in holidays


@pytest.mark.unit
@pytest.mark.parametrize("year", [2021, 2022, 2025, 2026, 2027, 2028, 2032])
def test_christmas_and_boxing_day_never_collapse_into_one_date(year: int) -> None:
    """Ten distinct federal days every year, including adjacent-substitution years.

    Christmas and Boxing Day are adjacent, so a naive substitution can land the
    second on a day the first already holds. A set would silently absorb it and
    the year would lose a holiday, which overcounts working days and pulls every
    derived deadline earlier. 2026 is the case in point: Boxing Day is a Saturday
    and moves to Monday the 28th rather than back onto Christmas Day.
    """
    assert len(_get_holidays("CA", year)) == 10


@pytest.mark.unit
def test_canadian_dates_agree_with_the_shipped_2026_work_calendar() -> None:
    """The computed set matches the hand-authored 2026 calendar the product seeds.

    ``i18n_foundation``'s ``work_calendars.json`` carries a Canadian row written
    by hand. Two independent constructions agreeing on all ten federal dates is
    worth more than either alone. The two provincial entries in that row, Family
    Day and the August civic holiday, are excluded here for the reason given in
    :func:`test_provincial_holidays_are_out_of_scope_for_the_federal_set`.
    """
    expected = {
        date(2026, 1, 1),  # New Year's Day
        date(2026, 4, 3),  # Good Friday
        date(2026, 5, 18),  # Victoria Day
        date(2026, 7, 1),  # Canada Day
        date(2026, 9, 7),  # Labour Day
        date(2026, 9, 30),  # National Day for Truth and Reconciliation
        date(2026, 10, 12),  # Thanksgiving
        date(2026, 11, 11),  # Remembrance Day
        date(2026, 12, 25),  # Christmas Day
        date(2026, 12, 28),  # Boxing Day, observed
    }
    assert _get_holidays("CA", 2026) == expected


# ── The UAE working week ──────────────────────────────────────────────────────
#
# `_WORKING_WEEK` gave the UAE a Sunday-Thursday week. The UAE moved to
# Monday-Friday in 2022 and is the only GCC state to have done so. These tests
# are anchored on the working week, which is a fixed rule, rather than on an Eid
# date, which is a hijridate conversion and moves every year.


@pytest.mark.unit
def test_uae_works_monday_to_friday() -> None:
    """Friday is a working day in the UAE and Sunday is not.

    Both assertions return the opposite answer under the old Sunday-Thursday
    entry. 2 and 4 January 2026 are chosen because neither is a holiday, so the
    weekday rule is the only thing under test.
    """
    assert is_working_day(date(2026, 1, 2), "AE") is True  # Friday
    assert is_working_day(date(2026, 1, 4), "AE") is False  # Sunday


@pytest.mark.unit
def test_the_rest_of_the_gulf_still_works_sunday_to_thursday() -> None:
    """Saudi Arabia is unchanged, which is what makes the UAE change a per-field one.

    The negative control for the change: the same two dates, the opposite answers.
    Qatar and Kuwait are asserted alongside because they share the entry Saudi
    Arabia does and a careless edit would take all four at once.
    """
    for gulf in ("SA", "QA", "KW"):
        assert is_working_day(date(2026, 1, 4), gulf) is True  # Sunday, a working day
        assert is_working_day(date(2026, 1, 2), gulf) is False  # Friday, the weekend


@pytest.mark.unit
def test_uae_holidays_still_reach_the_public_api_on_a_working_day() -> None:
    """A holiday landing midweek is still non-working once the weekend rule passes.

    Guards the failure mode the working-week change introduces: a country whose
    weekend now covers Saturday and Sunday can return False from the weekday check
    alone, which would hide a broken holiday set. National Day, 2 December 2026, is
    a Wednesday.

    The working-day control was 1 December until the per-country split, which is
    the point: this test was written when the shared set had never heard of
    Commemoration Day, so it picked a real UAE holiday as its example of an
    ordinary day and nothing could tell it otherwise. The control is now 30
    November, a Monday, which is also where Commemoration Day sat before it moved
    in 2019.
    """
    assert is_working_day(date(2026, 12, 2), "AE") is False  # National Day, a Wednesday
    assert is_working_day(date(2026, 12, 1), "AE") is False  # Commemoration Day, the Tuesday before
    assert is_working_day(date(2026, 11, 30), "AE") is True  # the Monday before that


# ── Per-country Gulf holiday sets ────────────────────────────────────────────
#
# AE, SA, QA and KW shared one holiday function until this split, and BH and OM
# had a working week in ``_WORKING_WEEK`` with no holiday function behind it, so
# ``_get_holidays`` returned an empty set and every non-weekend day counted as a
# working day.
#
# These are anchored on fixed Gregorian national days and on the working week,
# both of which are policy that does not move between years. Every anchor was
# checked to be a working weekday in its own country first, because a date that
# is already a weekend there makes ``is_working_day`` answer before it ever
# consults a holiday. Where an Eid appears, the docstring says explicitly that
# the assertion is about the hijridate conversion and not about how long a
# government chose to observe it.

_GULF = ("AE", "SA", "QA", "KW", "BH", "OM")


@pytest.mark.unit
def test_no_gulf_country_returns_another_countrys_national_day() -> None:
    """The defect the split exists to fix, stated as an assertion.

    One shared function returned UAE National Day on 2 and 3 December for Saudi
    Arabia, Qatar and Kuwait. A borrowed national day is worse than a missing
    one: it does not read as absent data, it reads as a plausible wrong answer,
    and a Saudi deadline would have moved for a holiday Saudi Arabia does not
    observe.
    """
    for cc in ("SA", "QA", "KW", "BH", "OM"):
        holidays = _get_holidays(cc, 2026)
        assert date(2026, 12, 2) not in holidays, f"{cc} still holds UAE National Day"
        assert date(2026, 12, 3) not in holidays, f"{cc} still holds UAE National Day"
    assert date(2026, 12, 2) in _get_holidays("AE", 2026)  # control: it is still the UAE's


@pytest.mark.unit
def test_no_two_gulf_countries_return_the_same_holiday_set() -> None:
    """Structural guard against a future re-merge, in whatever form it takes.

    The per-country assertions above each name a specific date, so they only
    catch a merge that happens to involve that date. Comparing whole sets catches
    one that does not: Bahrain and Oman are the likely pair to be collapsed back
    together, since their sets differ only in three fixed days and neither
    appears in the UAE National Day check.
    """
    sets = {cc: _get_holidays(cc, 2026) for cc in _GULF}
    for i, a in enumerate(_GULF):
        for b in _GULF[i + 1 :]:
            assert sets[a] != sets[b], f"{a} and {b} return an identical set"


@pytest.mark.unit
def test_saudi_arabia_does_not_observe_gregorian_new_year() -> None:
    """The only date the split removes, so the only one that can regress quietly.

    Every other country here gained days, and a gained day announces itself. Saudi
    Arabia lost 1 January, which the shared set gave it and which Saudi Arabia
    does not observe. An absence proves nothing by being absent, so it is asserted
    directly rather than left to the set comparison to imply.

    The two neighbours are the negative control, and they are what separates
    "Saudi Arabia is now correct" from "the New Year line was deleted for
    everyone", which the Saudi assertion alone cannot tell apart.
    """
    for year in (2026, 2027, 2028):
        assert date(year, 1, 1) not in _get_holidays("SA", year)
        assert date(year, 1, 1) in _get_holidays("AE", year)
        assert date(year, 1, 1) in _get_holidays("KW", year)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("country", "day", "label"),
    [
        ("AE", date(2026, 12, 1), "Commemoration Day"),
        ("AE", date(2026, 12, 2), "National Day"),
        ("SA", date(2026, 2, 22), "Founding Day"),
        ("SA", date(2026, 9, 23), "National Day"),
        ("QA", date(2026, 2, 10), "National Sports Day"),
        ("KW", date(2026, 2, 25), "National Day"),
        ("KW", date(2026, 2, 26), "Liberation Day"),
        ("BH", date(2026, 12, 16), "National Day"),
        ("OM", date(2026, 11, 18), "National Day"),
    ],
)
def test_each_gulf_national_day_reaches_the_public_api(country: str, day: date, label: str) -> None:
    """Each country's own national day is non-working through ``is_working_day``.

    Every date here is a working weekday in its own country, so the weekend rule
    cannot answer first and the holiday set is the only thing that can return
    False. Note that the two Gulf weeks disagree, so this is not one check
    repeated: 22 February 2026 is a Sunday, working in Saudi Arabia and a weekend
    in the UAE.

    Qatar's National Day, 18 December, is deliberately absent from this list. It
    falls on a Friday in 2026, which is a Qatari weekend, so the assertion would
    pass with no holiday set at all. It is covered by set membership below
    instead, where there is no weekend rule to short-circuit.
    """
    assert is_working_day(day, country) is False, f"{label} is not reaching {country}"


@pytest.mark.unit
def test_qatar_national_day_is_in_the_set_even_though_it_falls_on_a_weekend() -> None:
    """18 December 2026 is a Friday, so this is a membership test on purpose.

    Routing it through ``is_working_day`` would be a tautology in this year: the
    Qatari weekend answers False on its own and the holiday would never be
    consulted, so the assertion would survive the holiday being deleted.
    """
    assert date(2026, 12, 18) in _get_holidays("QA", 2026)
    assert date(2026, 12, 18) not in _get_holidays("AE", 2026)  # control: it is Qatar's alone


@pytest.mark.unit
def test_bahrain_and_oman_have_a_holiday_set_at_all() -> None:
    """New coverage rather than a split: both had a working week and no holidays.

    Absent from ``_HOLIDAY_FUNCS``, ``_get_holidays`` fell through to an empty
    frozenset for them, so no Eid and no national day was ever reachable and every
    day that was not a weekend counted as working. The truthiness check is the one
    that would have failed before this change; the rest keep the two apart.
    """
    for cc in ("BH", "OM"):
        assert _get_holidays(cc, 2026), f"{cc} still has no holidays at all"
    assert date(2026, 12, 16) in _get_holidays("BH", 2026)  # Bahrain National Day
    assert date(2026, 11, 18) in _get_holidays("OM", 2026)  # Oman National Day
    assert date(2026, 12, 16) not in _get_holidays("OM", 2026)
    assert date(2026, 11, 18) not in _get_holidays("BH", 2026)


@pytest.mark.unit
def test_the_two_eids_stay_shared_across_the_split() -> None:
    """Tests the Islamic-to-Gregorian conversion, not the observance policy.

    1 Shawwal and 10 Dhu al-Hijjah fall on the same Gregorian day in every
    country, so what this asserts is that splitting the national days did not
    split the calendar arithmetic along with them.

    It says nothing about how many days each government observes. That span is a
    single placeholder shared by all six and is known to be too short for Saudi
    Arabia, and no assertion here should be read as endorsing it.
    """
    for cc in _GULF:
        holidays = _get_holidays(cc, 2026)
        assert date(2026, 3, 20) in holidays, f"Eid al-Fitr missing for {cc}"
        assert date(2026, 5, 27) in holidays, f"Eid al-Adha missing for {cc}"


# ── China ─────────────────────────────────────────────────────────────────────
#
# China had a working week in ``_WORKING_WEEK`` and no entry in
# ``_HOLIDAY_FUNCS``, so the lookup fell through to an empty frozenset and every
# non-weekend day counted as working. It was the last member of that class.
#
# Spring Festival, Dragon Boat and Mid-Autumn are lunisolar and Qingming follows
# a solar term, so all four come from the curated ``_CN_FESTIVALS`` table rather
# than a rule. The tests below therefore have two jobs that are worth keeping
# apart: proving the function assembles the statutory days correctly, and
# proving the table's own rows are not guesses.


@pytest.mark.unit
def test_china_now_has_a_holiday_set_at_all() -> None:
    """New coverage: the lookup used to fall through to an empty set for China.

    The truthiness check is the assertion that would have failed before this
    change, and it is the one that matters, because an empty holiday set does not
    raise, does not log and returns a working-day count that looks reasonable.
    """
    assert _get_holidays("CN", 2026), "China still has no holidays at all"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("year", "expected", "why"),
    [
        (2024, 11, "pre-reform: Spring Festival is 3 days and Labour Day is 1"),
        (2025, 13, "the reform year: Spring Festival gains New Year's Eve, Labour Day gains 2 May"),
        (2026, 13, "a settled post-reform year"),
        (2028, 12, "Mid-Autumn falls on 3 October, the third day of National Day, so two days coincide"),
        (2030, 13, "the last year the table covers"),
    ],
)
def test_china_statutory_day_count_matches_the_state_council_total(year: int, expected: int, why: str) -> None:
    """The statutory total is 13 days from 2025 and 11 before it.

    A count is a weak assertion on its own, so it is paired here with the reason
    each year departs from the headline number. 2028 is the interesting row: it
    returns 12 rather than 13 because Mid-Autumn coincides with National Day, and
    a reader who does not know that would file the 12 as a bug.
    """
    assert len(_get_holidays("CN", year)) == expected, why


@pytest.mark.unit
def test_china_new_years_eve_became_statutory_in_2025() -> None:
    """The reform threshold, asserted from both sides.

    Spring Festival ran three days before 2025 and four after, the extra day
    being New Year's Eve. Asserting only the post-reform side would pass just as
    well if the eve had always been included, so the 2024 half is the control
    that gives the 2026 half its meaning.
    """
    # 2024: Spring Festival is 10 February, and 9 February is an ordinary day.
    assert date(2024, 2, 10) in _get_holidays("CN", 2024)
    assert date(2024, 2, 9) not in _get_holidays("CN", 2024)
    # 2026: Spring Festival is 17 February and the eve, 16 February, is statutory.
    assert date(2026, 2, 17) in _get_holidays("CN", 2026)
    assert date(2026, 2, 16) in _get_holidays("CN", 2026)
    # Same for the second Labour Day, which the same reform added.
    assert date(2024, 5, 2) not in _get_holidays("CN", 2024)
    assert date(2026, 5, 2) in _get_holidays("CN", 2026)


@pytest.mark.unit
def test_china_festival_offsets_stay_internally_consistent() -> None:
    """Guards the TABLE rather than the function, because the table is curated by hand.

    Dragon Boat is lunar 5/5 and Mid-Autumn is lunar 8/15, so both sit a bounded
    number of days after that same year's Spring Festival at lunar 1/1. Four lunar
    months of 29 or 30 days puts Dragon Boat between 120 and 124 days out. Seven
    puts Mid-Autumn near 220, unless a leap month falls between the two, which
    adds a whole lunar month and pushes it near 250.

    That structure is why a guessed row is catchable: a date invented by adding a
    fixed number of days to the previous year lands outside these bands. Two rows
    prove the test has teeth rather than one: 2025 carries a leap 6th month and
    2028 a leap 5th, and in both the leap month falls after Dragon Boat and before
    Mid-Autumn, so the two offsets must disagree with each other in a specific way
    rather than move together. Their Mid-Autumn offsets are 250 and 251, both in
    the leap band, so a second row landing there is expected and is not a defect.

    What this CANNOT catch is a whole table shifted the same direction, since
    every offset is relative. Extending the window means sourcing the dates.
    """
    for year, festivals in _CN_FESTIVALS.items():
        spring = date(year, *festivals["spring_festival"])
        dragon_boat_offset = (date(year, *festivals["dragon_boat"]) - spring).days
        mid_autumn_offset = (date(year, *festivals["mid_autumn"]) - spring).days

        assert 120 <= dragon_boat_offset <= 124, f"{year}: Dragon Boat is {dragon_boat_offset} days after 1/1"
        assert 219 <= mid_autumn_offset <= 222 or 249 <= mid_autumn_offset <= 252, (
            f"{year}: Mid-Autumn is {mid_autumn_offset} days after 1/1, which is neither a common"
            " year nor a leap year offset"
        )
        # Qingming follows a solar term rather than the lunar month, so it has no
        # offset to check. It is 4-6 April by construction, which bounds the damage.
        assert date(year, *festivals["qingming"]).month == 4
        assert 4 <= date(year, *festivals["qingming"]).day <= 6


@pytest.mark.unit
def test_china_outside_the_curated_window_is_loud_and_leaves_a_documented_shape(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A year the table does not cover must say so, not quietly return fewer days.

    This is the Bahrain and Oman defect wearing a different hat: a set that is
    short for a reason nobody can see. So the degradation is pinned to an exact
    shape, the six fixed Gregorian days, and to a warning rather than an info
    line, because an info line is not visible in a normal deployment.
    """
    cal._holiday_cache.clear()
    with caplog.at_level(logging.WARNING, logger="app.core.calendar"):
        holidays = _get_holidays("CN", 2031)

    assert holidays == {
        date(2031, 1, 1),  # New Year's Day
        date(2031, 5, 1),  # Labour Day
        date(2031, 5, 2),  # Labour Day (2nd day)
        date(2031, 10, 1),  # National Day
        date(2031, 10, 2),  # National Day (2nd day)
        date(2031, 10, 3),  # National Day (3rd day)
    }
    assert any("No curated Chinese festival dates for 2031" in r.getMessage() for r in caplog.records), (
        "the shortfall was silent"
    )
    # The control: a year inside the window must NOT warn.
    caplog.clear()
    cal._holiday_cache.clear()
    with caplog.at_level(logging.WARNING, logger="app.core.calendar"):
        _get_holidays("CN", 2030)
    assert not caplog.records, "a covered year warned anyway"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("day", "label"),
    [
        (date(2026, 2, 16), "New Year's Eve"),
        (date(2026, 2, 17), "Spring Festival"),
        (date(2026, 6, 19), "Dragon Boat"),
        (date(2026, 9, 25), "Mid-Autumn"),
        (date(2026, 10, 1), "National Day"),
    ],
)
def test_china_festivals_reach_the_public_api(day: date, label: str) -> None:
    """Each anchor is a working weekday in China, so the holiday set is load-bearing.

    Qingming and the second Labour Day are deliberately absent from this list.
    They fall on a Sunday and a Saturday in 2026, so the weekday rule would answer
    False on its own and the assertion would survive the holiday being deleted.
    They are covered by set membership below instead.
    """
    assert is_working_day(day, "CN") is False, f"{label} is not reaching China"


@pytest.mark.unit
def test_china_weekend_festivals_are_asserted_by_membership_not_by_the_public_api() -> None:
    """Qingming 2026 is a Sunday and the second Labour Day is a Saturday.

    Routing either through ``is_working_day`` would be a tautology in this year.
    Set membership has no weekend rule to short-circuit, so it still discriminates.
    """
    holidays = _get_holidays("CN", 2026)
    assert date(2026, 4, 5) in holidays  # Qingming, a Sunday
    assert date(2026, 5, 2) in holidays  # Labour Day 2nd day, a Saturday


@pytest.mark.unit
def test_an_ordinary_chinese_working_day_is_still_working() -> None:
    """The control for every assertion above, and its date is chosen with care.

    2 November 2026 is a Monday thirty days clear of the nearest statutory
    holiday. Somewhere closer would have been a worse control precisely because
    this function does not model the annual working-day arrangement: a Monday
    inside a National Day golden week is a real day off in China while this
    function calls it working, so asserting it here would bake the known
    limitation into a passing test.
    """
    assert is_working_day(date(2026, 11, 2), "CN") is True
