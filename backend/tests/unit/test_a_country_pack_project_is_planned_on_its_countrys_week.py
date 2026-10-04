# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A project created under a country pack is planned on that country's working week.

The schedule picks a project's week from ``project.region`` alone. A project
created while a country pack is active inherits the pack's market into
``project.country_code``, and its region is whatever the creator typed: a city,
or nothing. So a Saudi pack project in "Riyadh" was planned Monday to Friday
while its own country column said SA, which works Sunday to Thursday. Two days
of every week landed on the wrong side of the weekend and nothing flagged it,
because a Monday-Friday week is a plausible answer.

The gates beside this one walk ``core.calendar._WORKING_WEEK`` and the seed file
by country code, and a country code was never the string the schedule was
handed. This file asks the question through the input the product really
builds: a pack's market in the country column and a region that names no
calendar of its own.

It also writes down which pack countries have no public-holiday source at all,
in either the core holiday functions or the seeded calendars. That list is a
gap, not a design, and it cancels itself: a country that gains a source must
leave it.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import uuid
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.calendar import _DEFAULT_WORKING_WEEK, _HOLIDAY_FUNCS, _WORKING_WEEK
from app.modules.schedule.service import (
    WORK_CALENDARS,
    ScheduleService,
    calendar_region_for,
    get_work_calendar,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKS_DIR = REPO_ROOT / "packs"
SEED = REPO_ROOT / "backend" / "app" / "modules" / "i18n_foundation" / "seed_data" / "work_calendars.json"

_DAY = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SUN_TO_THU = {6, 0, 1, 2, 3}
MON_TO_FRI = {0, 1, 2, 3, 4}

#: Region strings a pack project plausibly carries that name no calendar: a
#: city the resolver has no row for, a blank field, and nothing at all.
_UNRESOLVED_REGIONS: tuple[str | None, ...] = ("Somewhere City", "", None)

#: Pack countries with no public-holiday source anywhere: no function in
#: ``core.calendar._HOLIDAY_FUNCS`` and no row in the seeded calendars. Their
#: working days are counted with weekends alone. Listed as open, each with what
#: a source would need, and checked so an entry cannot outlive its gap.
COUNTRIES_WITHOUT_A_HOLIDAY_SOURCE: dict[str, str] = {
    "BE": "the ten Belgian legal holidays, three of them movable with Easter",
    "GR": "the Greek public holidays, four of them movable with Orthodox Easter",
    "HR": "the Croatian holidays under the 2019 Holidays Act",
    "HU": "the Hungarian holidays plus the bridge-day swaps the ministry decrees each year",
    "ID": "the Indonesian national holidays and cuti bersama, set by joint ministerial decree each year",
    "IE": "the ten Irish public holidays, four of them first-Monday rules",
    "PT": "the Portuguese national holidays",
    "RO": "the Romanian legal holidays under Labour Code art. 139, Orthodox Easter based",
    "SG": "the gazetted Singapore holidays, four of them lunar",
}


@lru_cache(maxsize=1)
def _pack_countries() -> dict[str, str]:
    """Country code -> one pack slug for it, for every country pack shipped."""
    out: dict[str, str] = {}
    for path in sorted(PACKS_DIR.glob("*/src/*/manifest.py")):
        name = f"_calendar_manifest_{path.parts[-2]}"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader, f"{path} cannot be loaded as a module"
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        country = module.MANIFEST.market_country_code
        if country:
            out.setdefault(country, module.MANIFEST.slug)
    return out


@lru_cache(maxsize=1)
def _seeded_weeks() -> dict[str, set[int]]:
    """Country -> seeded week on the Monday-zero axis (the seed is ISO, Mon=1)."""
    rows = json.loads(SEED.read_text(encoding="utf-8"))
    return {row["country_code"]: {day - 1 for day in row["work_days"]} for row in rows}


def _country_week(country: str) -> set[int]:
    """The week the country works, from the most authoritative table that has it."""
    if country in _WORKING_WEEK:
        return set(_WORKING_WEEK[country])
    if country in _seeded_weeks():
        return _seeded_weeks()[country]
    return set(_DEFAULT_WORKING_WEEK)


def _names(days: set[int]) -> str:
    return ", ".join(_DAY[d] for d in sorted(days))


# ── Controls ─────────────────────────────────────────────────────────────────


def test_the_population_holds_a_country_whose_week_is_not_monday_to_friday() -> None:
    """Without one, every assertion below would pass on a Monday-Friday fallback."""
    countries = _pack_countries()
    assert len(countries) >= 35, f"only {len(countries)} pack countries were found under {PACKS_DIR}"
    odd = sorted(c for c in countries if _country_week(c) != MON_TO_FRI)
    assert "SA" in odd, f"the Saudi pack is gone or its week is Monday-Friday now; odd weeks: {odd}"


def test_reading_the_region_alone_is_what_planned_the_saudi_pack_on_the_wrong_week() -> None:
    """The defect, reproduced on the old input, so the fix below is measured against it."""
    assert set(get_work_calendar("Riyadh")["work_days"]) == MON_TO_FRI
    assert set(get_work_calendar(calendar_region_for("Riyadh", "SA"))["work_days"]) == SUN_TO_THU


# ── The rule ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("region", "country", "expected"),
    [
        # A region naming no calendar gives way to the country column.
        ("Riyadh", "SA", "GULF"),
        ("", "SA", "GULF"),
        (None, "QA", "GULF"),
        ("riyadh", "sa", "GULF"),
        # A group label gives way too: the UAE left the Gulf week in 2022.
        ("GulfStates", "AE", "UAE"),
        ("Middle East", "AE", "UAE"),
        ("DACH", "AT", "DACH"),
        # A region naming a calendar of its own keeps it.
        ("QA", "", "GULF"),
        ("Qatar", None, "GULF"),
        ("DE_BERLIN", "SA", "DACH"),
        ("United Arab Emirates", "SA", "UAE"),
        # A region naming a country whose week is the standard one keeps it
        # too. The country column may come from whichever pack was active, so
        # a Warsaw project created under the Saudi, Indian or Chinese pack was
        # planned on the Gulf, the Indian or the Chinese week while the BOQ
        # router validated it as Polish.
        ("PL_WARSAW", "SA", "DEFAULT"),
        ("PL", "IN", "DEFAULT"),
        ("IT_MILAN", "CN", "DEFAULT"),
        ("TR_ISTANBUL", "SA", "DEFAULT"),
        ("JP", "IN", "DEFAULT"),
        # A spelling only the registry reads names its country's week.
        ("UNITED_STATES", "SA", "US"),
        # No usable country leaves the region to answer, as before.
        ("Riyadh", None, "DEFAULT"),
        ("Riyadh", "SAU", "DEFAULT"),
        ("Riyadh", "1A", "DEFAULT"),
        ("GulfStates", None, "GULF"),
    ],
)
def test_the_week_comes_from_the_region_unless_the_country_is_the_more_precise_statement(
    region: str | None, country: str | None, expected: str
) -> None:
    calendar = get_work_calendar(calendar_region_for(region, country))
    assert calendar is WORK_CALENDARS[expected], (
        f"region {region!r} with country {country!r} resolved to {calendar['label']!r}, "
        f"expected {WORK_CALENDARS[expected]['label']!r}"
    )


