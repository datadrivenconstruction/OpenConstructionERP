"""Every shipped calendar is compared against the engine that computes it.

We ship holiday dates twice. ``app/core/calendar.py`` computes them, and
``i18n_foundation/seed_data/work_calendars.json`` states them as data for 36
countries. Until this file existed, nothing put the two side by side, and the
suite was green while they disagreed.

That is not hypothetical, it is how this module was written. Japan's Sports Day
was hardcoded to 14 October in the engine while the seed carried the correct
second Monday, and the two differed in 11 of the 12 years from 2026. India's
seeded festivals contradicted the engine's own curated table by up to thirteen
days. Both shipped. Both were invisible, because every calendar test we owned
looked at one source or the other and never at the pair.

**What this file asserts, and why it is worth asserting even without an
almanac.** A disagreement between two things we ship is a defect regardless of
which side is wrong, because at most one of them can be right and both are
reachable. So the primary check needs no external authority at all: for every
country the engine can compute, the seeded date set must equal the computed
one, and where it does not, the exact difference is written down here with a
reason and a named authoritative side.

**Why the differences are recorded rather than tolerated.** ``_DIVERGENCES``
holds the measured difference exactly, not a permission to differ. A country
listed here fails this test if it starts to differ in a NEW way, and it also
fails if somebody FIXES the difference, because the recorded set no longer
matches what is measured. That second direction is the point. A blanket
exemption is a hole that widens quietly; a recorded set is a ratchet that has
to be edited deliberately in either direction.

**Which side is authoritative** is stated per entry, because "these disagree"
is not actionable and "the seed is right and the engine is knowingly narrower"
is. Three of the entries are marked as suspected defects that this file
deliberately does not adjudicate, because fixing them changes date arithmetic
for real users and that is a decision to take explicitly rather than as a side
effect of writing a test.

**The denominator is printed.** 36 countries are seeded, 19 are bound to an
engine function, 17 are unbound. A gate whose population is invisible can be
satisfied by narrowing it, so the unbound countries are named in the output
rather than silently absent from it, and floors below stop the bound set from
being trimmed to make a failure go away.

Scope note. The lunisolar half of this problem, India's seeded festivals
measured against their own anchors, belongs to
``tests/unit/test_seeded_lunisolar_offsets.py``, which already owned seeded
festival offsets and was widened rather than duplicated. This file owns the
set-equality question for every country.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.core.calendar import _HOLIDAY_FUNCS, _equinox_day, _get_holidays

SEED_PATH = (
    Path(__file__).resolve().parents[3] / "app" / "modules" / "i18n_foundation" / "seed_data" / "work_calendars.json"
)

#: The only year the seed file carries. Asserted rather than assumed, because a
#: second year appearing would make every set comparison below meaningless
#: without failing anything.
SEED_YEAR = 2026

#: The span the Japanese Happy Monday assertion covers. Printed in the failure
#: messages so a narrowed population cannot be mistaken for a passing one.
JP_YEARS = range(2026, 2038)


# Which source to believe when the two differ. The string is what a reader sees
# in a failure, so it says what to do, not merely that something is off.
SEED_IS_RIGHT = "seed authoritative: the engine is knowingly narrower here"
ENGINE_SUSPECT = "suspected ENGINE defect, deliberately not adjudicated by this test"
SEED_SUSPECT = "suspected SEED defect, deliberately not adjudicated by this test"
UNADJUDICATED = "neither side checked against an external authority"


@dataclass(frozen=True)
class Divergence:
    """The exact, measured difference between one country's two sources."""

    side: str
    why: str
    seed_only: frozenset[str] = field(default_factory=frozenset)
    engine_only: frozenset[str] = field(default_factory=frozenset)


