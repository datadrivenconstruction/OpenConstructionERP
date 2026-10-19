# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Seasonal bans on outdoor work, per country. Data, read by a field-time warning.

Some countries forbid outdoor work in direct sun during the hottest hours of
summer. A schedule that plans concrete pours at 13:00 in July, or a timesheet
that books them, is planning or recording work the law does not allow. This
module writes each ban down once, with its season, its daily hours, the
country's clock and the source, and answers one question: does a span of
work touch a ban.

**Local time is the law's time.** A ban says 12:00 to 15:00 on the country's
clock. A recorded instant with a time zone is converted to that clock first,
so 09:30 UTC is 12:30 in Riyadh. An instant without a time zone is read as
already being local wall time.

**A warning, never a block.** The timesheet does not say whether a line was
worked outdoors in the sun, and every ban has exempt sectors and emergency
work. The reader of this table warns and leaves the decision to a person.

Standard library only; nothing here imports from ``app.modules``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

__all__ = [
    "OUTDOOR_WORK_BANS",
    "OutdoorWorkBan",
    "ban_overlap",
    "validate_bans",
]


@dataclass(frozen=True)
class OutdoorWorkBan:
    """One recurring seasonal ban on outdoor work.

    Attributes:
        country_code: ISO 3166-1 alpha-2 code of the jurisdiction.
        season_start: ``(month, day)`` of the first day of the season, inclusive.
        season_end: ``(month, day)`` of the last day of the season, inclusive.
        hours_from: Local time the daily ban starts.
        hours_to: Local time the daily ban ends (exclusive).
        utc_offset: The country's clock. Only for a country without daylight
            saving time, where a fixed offset is the whole truth.
        first_season: The first year the source evidences; an earlier date
            answers no ban rather than assuming one.
        scope: What the ban covers, in English.
        exemptions: Who is exempt, in English.
        legal_reference: The decision the ban comes from.
        source_url: Where the ban was read.
        read_date: ISO date the source was read.
        needs_expert_review: True where the figure is from secondary sources.
        note: One sentence a person reads beside the figure.
    """

    country_code: str
    season_start: tuple[int, int]
    season_end: tuple[int, int]
    hours_from: time
    hours_to: time
    utc_offset: timedelta
    first_season: int
    scope: str
    exemptions: str
    legal_reference: str
    source_url: str
    read_date: str
    needs_expert_review: bool = False
    note: str = ""

    def in_season(self, day: date) -> bool:
        """Whether ``day`` (on the country's clock) falls inside the season."""
        if day.year < self.first_season:
            return False
        return self.season_start <= (day.month, day.day) <= self.season_end


OUTDOOR_WORK_BANS: tuple[OutdoorWorkBan, ...] = (
    OutdoorWorkBan(
        country_code="SA",
        season_start=(6, 15),
        season_end=(9, 15),
        hours_from=time(12, 0),
        hours_to=time(15, 0),
        utc_offset=timedelta(hours=3),
        first_season=2025,
        scope="Work in open areas exposed to direct sunlight, private sector employers",
        exemptions="Oil and gas companies and emergency maintenance work, per the annual decision",
        legal_reference=(
            "Ministry of Human Resources and Social Development decision on the midday outdoor work ban, "
            "issued each year with the National Council for Occupational Safety and Health"
        ),
        source_url=(
            "https://gulfnews.com/world/gulf/saudi/"
            "saudi-arabias-three-month-midday-outdoor-work-ban-to-take-effect-on-june-15-1.500158142"
        ),
        read_date="2026-10-19",
        needs_expert_review=True,
        note=(
            "The ban is announced each year; the dates and hours are read in press and law-firm summaries of the "
            "2025 decision, not in the decision itself, and the ministry may change them in a later year."
        ),
    ),
)


def _country(value: str | None) -> str:
    return (value or "").strip().upper()


def _local(instant: datetime, offset: timedelta) -> datetime:
    """The wall time of ``instant`` on a clock ``offset`` from UTC, without a zone."""
    if instant.tzinfo is None:
        return instant
    return instant.astimezone(timezone(offset)).replace(tzinfo=None)


def ban_overlap(
    country: str | None,
    start: datetime | None,
    end: datetime | None,
    bans: Sequence[OutdoorWorkBan] = OUTDOOR_WORK_BANS,
) -> tuple[OutdoorWorkBan, date] | None:
    """The first ban a span of work touches, with the local day it touches it on.

    Args:
        country: The project's country, ISO alpha-2.
        start: When the work started.
        end: When it ended. An end before the start is read as the next day
            (a night shift), as the timesheet engine reads it.
        bans: The table to read, the shipped one by default.

    Returns:
        ``(ban, day)`` or ``None`` when the span touches no ban, the country
        has none, or either time is missing.
    """
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return None
    wanted = _country(country)
    for ban in bans:
        if _country(ban.country_code) != wanted:
            continue
        local_start = _local(start, ban.utc_offset)
        local_end = _local(end, ban.utc_offset)
        if local_end <= local_start:
            local_end += timedelta(days=1)
        day = local_start.date()
        while day <= local_end.date():
            window_start = datetime.combine(day, ban.hours_from)
            window_end = datetime.combine(day, ban.hours_to)
            if ban.in_season(day) and local_start < window_end and window_start < local_end:
                return ban, day
            day += timedelta(days=1)
    return None


def validate_bans(bans: Sequence[OutdoorWorkBan]) -> list[str]:
    """Describe everything that makes the table unsafe to read; empty for a sound one."""
    problems: list[str] = []
    seen: set[str] = set()
    for ban in bans:
        where = _country(ban.country_code) or "?"
        if len(where) != 2:
            problems.append(f"{where}: country_code is not ISO 3166-1 alpha-2")
        if where in seen:
            problems.append(f"{where}: more than one ban; the reader stops at the first")
        seen.add(where)
        for label, (month, day) in (("season_start", ban.season_start), ("season_end", ban.season_end)):
            try:
                date(2024, month, day)
            except ValueError:
                problems.append(f"{where}: {label} {month}-{day} is not a calendar day")
        if ban.season_end < ban.season_start:
            problems.append(f"{where}: a season across the new year is not supported")
        if ban.hours_to <= ban.hours_from:
            problems.append(f"{where}: hours_to must lie after hours_from")
        if not ban.legal_reference.strip():
            problems.append(f"{where}: legal_reference is empty")
        if not ban.source_url.startswith("https://"):
            problems.append(f"{where}: source_url must be an https address")
        if ban.needs_expert_review and not ban.note.strip():
            problems.append(f"{where}: a ban flagged for review must say why in its note")
        try:
            date.fromisoformat(ban.read_date)
        except ValueError:
            problems.append(f"{where}: read_date {ban.read_date!r} is not an ISO date")
    return problems
