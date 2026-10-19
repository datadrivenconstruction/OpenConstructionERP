# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Announced observed dates of public holidays, held as data.

Some governments decide each year, by decree, on which day a holiday is
actually observed: Egypt moves most midweek national days to the Thursday, and
announces the Islamic feasts after the official moon sighting. Whether a given
holiday moves in a given year is a decision, so nothing computes it. Each
announcement is one row in ``country_data/holiday_observances.json``.

A row names the holiday by the key the country's holiday function uses, the
dates that function computes (``statutory``) and the dates observed instead
(``observed``). :func:`apply_observances` refuses a row whose statutory dates
no longer match the computation, because a move applied blind would delete
whatever day happens to be computed now.

One loader and one validator serve every country. The module is pure: stdlib
only, no ORM, so the calendar engine can import it at any time.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA_PATH = Path(__file__).parent / "country_data" / "holiday_observances.json"

#: Whether the source states that the move covers private employers. Cabinet
#: decrees in Egypt sometimes name only the civil service, and the labour
#: minister follows with a separate decision for the private sector. The engine
#: applies the move either way and the row says which it was.
PRIVATE_SECTOR_VALUES = frozenset({"stated", "not_stated"})

_REQUIRED = ("country", "year", "holiday", "statutory", "observed", "authority", "source_url", "private_sector")


@dataclass(frozen=True)
class Observance:
    """One announced observed date for one holiday in one year."""

    country: str
    year: int
    holiday: str
    statutory: tuple[date, ...]
    observed: tuple[date, ...]
    authority: str
    source_url: str
    private_sector: str
    note: str = ""


def _dates(raw: Any, year: int, field: str, where: str) -> tuple[date, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{where}: {field} must be a non-empty list of ISO dates")
    out: list[date] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(f"{where}: {field} holds a non-string date")
        day = date.fromisoformat(item)
        if day.isoformat() != item or day.year != year:
            raise ValueError(f"{where}: {field} date {item} is not an ISO date in {year}")
        out.append(day)
    if len(set(out)) != len(out):
        raise ValueError(f"{where}: {field} repeats a date")
    return tuple(sorted(out))


def parse_observances(rows: Iterable[Mapping[str, Any]]) -> tuple[Observance, ...]:
    """Validate raw rows into :class:`Observance` objects.

    Raises:
        ValueError: on a missing field, a malformed or out-of-year date, a
            non-https source, an unknown private-sector value, or two rows for
            the same country, year and holiday.
    """
    parsed: list[Observance] = []
    seen: set[tuple[str, int, str]] = set()
    for index, row in enumerate(rows):
        where = f"holiday observance #{index}"
        if not isinstance(row, Mapping):
            raise ValueError(f"{where}: not an object")
        missing = [k for k in _REQUIRED if k not in row]
        if missing:
            raise ValueError(f"{where}: missing {missing}")
        country = str(row["country"]).strip().upper()
        if len(country) != 2 or not country.isalpha():
            raise ValueError(f"{where}: country {row['country']!r} is not ISO 3166-1 alpha-2")
        year = row["year"]
        if not isinstance(year, int) or isinstance(year, bool):
            raise ValueError(f"{where}: year must be an integer")
        holiday = str(row["holiday"]).strip()
        authority = str(row["authority"]).strip()
        source_url = str(row["source_url"]).strip()
        private_sector = str(row["private_sector"]).strip()
        if not holiday or not authority:
            raise ValueError(f"{where}: holiday and authority must be named")
        if not source_url.startswith("https://"):
            raise ValueError(f"{where}: source_url must be an https URL")
        if private_sector not in PRIVATE_SECTOR_VALUES:
            raise ValueError(f"{where}: private_sector must be one of {sorted(PRIVATE_SECTOR_VALUES)}")
        key = (country, year, holiday)
        if key in seen:
            raise ValueError(f"{where}: a second row for {country}/{year}/{holiday}")
        seen.add(key)
        parsed.append(
            Observance(
                country=country,
                year=year,
                holiday=holiday,
                statutory=_dates(row["statutory"], year, "statutory", where),
                observed=_dates(row["observed"], year, "observed", where),
                authority=authority,
                source_url=source_url,
                private_sector=private_sector,
                note=str(row.get("note", "")),
            )
        )
    return tuple(parsed)


@lru_cache(maxsize=1)
def load_observances() -> tuple[Observance, ...]:
    """Every shipped observance, validated. Raises on a malformed file."""
    rows = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("holiday_observances.json must hold a list")
    return parse_observances(rows)


def apply_observances(country: str, year: int, named: Mapping[str, Iterable[date]]) -> set[date]:
    """The year's holidays with every announced observance applied.

    Args:
        country: ISO 3166-1 alpha-2 code.
        year: Gregorian year.
        named: holiday key -> the dates the country's function computes.

    Returns:
        The union of all holidays, each replaced by its observed dates where a
        row exists.

    Raises:
        ValueError: a row names a holiday the function does not compute, or
            its statutory dates differ from the computed ones.
    """
    computed = {key: tuple(sorted(set(days))) for key, days in named.items()}
    for row in load_observances():
        if row.country != country or row.year != year:
            continue
        if row.holiday not in computed:
            raise ValueError(f"observance for {country}/{year} names unknown holiday {row.holiday!r}")
        if computed[row.holiday] != row.statutory:
            raise ValueError(
                f"observance for {country}/{year}/{row.holiday} moves {[d.isoformat() for d in row.statutory]} "
                f"but the engine computes {[d.isoformat() for d in computed[row.holiday]]}"
            )
        computed[row.holiday] = row.observed
    return {day for days in computed.values() for day in days}
