# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Explicitly enabled, year-specific holiday rosters from packaged seed data.

The seed also carries calendars that have not been reviewed for core scheduling.
Its presence alone must never enable a country or extrapolate another year.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

# Expected roster sizes guard against losing or gaining a structurally valid
# entry. Exact dates remain independently pinned in tests; a count is not an
# authenticity check for arbitrary changes to the packaged file.
SEEDED_HOLIDAY_COUNTS = {("PT", 2026): 13}
_SEED_PATH = Path(__file__).parent.parent / "modules/i18n_foundation/seed_data/work_calendars.json"


def seeded_holiday_dates(country: str, year: int) -> frozenset[date] | None:
    """Return an enabled roster, None outside its scope, or raise on bad data.

    No seed file is opened for a country/year outside the explicit bindings.
    Failures are not cached: the caller must not turn unreadable data into a
    holiday-free calendar, and a repaired file must be readable on the next call.
    """
    expected_count = SEEDED_HOLIDAY_COUNTS.get((country, year))
    if expected_count is None:
        return None

    rows = json.loads(_SEED_PATH.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("The work-calendar seed must be a list")
    matching = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("country_code") == country and row.get("year") == str(year)
    ]
    if len(matching) != 1:
        raise ValueError(f"Expected exactly one shipped holiday calendar for {country}/{year}")

    exceptions = matching[0].get("exceptions")
    if not isinstance(exceptions, list) or not exceptions:
        raise ValueError(f"Expected a nonempty holiday roster for {country}/{year}")
    if len(exceptions) != expected_count:
        raise ValueError(f"Expected {expected_count} holiday dates for {country}/{year}")
    dates: set[date] = set()
    for item in exceptions:
        if not isinstance(item, dict) or item.get("type") != "public_holiday":
            raise ValueError(f"Unsupported holiday entry in {country}/{year}")
        raw = item.get("date")
        if not isinstance(raw, str):
            raise ValueError(f"Expected an ISO holiday date in {country}/{year}")
        day = date.fromisoformat(raw)
        if day.isoformat() != raw or day.year != year:
            raise ValueError(f"Holiday date does not match {country}/{year}: {raw}")
        if day in dates:
            raise ValueError(f"Duplicate holiday date in {country}/{year}: {raw}")
        dates.add(day)
    return frozenset(dates)