#: Measured 2026 differences, one entry per bound country that has any. A
#: country that agrees exactly is absent from this table and must stay that way.
_DIVERGENCES: dict[str, Divergence] = {
    "AE": Divergence(
        side=UNADJUDICATED,
        why=(
            "four separate causes in one country. (a) Eid al-Fitr: the seed starts it on 19 March "
            "and the engine on 20 March. The astronomical new moon is 2026-03-19 01:24 UTC, so a "
            "civil 19 March would require the Shawwal crescent to have been sighted on the evening "
            "of 18 March, about ten hours BEFORE conjunction, which no sighting criterion permits. "
            "The seed's own India row says 20 March for the same event, and India never sights "
            "earlier than the Gulf. This one looks like a seed defect and is reported, not fixed. "
            "(b) Eid al-Adha: the engine runs a four-day span 27-30 May and no Arafat Day; the seed "
            "runs Arafat on the 26th and three Eid days. Both yield four non-working days, shifted "
            "by one. _GCC_EID_SPANS documents Eid length as annually announced policy. "
            "(c) Islamic New Year and (d) the Prophet's Birthday: the seed is one day later than "
            "the tabular converter, which is the ordinary direction for a sighted calendar. "
            "Commemoration Day differs by one day and neither side was checked against the law."
        ),
        seed_only=frozenset({"2026-03-19", "2026-05-26", "2026-06-17", "2026-08-26", "2026-11-30"}),
        engine_only=frozenset({"2026-03-22", "2026-05-30", "2026-06-16", "2026-08-25", "2026-12-01"}),
    ),
    "AT": Divergence(
        side=SEED_IS_RIGHT,
        why=(
            "_HOLIDAY_FUNCS maps AT to _holidays_de under the comment that Austrian federal "
            "holidays closely mirror Germany's. They do not mirror it closely enough: the engine "
            "hands Austria two German holidays it does not observe, Good Friday and German Unity "
            "Day on 3 October, and drops six that it does, including the Austrian National Day on "
            "26 October. The seed is the better source for Austria and the engine is wrong here by "
            "an approximation it declares in a comment."
        ),
        seed_only=frozenset({"2026-01-06", "2026-06-04", "2026-08-15", "2026-10-26", "2026-11-01", "2026-12-08"}),
        engine_only=frozenset({"2026-04-03", "2026-10-03"}),
    ),
    "BH": Divergence(
        side=UNADJUDICATED,
        why="the Gulf family described under AE: Eid al-Fitr anchor, Eid al-Adha span and Arafat, and two sighted dates.",
        seed_only=frozenset({"2026-03-19", "2026-05-26", "2026-06-17", "2026-08-26"}),
        engine_only=frozenset({"2026-03-22", "2026-05-30", "2026-06-16", "2026-08-25"}),
    ),
    "BR": Divergence(
        side=SEED_IS_RIGHT,
        why=(
            "Corpus Christi is a ponto facultativo rather than a national holiday under Lei "
            "9.093/95, so the engine leaves it out and the seed ships it. The seed is the fuller "
            "answer for an employer calendar; the engine's narrower one is deliberate."
        ),
        seed_only=frozenset({"2026-06-04"}),
    ),
    "CA": Divergence(
        side=SEED_IS_RIGHT,
        why=(
            "Family Day and the August civic holiday are provincial. _holidays_ca excludes them on "
            "purpose and says so at length, preferring an accurate federal list to a fuller one "
            "that is wrong in seven provinces. The seed carries the common provincial pair."
        ),
        seed_only=frozenset({"2026-02-16", "2026-08-03"}),
    ),
    "CH": Divergence(
        side=SEED_IS_RIGHT,
        why=(
            "the engine's entry for Switzerland is a three-date lambda marked 'simplified' in "
            "_HOLIDAY_FUNCS. The seed carries the six further days most cantons observe. Nothing "
            "here is in dispute; the engine simply does not try."
        ),
        seed_only=frozenset({"2026-01-02", "2026-04-03", "2026-04-06", "2026-05-14", "2026-05-25", "2026-12-26"}),
    ),
    "CN": Divergence(
        side=ENGINE_SUSPECT,
        why=(
            "two unrelated causes. The seed carries Chinese New Year days 4 to 7, which the engine "
            "models as a shorter statutory block, and that part is a policy split. The other "
            "direction is not: the engine computes 1 AND 2 May while the seed carries only 1 May. "
            "Labour Day became two statutory days in the 2025 State Council revision, so the seed "
            "looks a day short. Reported, not fixed, because it moves a working day."
        ),
        seed_only=frozenset({"2026-02-20", "2026-02-21", "2026-02-22", "2026-02-23"}),
        engine_only=frozenset({"2026-05-02"}),
    ),
    "GB": Divergence(
        side=UNADJUDICATED,
        why=(
            "Boxing Day 2026 falls on a Saturday. The engine reports the 26th itself and the seed "
            "reports the substitute Monday on the 28th. Deliberately not adjudicated here: a "
            "sibling finding about UK weekend substitution was refuted by its own probe, so this "
            "records the observation without reopening that question."
        ),
        seed_only=frozenset({"2026-12-28"}),
        engine_only=frozenset({"2026-12-26"}),
    ),
    "IN": Divergence(
        side=SEED_IS_RIGHT,
        why=(
            "_holidays_in computes the three national holidays plus Holi and Diwali from the "
            "curated table and states that regional and religious festivals are out of scope. The "
            "seed is a fuller employer calendar. The dates the two DO share were reconciled "
            "against an almanac and are pinned by tests/unit/test_seeded_lunisolar_offsets.py."
        ),
        seed_only=frozenset(
            {
                "2026-02-15",
                "2026-03-20",
                "2026-03-26",
                "2026-04-03",
                "2026-04-14",
                "2026-05-01",
                "2026-05-27",
                "2026-08-26",
                "2026-10-20",
                "2026-11-24",
            }
        ),
    ),
    "JP": Divergence(
        side=ENGINE_SUSPECT,
        why=(
            "two rules the engine does not implement, and the seed has both dates right. "
            "3 May 2026 is a Sunday and the 4th and 5th are already holidays, so Article 3(2) of "
            "the Act on National Holidays pushes the substitute to 6 May; the engine's _sub helper "
            "returns only {d, d+1}, which is a day already taken, so it adds nothing. And 22 "
            "September is trapped between Respect for the Aged Day and the equinox, which makes it "
            "a Citizen's Holiday under Article 3(3); the engine has no sandwich rule. Reported, "
            "not fixed: both add non-working days."
        ),
        seed_only=frozenset({"2026-05-06", "2026-09-22"}),
    ),
    "KW": Divergence(
        side=UNADJUDICATED,
        why="the Gulf family described under AE: Eid al-Fitr anchor, Eid al-Adha span and Arafat, and two sighted dates.",
        seed_only=frozenset({"2026-03-19", "2026-05-26", "2026-06-17", "2026-08-26"}),
        engine_only=frozenset({"2026-03-22", "2026-05-30", "2026-06-16", "2026-08-25"}),
    ),
    "OM": Divergence(
        side=UNADJUDICATED,
        why="the Gulf family described under AE: Eid al-Fitr anchor, Eid al-Adha span and Arafat, and two sighted dates.",
        seed_only=frozenset({"2026-03-19", "2026-05-26", "2026-06-17", "2026-08-26"}),
        engine_only=frozenset({"2026-03-22", "2026-05-30", "2026-06-16", "2026-08-25"}),
    ),
    "QA": Divergence(
        side=UNADJUDICATED,
        why=(
            "the Gulf family described under AE, minus the two sighted dates: Qatar's seeded row "
            "carries neither the Islamic New Year nor the Prophet's Birthday, so only the Eid "
            "al-Fitr anchor and the Arafat/Eid al-Adha span differ."
        ),
        seed_only=frozenset({"2026-03-19", "2026-05-26"}),
        engine_only=frozenset({"2026-03-22", "2026-05-30"}),
    ),
    "RU": Divergence(
        side=ENGINE_SUSPECT,
        why=(
            "8 March and 9 May 2026 both fall on a Sunday, and Article 112 of the Labour Code "
            "moves a holiday falling on a rest day to the next working day. The seed carries both "
            "substitutes, on 9 March and 11 May, and the engine computes neither. Reported, not "
            "fixed: it adds two non-working days."
        ),
        seed_only=frozenset({"2026-03-09", "2026-05-11"}),
    ),
    "SA": Divergence(
        side=UNADJUDICATED,
        why=(
            "the Gulf family described under AE. Saudi Arabia differs from its neighbours in the "
            "split: the seed gives Eid al-Fitr four days from the 19th and the engine three from "
            "the 20th, and _holidays_sa's docstring already records that one shared span is too "
            "short for Saudi Arabia, where both Eids routinely run longer."
        ),
        seed_only=frozenset({"2026-03-19", "2026-05-26"}),
        engine_only=frozenset({"2026-05-30"}),
    ),
}