def _region_population() -> list[str]:
    """Every region spelling the registry reads as a country, plus the shapes that name none."""
    from app.core import classification_registry as registry

    spellings = (
        set(registry.REGION_ALIAS_TO_COUNTRY)
        | set(registry._catalogue_region_to_country())
        | set(registry.COUNTRY_TO_STANDARD)
    )
    return sorted(spellings | {"Riyadh", "Somewhere City", "", "DACH", "GulfStates", "Middle East", "LATAM"})


def _router_country(region: str, country: str) -> str | None:
    """The country ``_build_rule_sets`` validates a project as, decided the way it decides it."""
    from app.core.classification_registry import is_macro_region, normalise_region

    from_region = normalise_region(region)
    from_column = normalise_region(country)
    if from_column and (from_region is None or is_macro_region(region)):
        return from_column
    return from_region


def test_the_population_holds_regions_that_name_a_standard_week_country() -> None:
    """Control: the agreement below is only worth something over regions that disagree with the column."""
    from app.core.classification_registry import normalise_region

    named = {normalise_region(r) for r in _region_population()}
    for country in ("PL", "IT", "NL", "TR", "JP", "AU", "ZA"):
        assert country in named, f"no region in the population names {country}"
    assert len(_region_population()) >= 80, f"only {len(_region_population())} region spellings were read"


@pytest.mark.parametrize("column", ["SA", "IN", "CN", "AE", "US", "PL"])
def test_the_week_is_planned_for_the_country_the_bill_is_validated_as(column: str) -> None:
    """The schedule and the BOQ router read one project's two columns into one country.

    Before, a region naming a country with the standard week (Poland, Italy,
    Japan, ...) gave way to the country column, while the router kept the
    region: the bill was checked as Polish and the dates were planned on the
    week of whichever pack had filled the column.
    """
    wrong: list[str] = []
    for region in _region_population():
        country = _router_country(region, column)
        assert country is not None, f"region {region!r} with column {column} names no country at all"
        planned = get_work_calendar(calendar_region_for(region, column))
        if planned is not get_work_calendar(country):
            wrong.append(f"{region!r}: validated as {country}, planned on {planned['label']!r}")
    assert wrong == [], f"with country column {column}: {wrong}"


