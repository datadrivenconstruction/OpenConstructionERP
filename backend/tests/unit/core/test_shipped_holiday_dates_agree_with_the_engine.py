"""Japan's Sports Day moves with the Happy Monday System, and must be computed.

``_holidays_jp`` hardcoded 14 October under a comment that stated the
second-Monday rule the code did not implement. The seed file shipped the correct
date all along, so the engine and the data disagreed in every year 14 October is
not itself a Monday, which is 11 of 2026 to 2037, and nothing compared them.

Scope. Only Japan is here. The lunisolar half of the same problem, India's
seeded festivals disagreeing with the engine's curated table, belongs in
``tests/unit/test_seeded_lunisolar_offsets.py``, which already owns seeded
festival dates and was widened to cover India rather than duplicated here. A
Happy Monday holiday is not lunisolar and has no offset to measure, so it would
not have fitted that file's shape.

``test_seeded_work_week_survives_its_year`` says in its own docstring that it
deliberately asserts no holidays at all. This module is part of the other half
of that split.

The Monday rule is recomputed here by walking October rather than by calling
``_nth_weekday``. Reusing the engine's own helper to check the engine would pass
whatever the helper did, including nothing.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.core.calendar import _get_holidays

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
    """The shipped 2026 row and the computed 2026 answer are the same date.

    This is the assertion that was missing. The seed said 2026-10-12 and the
    engine said 2026-10-14, and no test put the two side by side.
    """
    seeded = _seed_rows("JP")["Sports Day"]
    assert seeded == _second_monday_of_october(2026) == date(2026, 10, 12)
    assert seeded in _get_holidays("JP", 2026)