#: Floors. These stop a future failure from being resolved by trimming the
#: population instead of the defect. Measured, not guessed: 36 seeded countries,
#: of which 19 have an engine function.
_MIN_SEEDED = 36
_MIN_BOUND = 19


def _seed() -> list[dict]:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def _seed_dates(country_code: str) -> dict[str, str]:
    """ISO date to English name, for one country's shipped calendar."""
    row = next(c for c in _seed() if c["country_code"] == country_code)
    return {e["date"]: e["name"]["en"] for e in row["exceptions"]}


def _seed_names(country_code: str) -> dict[str, date]:
    """English name to date. The inverse view, for the label assertions."""
    row = next(c for c in _seed() if c["country_code"] == country_code)
    return {e["name"]["en"]: date.fromisoformat(e["date"]) for e in row["exceptions"]}


def _seeded_countries() -> list[str]:
    return sorted({c["country_code"] for c in _seed()})


SEEDED = _seeded_countries()
BOUND = [c for c in SEEDED if c in _HOLIDAY_FUNCS]
UNBOUND = [c for c in SEEDED if c not in _HOLIDAY_FUNCS]


def _measure(country_code: str) -> tuple[frozenset[str], frozenset[str]]:
    """``(dates only the seed has, dates only the engine has)`` for SEED_YEAR."""
    seeded = set(_seed_dates(country_code))
    computed = {d.isoformat() for d in _get_holidays(country_code, SEED_YEAR)}
    return frozenset(seeded - computed), frozenset(computed - seeded)


