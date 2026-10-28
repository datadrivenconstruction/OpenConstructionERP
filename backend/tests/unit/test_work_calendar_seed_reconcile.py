# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The work calendar reconciler agrees with the file it delivers from.

The reconciler itself needs a database and is covered where the other boot-path
repairs are. What is checked here is the half that does not: the table of ship
dates, the anchors derived from it, and the row builder both the seeder and the
reconciler go through. Those are the parts that rot silently when somebody adds
a country to ``work_calendars.json`` and nothing tells them there is a second
place to write.
"""

from __future__ import annotations

import pytest

from app.modules.i18n_foundation.seed import load_work_calendar_seed_rows, work_calendar_from_seed_row
from app.modules.i18n_foundation.work_calendar_seed_reconcile import (
    ANCHOR_COUNTRIES,
    CALENDAR_FIRST_SHIPPED,
    delivery_key,
)

#: The four the Gulf gap is about. Named separately from the six in
#: CALENDAR_FIRST_SHIPPED because these are the ones whose absence changes a
#: date; Bulgaria and Nigeria are Monday to Friday, which is what the fallback
#: already answers.
_GULF = ("QA", "KW", "BH", "OM")

#: Sunday through Thursday, ISO numbering.
_GULF_WEEK = [7, 1, 2, 3, 4]


@pytest.mark.parametrize("slot", sorted(CALENDAR_FIRST_SHIPPED))
def test_every_dated_calendar_is_still_in_the_seed_file(slot: tuple[str, str]) -> None:
    """A ship date for a row that is no longer shipped delivers nothing, quietly."""
    shipped = {(row["country_code"], row["year"]) for row in load_work_calendar_seed_rows()}
    assert slot in shipped, (
        f"{delivery_key(slot)} carries a ship date in CALENDAR_FIRST_SHIPPED but is not in "
        "work_calendars.json. Either the calendar was removed and the entry should go with it, "
        "or the year was changed and the entry has to follow."
    )


@pytest.mark.parametrize("country_code", _GULF)
def test_the_calendar_that_would_be_delivered_carries_the_gulf_week(country_code: str) -> None:
    """Delivering the wrong week would be worse than delivering nothing.

    The whole point of the repair is that a country with no calendar answers a
    confident Monday-to-Friday. Handing it a row that says the same thing in
    different numbers would close the gap on paper and change no date.
    """
    row = next((r for r in load_work_calendar_seed_rows() if r["country_code"] == country_code), None)
    assert row is not None, f"{country_code} is not in the seed file, so there is nothing to deliver"
    assert row["work_days"] == _GULF_WEEK, (
        f"{country_code} is seeded as {row['work_days']}, not the Sunday-to-Thursday {_GULF_WEEK}. "
        "On the ISO axis this column is read on, Sunday is 7 and Friday is 5."
    )


def test_a_country_being_delivered_cannot_also_be_dating_the_seed() -> None:
    """Anchors and deliverables must be disjoint.

    A country added after release one is absent from exactly the installs whose
    seed date is being established, so letting it anchor would date those
    installs by a row they cannot have.
    """
    delivered = {country for country, _ in CALENDAR_FIRST_SHIPPED}
    overlap = ANCHOR_COUNTRIES & delivered
    assert not overlap, f"These countries are both anchors and deliverables: {sorted(overlap)}"


@pytest.mark.parametrize("country_code", sorted({row["country_code"] for row in load_work_calendar_seed_rows()}))
def test_every_shipped_country_is_either_an_anchor_or_dated(country_code: str) -> None:
    """The gate the frozen anchor set exists to make possible.

    While the anchors were derived as "everything shipped, less what is dated",
    a country added to the seed file without a ship date was absorbed into the
    anchors silently and then delivered to nobody - and no test could see it,
    because the derivation made the two sets agree by construction. Frozen, the
    two sets can disagree, and that disagreement is this failure.
    """
    dated = {country for country, _ in CALENDAR_FIRST_SHIPPED}
    assert country_code in ANCHOR_COUNTRIES or country_code in dated, (
        f"{country_code} is in work_calendars.json but is neither in ANCHOR_COUNTRIES, which is "
        "closed history and must not grow, nor in CALENDAR_FIRST_SHIPPED. A country added to the "
        "seed file needs a ship date there, or no install that predates it will ever be given it."
    )


def test_the_anchor_set_is_the_membership_of_the_first_release() -> None:
    """It is a historical fact, so it has a fixed size, and 30 is that size.

    Not a census of a growing file - that is what CALENDAR_FIRST_SHIPPED is for.
    This number cannot change without somebody rewriting what release one
    contained, which is the one thing that cannot happen.
    """
    assert len(ANCHOR_COUNTRIES) == 30
    assert "SA" in ANCHOR_COUNTRIES, "Saudi Arabia shipped in the first release"
    for late in ("BG", "NG", "QA", "KW", "BH", "OM"):
        assert late not in ANCHOR_COUNTRIES, f"{late} shipped after release one and cannot date a seed"


def test_the_delivery_key_format_is_the_one_already_in_the_field() -> None:
    """Recorded in oe_data_repair_delivery and read back on every boot, so it is permanent."""
    assert delivery_key(("QA", "2026")) == "QA/2026"


@pytest.mark.parametrize("country_code", _GULF)
def test_the_delivered_row_is_the_row_the_seeder_would_have_written(country_code: str) -> None:
    """One builder, so a delivered calendar cannot drift from a seeded one."""
    row = next(r for r in load_work_calendar_seed_rows() if r["country_code"] == country_code)
    built = work_calendar_from_seed_row(row)

    assert built.country_code == row["country_code"]
    assert built.year == row["year"]
    assert built.work_days == row["work_days"]
    assert built.name == row["name"]
    assert built.exceptions == row["exceptions"]
    assert built.work_hours_per_day == row.get("work_hours_per_day", "8")
    assert built.metadata_ == {}
