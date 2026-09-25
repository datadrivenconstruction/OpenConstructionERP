"""A date-only field keeps the day the user typed, whatever the zones involved.

A punch item's due date lives in a ``TIMESTAMP WITH TIME ZONE`` column. Pydantic
read ``"2026-10-16"`` as the naive ``datetime(2026, 10, 16)``, asyncpg bound that
in the server process's local zone, and a server at UTC+2 stored
``2026-10-15T22:00:00Z``. The API then sent that instant, and a browser in
Toronto printed 15 October while one in Berlin printed 16 October.

These tests pin the convention of :mod:`app.core.calendar_day`: the day is kept
as midnight UTC, sent as ``YYYY-MM-DD``, and a row written the old way reads
back as the day that was meant. The zones are passed explicitly, so the tests
do not depend on the zone of the machine running them.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.calendar_day import (
    calendar_day_iso,
    calendar_day_of,
    calendar_day_utc,
    start_of_today_utc,
)
from app.core.db_types import CalendarDayDateTime

BERLIN = ZoneInfo("Europe/Berlin")
TORONTO = ZoneInfo("America/Toronto")
TOKYO = ZoneInfo("Asia/Tokyo")


# ── The helper ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-16",
        date(2026, 10, 16),
        datetime(2026, 10, 16),  # what Pydantic makes of "2026-10-16"
        "2026-10-16T00:00:00",
        "2026-10-16T00:00:00Z",
        "2026-10-16T00:00:00-04:00",  # a Toronto client that sent its own midnight
        "2026-10-16T00:00:00+09:00",  # a Tokyo client
    ],
)
def test_every_spelling_of_a_day_is_stored_as_midnight_utc_of_that_day(value: object) -> None:
    stored = calendar_day_utc(value, legacy_zone=UTC)
    assert stored == datetime(2026, 10, 16, tzinfo=UTC)
    assert stored is not None and stored.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    ("stored", "server_zone"),
    [
        (datetime(2026, 10, 15, 22, 0, tzinfo=UTC), BERLIN),  # the row the report quotes
        (datetime(2026, 1, 25, 23, 0, tzinfo=UTC), BERLIN),  # the same bug in winter time
        (datetime(2026, 10, 16, 4, 0, tzinfo=UTC), TORONTO),  # a server in Toronto
        (datetime(2026, 10, 15, 15, 0, tzinfo=UTC), TOKYO),  # a server in Tokyo
    ],
)
def test_a_row_stored_at_the_server_zone_midnight_reads_back_as_the_day_meant(
    stored: datetime, server_zone: ZoneInfo
) -> None:
    expected = stored.astimezone(server_zone).date()
    assert calendar_day_of(stored, legacy_zone=server_zone) == expected


@pytest.mark.parametrize("month", range(1, 13))
def test_a_row_written_the_old_way_on_this_machine_reads_back_as_its_day_in_every_season(month: int) -> None:
    # Exactly what asyncpg did with a naive value: read it in the process's
    # local zone, at the offset in force on THAT day. A winter row read back in
    # summer (or the reverse) must not lose a day to the daylight-saving hour.
    # Trivially green on a UTC machine, discriminating on any machine with DST.
    stored = datetime(2026, month, 15).astimezone(UTC)
    assert calendar_day_of(stored) == date(2026, month, 15)


def test_a_genuine_timestamp_keeps_its_utc_day() -> None:
    # A seeded "now + 7 days" is midnight in neither UTC nor the server zone.
    assert calendar_day_of(datetime(2026, 10, 16, 15, 42, tzinfo=UTC), legacy_zone=BERLIN) == date(2026, 10, 16)


def test_the_day_is_sent_as_a_plain_calendar_date() -> None:
    assert calendar_day_iso(datetime(2026, 10, 16, tzinfo=UTC)) == "2026-10-16"
    assert calendar_day_iso(None) is None


def test_an_empty_or_missing_value_is_none() -> None:
    assert calendar_day_utc(None) is None
    assert calendar_day_utc("") is None


def test_rubbish_is_refused() -> None:
    with pytest.raises(ValueError):
        calendar_day_utc("16/10/2026")


def test_today_starts_at_midnight_utc() -> None:
    assert start_of_today_utc(datetime(2026, 10, 16, 23, 59, tzinfo=UTC)) == datetime(2026, 10, 16, tzinfo=UTC)
    # An aware "now" elsewhere is read as its UTC instant.
    toronto_evening = datetime(2026, 10, 16, 21, 0, tzinfo=timezone(timedelta(hours=-4)))
    assert start_of_today_utc(toronto_evening) == datetime(2026, 10, 17, tzinfo=UTC)


# ── The column type ───────────────────────────────────────────────────────────


def test_the_column_never_hands_asyncpg_a_naive_value() -> None:
    # asyncpg reads a naive datetime in the process's local zone. The column
    # has to bind an aware one, and the right one.
    bound = CalendarDayDateTime().process_bind_param(datetime(2026, 10, 16), None)
    assert bound == datetime(2026, 10, 16, tzinfo=UTC)
    assert bound is not None and bound.tzinfo is not None


def test_the_column_binds_a_typed_string_as_that_day() -> None:
    assert CalendarDayDateTime().process_bind_param("2026-10-16", None) == datetime(2026, 10, 16, tzinfo=UTC)


# ── The punch item API ────────────────────────────────────────────────────────


def test_a_typed_due_date_is_held_as_an_aware_midnight_utc() -> None:
    from app.modules.punchlist.schemas import PunchItemCreate, PunchItemUpdate

    created = PunchItemCreate(project_id=uuid.uuid4(), title="Cracked tile", due_date="2026-10-16")
    assert created.due_date == datetime(2026, 10, 16, tzinfo=UTC)
    updated = PunchItemUpdate(due_date="2026-10-16")
    assert updated.due_date == datetime(2026, 10, 16, tzinfo=UTC)


def test_the_response_sends_the_due_date_as_a_calendar_date() -> None:
    from app.modules.punchlist.schemas import PunchItemResponse

    now = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    response = PunchItemResponse(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        title="Cracked tile",
        due_date=datetime(2026, 10, 16, tzinfo=UTC),
        created_at=now,
        updated_at=now,
    )
    body = json.loads(response.model_dump_json())
    assert body["due_date"] == "2026-10-16"
    # A true timestamp stays a timestamp.
    assert body["created_at"].startswith("2026-09-23T12:00:00")
