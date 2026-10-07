"""An agreement between the two working-week registries only counts when both sides answered.

Two registries answer "which days does this country work":

* ``core.calendar._WORKING_WEEK``, keyed by ISO country code.
* ``schedule.service``, reached through ``_get_work_week``, keyed by a project's
  free-text region and resolved through several paths.

Both substitute silently for a country they do not carry. ``_get_work_week``
returns ``WORK_CALENDARS["DEFAULT"]``, a Monday-Friday week, and
``core.calendar.is_working_day`` reads ``_WORKING_WEEK.get(cc, _DEFAULT_WORKING_WEEK)``
and answers Monday-Friday with no holidays. Neither says it has done so.

**Why that makes an agreement untrustworthy and a difference trustworthy.** A
difference is a positive result: something had to be computed on both sides for the
two answers to come out unequal. An agreement is the *absence* of a computed
difference, and an absence has two causes. The systems agree, or nothing was
measured. Take any country neither registry carries and any weekend date: both
return "not working", a comparison prints "agree", and nothing whatsoever has been
established.

So a comparison of these two registries has three outcomes, not two, and this file
exists to keep the third one visible:

    comparable   both sides resolved a real entry; agree or differ both mean something
    unmeasured   at least one side substituted; neither agreement nor disagreement
    absent       the country is in neither registry; out of scope here

**Why resolution is proved by identity and never by a label.** The fallback calendar
is a complete, confident dict with a plausible label. Reading the label is how a
first pass at this measurement reported Nigeria as a genuine difference: the value
looked like an answer because it *is* an answer, just not that country's. Identity
against the ``DEFAULT`` object is the only cheap proof that a lookup found something.
``test_no_country_resolves_to_the_default_calendar_object`` guards the premise that
makes identity valid.

**Why the resolver is asked rather than the country map read.** ``_get_work_week``
resolves a calendar key before it consults ``_CALENDAR_BY_COUNTRY``, so a code that is
also a calendar key resolves without appearing in that map. Reading the map and
reading the resolver give different answers, and only one of them is what the product
does. Every check below asks the resolver.

**Boundary with the neighbouring gate.**
``test_work_calendar_rest_days_do_not_conflict.py`` asks whether a *misplaced rest
day* can exist, and correctly skips countries whose week is Monday-Friday, because
the Monday-Friday fallback cannot put the weekend on the wrong days for them. That
skip is right for that question and it is exactly the population this file is about:
a country whose week is Monday-Friday on one side and absent on the other is the case
where a fallback is invisible to every existing check.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pytest

from app.core.calendar import _WORKING_WEEK
from app.modules.schedule.service import (
    _CALENDAR_BY_COUNTRY,
    WORK_CALENDARS,
    _get_work_week,
)

COMPARABLE = "comparable"
UNMEASURED = "unmeasured"

#: Countries where one registry holds an opinion and the other substitutes, so any
#: comparison of the two is unmeasured rather than agreeing. This is a ratchet: it may
#: shrink, and a country joining it fails the gate. It is recorded rather than derived
#: on purpose, because deriving the expectation from the same code under test would
#: assert nothing. The population it is checked against *is* derived, so a country
#: added to either registry is covered without touching this set.
_KNOWN_UNMEASURED: frozenset[str] = frozenset({"BG", "ES", "FR", "JP", "NG"})


def _population(core_weeks: Mapping[str, Any], country_map: Mapping[str, Any]) -> list[str]:
    """Every country either registry claims to know, derived rather than listed."""
    return sorted(set(core_weeks) | set(country_map))


def _sides(
    country: str,
    *,
    core_weeks: Mapping[str, Any],
    resolve: Callable[[str], Any],
    default_calendar: Any,
) -> tuple[bool, bool]:
    """Return whether each side resolved a real entry for ``country``.

    The planning side is proved by identity against the default calendar object,
    never by inspecting the returned value, which is indistinguishable from a real
    Monday-Friday answer.
    """
    return country in core_weeks, resolve(country) is not default_calendar


def _classify(country: str, **kwargs: Any) -> str:
    core_resolved, planning_resolved = _sides(country, **kwargs)
    return COMPARABLE if core_resolved and planning_resolved else UNMEASURED


def _unmeasured(population: list[str], **kwargs: Any) -> dict[str, str]:
    """Map each unmeasured country to the side that substituted for it."""
    out: dict[str, str] = {}
    for country in population:
        core_resolved, planning_resolved = _sides(country, **kwargs)
        if core_resolved and planning_resolved:
            continue
        if core_resolved:
            out[country] = "the planning table substituted DEFAULT"
        elif planning_resolved:
            out[country] = "core.calendar substituted its default week"
        else:
            out[country] = "both sides substituted"
    return out


def _live() -> dict[str, Any]:
    return {
        "core_weeks": _WORKING_WEEK,
        "resolve": _get_work_week,
        "default_calendar": WORK_CALENDARS["DEFAULT"],
    }


def test_no_country_resolves_to_the_default_calendar_object() -> None:
    """The premise that makes an identity check a valid proof of resolution.

    Identity says "this lookup found nothing" only while no country is deliberately
    routed to ``DEFAULT``. If one ever is, every check in this file starts reporting
    a real mapping as a substitution, so the premise is asserted rather than assumed.
    """
    routed_to_default = sorted(c for c, key in _CALENDAR_BY_COUNTRY.items() if key == "DEFAULT")

    assert routed_to_default == [], (
        f"these countries are mapped to DEFAULT explicitly: {routed_to_default}. "
        "Identity against WORK_CALENDARS['DEFAULT'] can no longer tell a deliberate mapping "
        "from a fallback, so the resolution checks in this file need a different proof."
    )


def test_every_calendar_carries_a_distinct_label() -> None:
    """Two calendars sharing a label would make any label-based reading ambiguous.

    Nothing in this file reads a label, but a human comparing two answers does, and a
    duplicate label is how a substituted calendar passes for a resolved one on sight.
    """
    seen: dict[str, str] = {}
    collisions = []
    for key, calendar in WORK_CALENDARS.items():
        label = calendar["label"]
        if label in seen:
            collisions.append(f"  {seen[label]} and {key} both present as {label!r}")
        seen[label] = key

    assert collisions == [], "two calendars answer to the same label:\n" + "\n".join(collisions)


def test_a_comparison_is_unmeasured_when_either_registry_substitutes() -> None:
    """The gate. A country may not silently join the population where agreement is meaningless.

    The failure names the countries and the side that substituted, because a gate over
    two registries that disagree today is worthless if it cannot say where.
    """
    population = _population(_WORKING_WEEK, _CALENDAR_BY_COUNTRY)
    unmeasured = _unmeasured(population, **_live())

    newly_unmeasured = sorted(set(unmeasured) - _KNOWN_UNMEASURED)

    assert newly_unmeasured == [], (
        "these countries newly resolve on only one side, so any comparison of the two "
        "registries for them reports agreement without measuring anything:\n"
        + "\n".join(f"  {c}: {unmeasured[c]}" for c in newly_unmeasured)
        + "\nEither give the missing side an entry, or add the country to _KNOWN_UNMEASURED "
        "with a reason. Do not compare the two registries for it in the meantime: a fallback "
        "and a real answer are the same shape."
    )


def test_the_recorded_exposure_has_not_gone_stale() -> None:
    """A ratchet that never tightens stops being a ratchet.

    A country that has since been given its missing entry must leave
    ``_KNOWN_UNMEASURED``, or the set slowly becomes a list of countries nobody has
    re-checked, which is the failure mode this whole area keeps producing.
    """
    population = _population(_WORKING_WEEK, _CALENDAR_BY_COUNTRY)
    unmeasured = _unmeasured(population, **_live())

    now_resolved = sorted(_KNOWN_UNMEASURED - set(unmeasured))

    assert now_resolved == [], (
        f"these are recorded as unmeasured but now resolve on both sides: {now_resolved}. "
        "Remove them from _KNOWN_UNMEASURED so the recorded exposure keeps shrinking."
    )


@pytest.mark.parametrize(
    ("core_has", "planning_has", "expected_side"),
    [
        (True, False, "the planning table substituted DEFAULT"),
        (False, True, "core.calendar substituted its default week"),
        (False, False, "both sides substituted"),
    ],
)
def test_the_classifier_names_the_side_that_substituted(core_has: bool, planning_has: bool, expected_side: str) -> None:
    """Negative control, run in both directions and for the case where neither side answers.

    ``ZZ`` is ISO 3166-1 user-assigned and is asserted absent from both live registries,
    so the control cannot pass by accident on a country that is really there. The
    registries are injected rather than patched, so this proves the classifier without
    touching module state other tests share.
    """
    assert "ZZ" not in _WORKING_WEEK, "the control code must be absent from _WORKING_WEEK"
    assert "ZZ" not in _CALENDAR_BY_COUNTRY, "the control code must be absent from _CALENDAR_BY_COUNTRY"

    default_calendar = {"label": "Standard (Mon-Fri, 8h)", "work_days": {0, 1, 2, 3, 4}}
    resolved_calendar = {"label": "Somewhere (Sun-Thu, 8h)", "work_days": {6, 0, 1, 2, 3}}
    injected = {
        "core_weeks": {"ZZ": frozenset({0, 1, 2, 3, 4})} if core_has else {},
        "resolve": (lambda _c: resolved_calendar) if planning_has else (lambda _c: default_calendar),
        "default_calendar": default_calendar,
    }

    assert _classify("ZZ", **injected) == UNMEASURED
    assert _unmeasured(["ZZ"], **injected) == {"ZZ": expected_side}


def test_a_country_that_resolves_on_both_sides_is_comparable() -> None:
    """The positive control, so the classifier is not simply answering UNMEASURED always.

    Without this, every assertion above would still pass if ``_classify`` were broken to
    return ``UNMEASURED`` unconditionally.
    """
    population = _population(_WORKING_WEEK, _CALENDAR_BY_COUNTRY)
    comparable = [c for c in population if _classify(c, **_live()) == COMPARABLE]

    assert comparable, (
        "no country resolves on both registries, which means the classifier is answering "
        "UNMEASURED for everything and none of the checks above are testing what they claim."
    )