def _second_monday_of_october(year: int) -> date:
    """Walk October and take the second Monday, without the engine's helper.

    Reusing ``_nth_weekday`` to check the engine would pass whatever that helper
    did, including nothing.
    """
    mondays = []
    day = date(year, 10, 1)
    while day.month == 10:
        if day.weekday() == 0:
            mondays.append(day)
        day += timedelta(days=1)
    return mondays[1]


# --------------------------------------------------------------------------
# Tier 1: the seed and the engine must agree, or differ exactly as recorded.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("code", BOUND)
def test_the_seed_and_the_engine_agree(code: str) -> None:
    """Two things we ship must say the same thing about the same country."""
    seed_only, engine_only = _measure(code)
    recorded = _DIVERGENCES.get(code, Divergence(side="", why="none: these two sources agree exactly"))

    unexpected_seed = seed_only - recorded.seed_only
    unexpected_engine = engine_only - recorded.engine_only
    repaired_seed = recorded.seed_only - seed_only
    repaired_engine = recorded.engine_only - engine_only

    assert not (unexpected_seed or unexpected_engine), (
        f"{code}: the shipped calendar and the engine have started to disagree in a way "
        f"nothing recorded. Dates only in the seed: {sorted(unexpected_seed)}. Dates only "
        f"from the engine: {sorted(unexpected_engine)}. At most one source can be right and "
        f"both are reachable, so this is a defect whichever side moved. Fix it, or record it "
        f"in _DIVERGENCES with the reason and the authoritative side. "
        f"(population: {len(BOUND)} bound of {len(SEEDED)} seeded)"
    )
    assert not (repaired_seed or repaired_engine), (
        f"{code}: a recorded divergence is gone, which is good news that this test has to "
        f"fail to deliver. Dates the seed no longer holds alone: {sorted(repaired_seed)}. "
        f"Dates the engine no longer holds alone: {sorted(repaired_engine)}. Update or delete "
        f"the _DIVERGENCES entry so the record matches the tree. Recorded reason was: "
        f"{recorded.why}"
    )