def test_the_agreement_check_catches_a_region_that_gives_way_to_the_column() -> None:
    """Negative control: the resolver as the wave first wrote it fails the agreement above."""
    from app.core.classification_registry import is_macro_region

    def _first_version(region: str | None, country_code: str | None) -> str | None:
        if get_work_calendar(region) is WORK_CALENDARS["DEFAULT"] or is_macro_region(region):
            return country_code
        return region

    region, column = "PL_WARSAW", "SA"
    assert _router_country(region, column) == "PL"
    assert get_work_calendar(_first_version(region, column)) is not get_work_calendar("PL")
    assert get_work_calendar(calendar_region_for(region, column)) is get_work_calendar("PL")


# ── Every country pack ───────────────────────────────────────────────────────


@pytest.mark.parametrize("country", sorted(_pack_countries()))
@pytest.mark.parametrize("region", _UNRESOLVED_REGIONS)
def test_a_pack_project_never_rests_a_day_its_country_works(country: str, region: str | None) -> None:
    planning = set(get_work_calendar(calendar_region_for(region, country))["work_days"])
    worked = _country_week(country)
    rested = worked - planning
    assert not rested, (
        f"a {_pack_countries()[country]} project in region {region!r} rests {_names(rested)}, which "
        f"{country} works. Country week {_names(worked)}, planning week {_names(planning)}."
    )


@pytest.mark.parametrize("country", sorted(c for c in _pack_countries() if _country_week(c) != MON_TO_FRI))
def test_a_pack_country_with_its_own_week_is_planned_on_exactly_that_week(country: str) -> None:
    """For a week that is not Monday-Friday, an extra day is as wrong as a missing one."""
    planning = set(get_work_calendar(calendar_region_for("Somewhere City", country))["work_days"])
    assert planning == _country_week(country), (
        f"{country}: planned {_names(planning)}, works {_names(_country_week(country))}"
    )


def test_the_schedule_service_hands_the_resolver_the_country_of_a_pack_project() -> None:
    """End to end through the one method every date path asks."""

    def _service(project: Any) -> ScheduleService:
        async def _get(*_args: Any, **_kwargs: Any) -> Any:
            return project

        service = ScheduleService.__new__(ScheduleService)
        service.session = SimpleNamespace(get=_get)
        return service

    pid = uuid.uuid4()
    saudi = _service(SimpleNamespace(id=pid, region="Riyadh", country_code="SA"))
    region = asyncio.run(saudi.resolve_project_region(pid))
    assert set(get_work_calendar(region)["work_days"]) == SUN_TO_THU

    # A row written before the country column existed answers as it always has.
    legacy = _service(SimpleNamespace(id=pid, region="Riyadh"))
    assert asyncio.run(legacy.resolve_project_region(pid)) == "Riyadh"

    berlin = _service(SimpleNamespace(id=pid, region="DE_BERLIN", country_code="DE"))
    assert asyncio.run(berlin.resolve_project_region(pid)) == "DE_BERLIN"

    # Created under the Saudi pack with a Warsaw region and no country typed:
    # the column says SA, the project is in Poland, and the badge echoes the
    # region the user wrote.
    warsaw = _service(SimpleNamespace(id=pid, region="PL_WARSAW", country_code="SA"))
    region = asyncio.run(warsaw.resolve_project_region(pid))
    assert region == "PL_WARSAW"
    assert get_work_calendar(region) is WORK_CALENDARS["DEFAULT"]

    gone = _service(None)
    assert asyncio.run(gone.resolve_project_region(pid)) is None


# ── Public holidays ──────────────────────────────────────────────────────────


def _has_holiday_source(country: str) -> bool:
    return country in _HOLIDAY_FUNCS or country in _seeded_weeks()


def test_every_pack_country_without_a_holiday_source_is_named() -> None:
    silent = sorted(
        c for c in _pack_countries() if not _has_holiday_source(c) and c not in COUNTRIES_WITHOUT_A_HOLIDAY_SOURCE
    )
    assert silent == [], (
        f"pack countries {silent} have no public-holiday source in core.calendar or the seed file, so "
        "their working days count weekends alone. Add a source, or name the gap in "
        "COUNTRIES_WITHOUT_A_HOLIDAY_SOURCE with what it would take."
    )


@pytest.mark.parametrize("country", sorted(COUNTRIES_WITHOUT_A_HOLIDAY_SOURCE))
def test_a_named_holiday_gap_is_still_a_gap(country: str) -> None:
    assert country in _pack_countries(), f"{country} has no pack any more; remove it from the list"
    assert not _has_holiday_source(country), (
        f"{country} has a holiday source now; remove it from COUNTRIES_WITHOUT_A_HOLIDAY_SOURCE"
    )
