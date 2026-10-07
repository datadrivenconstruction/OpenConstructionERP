"""The planning week may extend a country's week; it may never rest a working day.

Two structures in this product answer questions about a working week, and they
answer *different* questions:

* ``core.calendar._WORKING_WEEK`` is the country's week: the days a statute or a
  near-universal convention says are worked. Weekdays are Mon=0..Sun=6.
* ``schedule.service.WORK_CALENDARS``, reached through ``get_work_calendar``, is
  the week the planner schedules against. Same Mon=0 convention, but it carries
  ``hours_per_day``, ``work_days`` and ``label``, and it is the only one of the
  two that any date arithmetic reads.

**Which assertion this file makes, and which it deliberately does not.**

It asserts *no conflict*, not equality. A construction schedule is not a
statutory week, and the shipped table says so in its own comments: Brazil is
marked ``44h/week legal`` and China ``common in construction``, both of which
plan a six-day site week on top of a five-day statutory one. That is a
deliberate model, so the planning week is allowed to *add* days.

What it may never do is *remove* one. If the country works Sunday and the
planning week rests it, every date the product computes for that country lands
on the wrong side of the weekend, and it does so silently, because a duration
still comes back as a plausible number.

    allowed:   planning_week ⊇ country_week        (an extension, e.g. Brazil)
    forbidden: country_week - planning_week ≠ ∅    (a misplaced rest day)

Do not weaken this into ``planning_week == country_week``. Equality would fail
Brazil, China and India, whose extra Saturday is intended, and "fixing" them to
make it pass would delete a deliberate site-week model.

**Why the absence case is tested separately.** A country missing from the
resolver does not raise; it falls through to ``DEFAULT``, a Monday-Friday week.
So a Gulf state that is simply absent gets exactly the same wrong weekend as one
that is mapped to the wrong calendar, with nothing to distinguish it from a
country that legitimately has no special calendar.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from app.core.calendar import _DEFAULT_WORKING_WEEK, _HOLIDAY_FUNCS, _WORKING_WEEK
from app.modules.schedule.service import _CALENDAR_BY_COUNTRY, WORK_CALENDARS, get_work_calendar

_DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _names(days: object) -> str:
    """Render a weekday set as day names, so a failure reads without decoding."""
    return ", ".join(_DAY_NAMES[d] for d in sorted(days))  # type: ignore[union-attr]


@pytest.mark.parametrize("country", sorted(_WORKING_WEEK))
def test_the_planning_week_never_rests_a_day_the_country_works(country: str) -> None:
    """Every day the country works must be a day the planner plans on.

    The reverse is not asserted: see this module's docstring. The planning week
    may hold days the country's week does not.
    """
    country_week = set(_WORKING_WEEK[country])
    planning_week = set(get_work_calendar(country)["work_days"])

    rested_but_worked = country_week - planning_week

    assert not rested_but_worked, (
        f"{country}: the planning calendar rests {_names(rested_but_worked)}, which this country works.\n"
        f"  country week  (core.calendar._WORKING_WEEK):     {_names(country_week)}\n"
        f"  planning week (schedule.get_work_calendar):      {_names(planning_week)}\n"
        f"  calendar selected:                               {get_work_calendar(country)['label']}\n"
        "This is a misplaced rest day, not a longer week. Every date computed for this country "
        "lands on the wrong side of the weekend."
    )


@pytest.mark.parametrize("country", sorted(_WORKING_WEEK))
def test_a_country_whose_week_is_not_monday_to_friday_is_routed_explicitly(country: str) -> None:
    """A non-default week must be mapped, because absence is indistinguishable from neutrality.

    ``get_work_calendar`` answers ``DEFAULT`` for any country it does not know,
    and ``DEFAULT`` is Monday-Friday. For a country whose week really is
    Monday-Friday that is the right answer by luck. For a Gulf state it is the
    wrong weekend, produced by the country simply not being in the table.
    """
    country_week = frozenset(_WORKING_WEEK[country])
    if country_week == _DEFAULT_WORKING_WEEK:
        pytest.skip(
            f"{country}: _WORKING_WEEK is Monday-Friday, so DEFAULT is a correct answer for it. "
            "This says nothing about the planning calendar, which may still be a longer week "
            "(Brazil, China and India all plan Monday-Saturday); that direction is checked above."
        )

    calendar = get_work_calendar(country)

    assert not calendar["week_fallback"], (
        f"{country} works {_names(country_week)}, which is not the default week, but the resolver "
        "falls through to WORK_CALENDARS['DEFAULT'] (Mon-Fri) because the country has no entry. "
        "Add it to _CALENDAR_BY_COUNTRY: a missing country looks exactly like a country with no "
        "special calendar, so nothing else will detect this."
    )


def test_a_planning_week_that_is_not_monday_to_friday_has_a_country_week_to_check_it_against() -> None:
    """The same absence mechanism, running the other way.

    The two tests above walk ``_WORKING_WEEK``, so they can only check a country
    the core table knows. A country routed to a calendar that no country week is
    ever compared against is invisible to both.

    The bar here is a planning week that is *not* Monday-Friday, not merely a
    non-default calendar, because a misplaced rest day is what this file exists
    to catch. Spain and France are routed to their own calendars and are absent
    from ``_WORKING_WEEK``; both plan Monday-Friday, so neither can carry the
    weekend on the wrong days, and France's separate entry exists to hold seven
    hours a day rather than a different set of days.

    Adding those two to ``_WORKING_WEEK`` is deliberately not done here.
    ``_WORKING_WEEK`` and ``_HOLIDAY_FUNCS`` have to move together, because a
    working week with no holiday function behind it is the defect that made
    ``_get_holidays`` return an empty set for Bahrain and Oman, counting every
    non-weekend day as a working day. Closing this gap properly means sourcing
    Spanish and French public holidays, which is its own change.

    That pairing used to be stated here, as a count of the countries the two
    registries share. The count went stale without anything failing, so the
    pairing is asserted by
    ``test_the_two_country_registries_hold_the_same_countries`` below and is no
    longer described here.
    """
    unguarded = []
    for country in sorted(_CALENDAR_BY_COUNTRY):
        calendar = get_work_calendar(country)
        if set(calendar["work_days"]) == set(_DEFAULT_WORKING_WEEK):
            continue
        if country not in _WORKING_WEEK:
            unguarded.append(f"  {country} -> {calendar['label']}, no _WORKING_WEEK entry")

    assert unguarded == [], (
        "these countries plan a week that is not Monday-Friday, and no country week is ever "
        "compared against it:\n"
        + "\n".join(unguarded)
        + "\nAdd the country to core.calendar._WORKING_WEEK, and a holiday function beside it, so the "
        "conflict check above covers it."
    )


def _registry_gap(working_week: Mapping[str, Any], holiday_funcs: Mapping[str, Any]) -> list[str]:
    """Describe, in both directions, how two country registries differ.

    One line per country present in one registry and absent from the other,
    naming the registry that holds it. An empty list means the key sets are equal.

    Both registries are arguments rather than module globals read directly, which
    is what lets the negative control below hand it a pair that really differs.
    """
    week = set(working_week)
    funcs = set(holiday_funcs)
    return [f"  {c}: in _WORKING_WEEK, absent from _HOLIDAY_FUNCS" for c in sorted(week - funcs)] + [
        f"  {c}: in _HOLIDAY_FUNCS, absent from _WORKING_WEEK" for c in sorted(funcs - week)
    ]


def test_the_two_country_registries_hold_the_same_countries() -> None:
    """A country week and a holiday function are added together or not at all.

    This was a sentence in the module docstring for as long as it was true, and a
    sentence cannot fail. It carried a count, the count said nineteen, both
    registries had grown to twenty, and nothing anywhere went red.

    The assertion is strict pairing, and the reason is *not* that every unpaired
    row misbehaves. An unpaired row whose week is Monday-Friday is inert: the only
    read of ``_WORKING_WEEK`` is a ``.get`` against ``_DEFAULT_WORKING_WEEK``,
    which is Monday-Friday already, so such a row cannot change a computed answer
    for any date. The row that bites is one whose week *differs* from the default
    with no holiday function behind it, which is exactly what Bahrain and Oman
    were: a Sunday-Thursday week and an empty holiday set, so every non-weekend
    day came back working. The risk lives in the delta from the default, not in
    the absence of a neighbour.

    Strict pairing is asserted regardless, because the pairing is what the rest of
    this file leans on when it declines to add a country, and an unpaired row
    makes that reasoning silently untrue.
    """
    gap = _registry_gap(_WORKING_WEEK, _HOLIDAY_FUNCS)

    assert gap == [], (
        "core.calendar._WORKING_WEEK and core.calendar._HOLIDAY_FUNCS no longer cover the same "
        "countries:\n" + "\n".join(gap) + "\n"
        "Add the missing half in the same change. A country week with no holiday function answers "
        "every non-weekend day as working; a holiday function with no country week is answered "
        "against the default Monday-Friday week, which is a guess rather than a statement."
    )


@pytest.mark.parametrize(
    ("extra_side", "expected_line"),
    [
        ("working_week", "  ZZ: in _WORKING_WEEK, absent from _HOLIDAY_FUNCS"),
        ("holiday_funcs", "  ZZ: in _HOLIDAY_FUNCS, absent from _WORKING_WEEK"),
    ],
)
def test_the_registry_comparison_names_whichever_direction_the_difference_falls_in(
    extra_side: str, expected_line: str
) -> None:
    """Prove the comparison can fail at all, and can tell the two directions apart.

    A check that only asserts one registry is contained in the other passes on
    half of the defect, and it is the half nobody is watching for. So the control
    runs once per direction, and each run asserts the opposite direction stays
    silent by requiring the gap to be that one line and nothing else.

    ``ZZ`` is ISO 3166-1 user-assigned, and is asserted absent from both
    registries before it is used, so the control cannot pass by colliding with a
    real entry.
    """
    assert "ZZ" not in _WORKING_WEEK, "the control code must be absent from _WORKING_WEEK or it proves nothing"
    assert "ZZ" not in _HOLIDAY_FUNCS, "the control code must be absent from _HOLIDAY_FUNCS or it proves nothing"

    if extra_side == "working_week":
        gap = _registry_gap({**_WORKING_WEEK, "ZZ": frozenset({0})}, _HOLIDAY_FUNCS)
    else:
        gap = _registry_gap(_WORKING_WEEK, {**_HOLIDAY_FUNCS, "ZZ": lambda year: set()})

    assert gap == [expected_line], (
        f"the comparison was handed a pair differing only in {extra_side} and did not report it "
        f"as exactly that one difference; it said: {gap}"
    )


def test_a_region_string_naming_the_gulf_gets_the_week_five_of_the_six_states_work() -> None:
    """``GULF`` is a legacy region head whose meaning changed when the entry split.

    A project stored with the bare region string ``GULF`` used to get a six-day
    Monday-Saturday week. It now gets Sunday-Thursday, which is right for Saudi
    Arabia, Qatar, Kuwait, Bahrain and Oman and wrong for the UAE. The UAE is
    reachable by its own code, its own label and its own catalogue id, so the
    only way to land here wrongly is to have stored a UAE project under a region
    string that names the region rather than the country.
    """
    gulf = get_work_calendar("GULF")
    assert gulf["work_days"] == {6, 0, 1, 2, 3}, "the bare GULF head must mean the Sunday-Thursday week"
    assert gulf["hours_per_day"] == 8

    for region in ("AE", "AE_DUBAI", "United Arab Emirates"):
        assert get_work_calendar(region)["work_days"] == {0, 1, 2, 3, 4}, (
            f"{region!r} must reach the UAE calendar, not the Sunday-Thursday one"
        )


def test_the_two_structures_are_told_apart_by_field_name_not_by_shape() -> None:
    """Pin the discriminator, because four structures in this repo look alike.

    ``WORK_CALENDARS`` entries carry ``hours_per_day``. The ``schedule_advanced``
    and ``i18n_foundation`` calendars carry ``work_hours_per_day``, and the
    ``i18n_foundation`` one is 1-based (Mon=1, matched by ``isoweekday()``) where
    this one is 0-based. An assertion placed on the wrong structure passes while
    measuring nothing, so the field name is the thing worth holding still.
    """
    for key, calendar in WORK_CALENDARS.items():
        assert "hours_per_day" in calendar, f"{key} is missing hours_per_day"
        assert "work_hours_per_day" not in calendar, (
            f"{key} carries work_hours_per_day, which belongs to the schedule_advanced and "
            "i18n_foundation calendars. A different field name means a different structure."
        )
        assert all(0 <= d <= 6 for d in calendar["work_days"]), (
            f"{key} declares a weekday outside 0..6; this table is Mon=0..Sun=6, not isoweekday"
        )