def test_the_countries_that_agree_are_named() -> None:
    """The four clean countries, pinned against the easy escape from the test above.

    This asserts on ``_DIVERGENCES`` rather than on the data, deliberately. When
    the agreement check fails, the cheap way out is to add an entry here and
    move on, and that would be invisible: the suite goes green and one more
    country stops being compared. Naming the four countries that carry no entry
    means growing the table is a change somebody has to make on purpose.
    """
    agreeing = sorted(c for c in BOUND if c not in _DIVERGENCES)
    print(f"seed equals engine exactly for {len(agreeing)} of {len(BOUND)} bound countries: {agreeing}")
    assert agreeing == ["BG", "DE", "NG", "US"], (
        f"the set of countries whose two sources agree exactly has changed, now {agreeing}. "
        f"If a country left this list it started disagreeing; if one joined, delete its "
        f"_DIVERGENCES entry."
    )


def test_no_recorded_divergence_is_stale() -> None:
    """An entry for a country we no longer ship, or no longer compute, is a lie."""
    orphans = sorted(set(_DIVERGENCES) - set(BOUND))
    assert not orphans, (
        f"_DIVERGENCES has entries for {orphans}, which are not both seeded and bound to an "
        f"engine function. A recorded divergence that nothing measures is worse than none, "
        f"because it reads as coverage."
    )


def test_every_divergence_names_a_side_and_a_reason() -> None:
    """A bare exemption is a hole; a reasoned one is a decision someone can revisit."""
    for code, record in sorted(_DIVERGENCES.items()):
        assert record.side in {SEED_IS_RIGHT, ENGINE_SUSPECT, SEED_SUSPECT, UNADJUDICATED}, (
            f"{code} has no recognised authoritative side"
        )
        assert len(record.why) > 60, f"{code} has no real reason recorded, only {record.why!r}"
        assert record.seed_only or record.engine_only, (
            f"{code} is recorded as divergent but names no dates, so it exempts everything"
        )


# --------------------------------------------------------------------------
# Tier 2: countries the engine cannot compute are named, not skipped.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("code", UNBOUND)
def test_an_unbound_country_is_visible_rather_than_absent(code: str) -> None:
    """A seeded calendar with no engine function is unchecked, and says so.

    This is the honest half of the population. Seventeen countries ship holiday
    dates that nothing computes, so nothing can contradict them. That is a real
    limit of this gate and it is asserted rather than left to inference: the day
    somebody adds an engine function for one of these, this test fails and
    forces the country into tier 1 where it will actually be compared.
    """
    assert code not in _HOLIDAY_FUNCS, (
        f"{code} now has an engine function, so it is no longer unbound. Move it into the "
        f"tier 1 population by rerunning this module: BOUND and UNBOUND are computed from "
        f"_HOLIDAY_FUNCS, so this failure means the recorded expectation below is stale."
    )
    seeded = _seed_dates(code)
    assert seeded, f"{code} ships an empty calendar, which no source can be checked against"


