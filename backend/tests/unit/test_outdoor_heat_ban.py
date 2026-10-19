# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The summer midday outdoor work ban, as data and as a field-time warning.

Saudi Arabia forbids outdoor work in direct sun from 12:00 to 15:00 between
15 June and 15 September. The timesheet does not record whether a line was
outdoors and exempt sectors exist, so the rule warns and never blocks. The
distinguishing cases are the edges: the window's hours, the season's days,
the country, and a UTC instant that is midday only in Riyadh.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.core.validation.rules import FieldTimeOutdoorHeatBan
from app.core.work_restrictions import OUTDOOR_WORK_BANS, ban_overlap, validate_bans

_RIYADH = timezone(timedelta(hours=3))


def _at(day: date, hour: int, minute: int = 0, tz: timezone = _RIYADH) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def test_the_shipped_bans_are_sound() -> None:
    assert validate_bans(OUTDOOR_WORK_BANS) == []
    sa = [ban for ban in OUTDOOR_WORK_BANS if ban.country_code == "SA"]
    assert len(sa) == 1
    assert sa[0].source_url.startswith("https://")


@pytest.mark.parametrize(
    ("start", "end", "hit"),
    [
        (_at(date(2026, 7, 1), 10), _at(date(2026, 7, 1), 16), True),
        (_at(date(2026, 7, 1), 14), _at(date(2026, 7, 1), 18), True),
        (_at(date(2026, 7, 1), 6), _at(date(2026, 7, 1), 12), False),
        (_at(date(2026, 7, 1), 15), _at(date(2026, 7, 1), 20), False),
        (_at(date(2026, 6, 15), 11), _at(date(2026, 6, 15), 13), True),
        (_at(date(2026, 9, 15), 11), _at(date(2026, 9, 15), 13), True),
        (_at(date(2026, 6, 14), 11), _at(date(2026, 6, 14), 13), False),
        (_at(date(2026, 9, 16), 10), _at(date(2026, 9, 16), 16), False),
    ],
    ids=["across", "afternoon", "ends-at-noon", "starts-at-three", "first-day", "last-day", "day-before", "day-after"],
)
def test_the_window_and_the_season_edges(start: datetime, end: datetime, hit: bool) -> None:
    assert (ban_overlap("SA", start, end) is not None) is hit


def test_a_utc_instant_is_read_in_riyadh_time() -> None:
    # 09:30 to 10:30 UTC is 12:30 to 13:30 in Riyadh.
    start = datetime(2026, 7, 1, 9, 30, tzinfo=UTC)
    end = datetime(2026, 7, 1, 10, 30, tzinfo=UTC)
    assert ban_overlap("SA", start, end) is not None
    # 06:00 to 08:00 UTC is 09:00 to 11:00 in Riyadh.
    assert ban_overlap("SA", start.replace(hour=6, minute=0), end.replace(hour=8, minute=0)) is None


def test_another_country_or_missing_times_answer_none() -> None:
    assert ban_overlap("DE", _at(date(2026, 7, 1), 10), _at(date(2026, 7, 1), 16)) is None
    assert ban_overlap(None, _at(date(2026, 7, 1), 10), _at(date(2026, 7, 1), 16)) is None
    assert ban_overlap("SA", None, _at(date(2026, 7, 1), 16)) is None


def test_a_night_shift_into_the_next_midday_is_caught() -> None:
    assert ban_overlap("SA", _at(date(2026, 7, 1), 22), _at(date(2026, 7, 2), 13)) is not None


def _context(country: str | None, start: datetime, end: datetime) -> ValidationContext:
    return ValidationContext(
        data={
            "id": "ts-1",
            "date": "2026-07-01",
            "lines": [{"id": "l-1", "cost_code": "03-300", "start": start, "end": end, "hours": "6"}],
        },
        metadata={"locale": "en", "project_country": country},
    )


async def test_the_rule_warns_and_never_blocks() -> None:
    rule = FieldTimeOutdoorHeatBan()
    assert rule.severity == Severity.WARNING
    results = await rule.validate(_context("SA", _at(date(2026, 7, 1), 10), _at(date(2026, 7, 1), 16)))
    assert len(results) == 1
    assert results[0].passed is False
    assert "12:00" in results[0].message and "15:00" in results[0].message


@pytest.mark.parametrize(
    ("country", "start", "end"),
    [
        ("SA", _at(date(2026, 9, 16), 10), _at(date(2026, 9, 16), 16)),
        ("SA", _at(date(2026, 7, 1), 6), _at(date(2026, 7, 1), 12)),
        ("DE", _at(date(2026, 7, 1), 10), _at(date(2026, 7, 1), 16)),
        (None, _at(date(2026, 7, 1), 10), _at(date(2026, 7, 1), 16)),
    ],
    ids=["after-season", "morning-shift", "germany", "no-country"],
)
async def test_the_rule_stays_silent_outside_the_ban(country: str | None, start: datetime, end: datetime) -> None:
    assert await FieldTimeOutdoorHeatBan().validate(_context(country, start, end)) == []
