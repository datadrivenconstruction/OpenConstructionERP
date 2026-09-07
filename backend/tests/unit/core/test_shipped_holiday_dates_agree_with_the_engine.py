"""The holidays we ship as data and the holidays we compute must be one answer.

``work_calendars.json`` and ``app.core.calendar`` are two independently edited
sources for the same fact, and nothing bound them together. Both defects this
module pins were invisible for that reason:

* Sports Day was hardcoded to 14 October in ``_holidays_jp`` while the seed file
  shipped the correct second Monday. The engine and the data disagreed every
  year in which 14 October is not itself a Monday, and no test compared them.
* India's seeded Holi and Diwali for 2026 were 13 and 2 days away from the
  curated ``_HINDU_HOLIDAYS`` rows the engine serves, so the same calendar
  answered differently depending on which source the caller reached.

``test_seeded_work_week_survives_its_year`` says in its own docstring that it
deliberately asserts no holidays. This module is the other half of that split,
and it asserts only the countries whose data has been checked against an
external almanac, because a wider sweep would pin dates nobody has verified.

The Monday rule is recomputed here by walking October rather than by calling
``_nth_weekday``. Reusing the engine's own helper to check the engine would pass
whatever the helper did, including nothing.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.core.calendar import _HINDU_HOLIDAYS, _get_holidays

SEED_PATH = (
    Path(__file__).resolve().parents[3] / "app" / "modules" / "i18n_foundation" / "seed_data" / "work_calendars.json"
)

#: The span the Japanese assertion covers. Printed in the failure messages so a
#: narrowed population cannot be mistaken for a passing one.
JP_YEARS = range(2026, 2038)


def _seed_rows(country_code: str) -> dict[str, date]:
    """Holiday name to date, for one country's shipped calendar."""
    calendars = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    row = next(c for c in calendars if c["country_code"] == country_code)
    return {e["name"]["en"]: date.fromisoformat(e["date"]) for e in row["exceptions"]}


def _second_monday_of_october(year: int) -> date:
    """Walk October and take the second Monday, without the engine's helper."""
    mondays = []
    day = date(year, 10, 1)
    while day.month == 10:
        if day.weekday() == 0:
            mondays.append(day)
        day += timedelta(days=1)
    return mondays[1]


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
    """The shipped 2026 row and the computed 2026 answer are the same date."""
    seeded = _seed_rows("JP")["Sports Day"]
    assert seeded == _second_monday_of_october(2026) == date(2026, 10, 12)
    assert seeded in _get_holidays("JP", 2026)


@pytest.mark.parametrize("festival", ["Holi", "Diwali"])
def test_indias_seeded_lunisolar_dates_match_the_curated_table(festival: str) -> None:
    """The seed file and ``_HINDU_HOLIDAYS`` are one calendar, not two.

    These are the only two Indian festivals the engine itself computes, so they
    are the only two where a seed row can be checked against something in the
    tree rather than against a date this test would have to assert on its own.
    """
    month, day = _HINDU_HOLIDAYS[2026][festival.lower()]
    curated = date(2026, month, day)
    seeded = _seed_rows("IN")[festival]

    assert seeded == curated, (
        f"{festival} 2026 is {seeded} in work_calendars.json and {curated} in "
        f"_HINDU_HOLIDAYS, a gap of {abs((seeded - curated).days)} days"
    )
    assert seeded in _get_holidays("IN", 2026)