def test_the_unbound_population_is_printed_and_bounded() -> None:
    """Name them in the output. A country absent from a report is not covered by it."""
    print(
        f"seed vs engine population: {len(SEEDED)} countries seeded, {len(BOUND)} bound to an "
        f"engine function and compared, {len(UNBOUND)} unbound and NOT compared."
    )
    print(f"  bound   ({len(BOUND)}): {BOUND}")
    print(f"  unbound ({len(UNBOUND)}): {UNBOUND}")
    print(f"  of the bound, {len(BOUND) - len(_DIVERGENCES)} agree exactly and {len(_DIVERGENCES)} differ as recorded")
    for code in UNBOUND:
        print(f"    {code}: {len(_seed_dates(code))} seeded dates, unbound because _HOLIDAY_FUNCS has no entry")

    assert set(SEEDED) == set(BOUND) | set(UNBOUND), "a seeded country fell out of both halves of the population"
    assert not set(BOUND) & set(UNBOUND), "a country cannot be both bound and unbound"
    assert len(SEEDED) >= _MIN_SEEDED, (
        f"only {len(SEEDED)} seeded countries, was {_MIN_SEEDED}. If a calendar was removed on "
        f"purpose, lower the floor deliberately; do not let the denominator shrink quietly."
    )
    assert len(BOUND) >= _MIN_BOUND, (
        f"only {len(BOUND)} countries are actually compared, was {_MIN_BOUND}. This gate can be "
        f"satisfied by narrowing it, so the width is asserted too."
    )


def test_the_seed_carries_exactly_one_year_and_one_kind_of_entry() -> None:
    """Both assumptions every set comparison above rests on."""
    years, kinds, total = set(), set(), 0
    for row in _seed():
        for entry in row["exceptions"]:
            years.add(entry["date"][:4])
            kinds.add(entry["type"])
            total += 1
    print(f"seed entries: {total} across {len(SEEDED)} countries, years {sorted(years)}, types {sorted(kinds)}")
    assert years == {str(SEED_YEAR)}, (
        f"the seed now carries {sorted(years)}. Every comparison in this file is against "
        f"{SEED_YEAR} only, so another year would ship unchecked while the suite stayed green."
    )
    assert kinds == {"public_holiday"}, (
        f"the seed now carries entry types {sorted(kinds)}. This file treats every exception as "
        f"a holiday; a non-holiday entry would be compared against the engine as though it were one."
    )


# --------------------------------------------------------------------------
# Tier 3: rules that are genuinely computable, checked against the rule.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("year", JP_YEARS)
def test_japanese_sports_day_is_the_second_monday_of_october(year: int) -> None:
    """Sports Day moves with the Happy Monday System, like its three neighbours."""
    expected = _second_monday_of_october(year)
    holidays = _get_holidays("JP", year)

    assert expected in holidays, (
        f"Sports Day {expected} missing from Japan {year} "
        f"(population: {len(JP_YEARS)} years, {JP_YEARS.start}-{JP_YEARS.stop - 1})"
    )
    assert expected.weekday() == 0, f"{expected} is not a Monday"

    # The old hardcoded date. It is a holiday only in the years it is the
    # second Monday, so this is what actually separates the rule from the stub.
    hardcoded = date(year, 10, 14)
    if hardcoded != expected:
        assert hardcoded not in holidays, (
            f"14 October {year} is a {hardcoded.strftime('%A')}, not the second Monday "
            f"({expected}), yet Japan's holiday set still contains it"
        )


def test_the_hardcoded_sports_day_would_have_been_wrong_in_most_of_these_years() -> None:
    """The span is worth asserting over: a fixed date is right only rarely.

    Without this, a future author could narrow ``JP_YEARS`` to a single year in
    which 14 October happens to be a Monday and keep the suite green.
    """
    wrong = [y for y in JP_YEARS if date(y, 10, 14) != _second_monday_of_october(y)]
    assert len(wrong) >= len(JP_YEARS) - 2, (
        f"only {len(wrong)} of {len(JP_YEARS)} years distinguish the fixed date "
        f"from the second-Monday rule; the span no longer tests anything"
    )


