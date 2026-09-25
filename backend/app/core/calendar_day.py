# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Calendar days kept in timestamp columns.

Some date-only fields (a punch item's due date, for one) live in a
``TIMESTAMP WITH TIME ZONE`` column. A calendar day has no time and no zone,
so a timestamp can only carry it by convention, and the convention here is
**midnight UTC of that day**. Everything that writes or reads such a field
goes through this module so the convention is applied in one place.

Why it matters. Pydantic turns ``"2026-10-16"`` into the *naive*
``datetime(2026, 10, 16, 0, 0)``, and asyncpg binds a naive value to a
``TIMESTAMPTZ`` parameter with ``obj.astimezone(utc)``, which reads it in the
*server process's* local zone. On a server at UTC+2 the day the user typed was
therefore stored as ``2026-10-15T22:00:00Z``, and every browser west of UTC+2
printed the 15th. A browser in Toronto printed the 15th even on a UTC server,
because the API sent a timestamp and the browser rendered it in its own zone.

The two halves of the fix:

* **Write**: :func:`calendar_day_utc` turns whatever arrives (a date, a
  ``YYYY-MM-DD`` string, a naive or aware datetime) into an aware midnight-UTC
  datetime, so asyncpg never sees a naive value.
* **Read**: :func:`calendar_day_of` gives back the day, and the API sends it
  as ``YYYY-MM-DD`` (see :data:`CalendarDay`), which the frontend's shared
  formatters already render without a zone shift.

Rows written before the fix. A row stored at *local midnight of the server
zone* (``22:00Z`` for a server at UTC+2) is recognised by exactly that
signature: converted to the server zone it reads 00:00. Such a row reads back
as the local day. A stored instant that is midnight in neither UTC nor the
server zone is a genuine timestamp (a seeded ``now() + 7 days``), and its UTC
day is taken. This is a reading rule, not a data repair: nothing is rewritten.
It assumes the server zone has not changed since the row was written; the
daylight-saving offset of the row's own date is applied.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, tzinfo
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse(value: object) -> date | datetime:
    if isinstance(value, datetime | date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if _DATE_ONLY_RE.match(text):
            return date.fromisoformat(text)
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    raise ValueError(f"not a calendar day: {value!r}")


def calendar_day_of(value: object, *, legacy_zone: tzinfo | None = None) -> date | None:
    """Return the calendar day a date-only field holds, or None.

    Args:
        value: ``None``, a :class:`date`, a ``YYYY-MM-DD`` or ISO-8601 string, or
            a :class:`datetime`.
        legacy_zone: The zone a row written before the fix was read in. Defaults
            to the process's local zone; tests pass one explicitly.

    Rules, in order:

    * a date or ``YYYY-MM-DD`` string is that day;
    * a naive datetime is its own wall-clock day (what Pydantic makes of a
      ``YYYY-MM-DD`` payload, and what SQLite hands back);
    * an aware datetime with a non-zero offset is its wall-clock day in that
      offset (the sender said which day it meant);
    * an aware UTC instant at 00:00 is that UTC day (the stored convention);
    * an aware UTC instant that is 00:00 in ``legacy_zone`` is that local day
      (a row written before the fix);
    * any other instant is its UTC day.
    """
    if value is None or value == "":
        return None
    parsed = _parse(value)
    if not isinstance(parsed, datetime):
        return parsed
    offset = parsed.utcoffset()
    if offset is None:
        return parsed.date()
    if offset:
        return parsed.date()
    utc_value = parsed.astimezone(UTC)
    if utc_value.time() == time(0):
        return utc_value.date()
    # asyncpg read a naive value at the local offset in force on THAT day, so
    # the default converts per instant (``astimezone()`` with no argument). A
    # fixed offset taken from "now" would lose a day to daylight saving: a
    # winter row read back in summer misses midnight by the DST hour.
    local = utc_value.astimezone(legacy_zone) if legacy_zone is not None else utc_value.astimezone()
    if local.time() == time(0):
        return local.date()
    return utc_value.date()


def calendar_day_utc(value: object, *, legacy_zone: tzinfo | None = None) -> datetime | None:
    """Return the stored form of a calendar day: midnight UTC of that day, aware."""
    day = calendar_day_of(value, legacy_zone=legacy_zone)
    if day is None:
        return None
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def calendar_day_iso(value: object) -> str | None:
    """Return the calendar day as ``YYYY-MM-DD``, or None. For exports and reports."""
    day = calendar_day_of(value)
    return day.isoformat() if day is not None else None


def start_of_today_utc(now: datetime | None = None) -> datetime:
    """Midnight UTC of today: a calendar day is overdue once it is before this.

    Matches the frontend's ``isDateOnlyPast``: a day stops being current the
    day after it, not at the first instant of it.
    """
    current = now or datetime.now(UTC)
    current = current.astimezone(UTC) if current.tzinfo else current.replace(tzinfo=UTC)
    return datetime(current.year, current.month, current.day, tzinfo=UTC)


def _validate(value: Any) -> datetime | None:
    try:
        return calendar_day_utc(value)
    except ValueError as exc:
        raise ValueError("Expected a calendar date in the form YYYY-MM-DD") from exc


#: A date-only API field kept in a timestamp column.
#:
#: Accepts ``YYYY-MM-DD`` (and, for older clients, a timestamp, whose own
#: wall-clock day is taken). Holds an aware midnight-UTC ``datetime`` in Python,
#: so service code and the column see one form. Sends ``YYYY-MM-DD`` in JSON.
CalendarDay = Annotated[
    datetime,
    BeforeValidator(_validate),
    PlainSerializer(calendar_day_iso, return_type=str | None, when_used="json"),
]