def test_japans_seeded_sports_day_matches_the_engine() -> None:
    """The shipped 2026 row and the computed 2026 answer are the same date.

    This is the assertion that was missing. The seed said 2026-10-12 and the
    engine said 2026-10-14, and no test put the two side by side.
    """
    seeded = _seed_names("JP")["Sports Day"]
    expected = _second_monday_of_october(2026)
    assert seeded == expected == date(2026, 10, 12), (
        f"the seed puts Sports Day 2026 on {seeded}, the second Monday of October is {expected}. "
        f"The engine hardcoded 14 October while the seed carried the right date, and this is the "
        f"assertion that was missing when they disagreed."
    )
    assert seeded in _get_holidays("JP", 2026), (
        f"the engine does not compute {seeded} as a Japanese holiday, so the two sources have parted again"
    )


def test_the_equinox_label_is_on_the_equinox() -> None:
    """Autumnal Equinox Day is an astronomical instant, not a choice of day.

    The seed shipped this name on 22 September 2026 and Citizen's Holiday on the
    23rd, which is backwards. Nothing caught it, because the pair of dates was
    right and every gate we own compares dates rather than names.
    """
    seeded = _seed_names("JP")["Autumnal Equinox Day"]
    computed = date(2026, 9, _equinox_day(2026, spring=False))
    assert seeded == computed == date(2026, 9, 23), (
        f"the seed calls {seeded} the autumnal equinox, but the equinox falls on {computed}. "
        f"The instant is 2026-09-23 09:05 JST and the engine's own approximation agrees."
    )


def test_citizens_holiday_is_sandwiched_between_two_holidays() -> None:
    """A Citizen's Holiday that is not sandwiched is not a Citizen's Holiday.

    It is not a named observance. Article 3(3) turns an ordinary day trapped
    between two national holidays into one, so the rule fully determines the
    date and the label can be checked against it with nothing external.
    """
    seeded = _seed_dates("JP")
    citizens = [date.fromisoformat(d) for d, name in seeded.items() if name == "Citizen's Holiday"]
    assert citizens, "Japan's seeded calendar no longer names a Citizen's Holiday"

    for day in citizens:
        before = (day - timedelta(days=1)).isoformat()
        after = (day + timedelta(days=1)).isoformat()
        assert before in seeded and after in seeded, (
            f"{day} is labelled Citizen's Holiday but is not between two holidays: "
            f"{before} is {seeded.get(before, 'an ordinary day')} and "
            f"{after} is {seeded.get(after, 'an ordinary day')}. The label is only ever "
            f"produced by the sandwich rule, so an unsandwiched one is on the wrong date."
        )
        assert day.weekday() < 5, f"{day} is a weekend, so no working day was ever trapped"


# --------------------------------------------------------------------------
# Controls: this gate must fail on the defects it was written for.
# --------------------------------------------------------------------------


def test_the_gate_catches_a_seed_date_that_drifts() -> None:
    """Red in the other direction, using the exact shape of the Japanese defect."""
    seed_only = frozenset({"2026-10-14"})
    recorded = _DIVERGENCES["JP"]
    unexpected = seed_only - recorded.seed_only
    assert unexpected == frozenset({"2026-10-14"}), (
        "a date appearing in the seed and not in the engine must be reported as unexpected "
        "unless it is recorded; if this passes trivially the tier 1 assertion is inert"
    )


def test_the_gate_catches_a_repaired_divergence() -> None:
    """Fixing a recorded difference must also fail, or the record rots silently."""
    recorded = _DIVERGENCES["RU"]
    still_diverging = frozenset({"2026-03-09"})
    repaired = recorded.seed_only - still_diverging
    assert repaired == frozenset({"2026-05-11"}), (
        "when a recorded divergence is fixed the ratchet must notice, otherwise _DIVERGENCES "
        "accumulates entries describing a tree that has moved on"
    )


def test_the_transposed_japanese_labels_would_be_caught() -> None:
    """The exact strings that shipped, run through the equinox rule."""
    shipped_equinox = date(2026, 9, 22)
    assert shipped_equinox != date(2026, 9, _equinox_day(2026, spring=False))
