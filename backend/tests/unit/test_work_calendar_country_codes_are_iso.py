"""A country code must select that country's working week, not another country's.

``schedule.service.get_work_calendar`` picks the working week that
``compute_duration`` and the schedule generator count days with. It resolves a
region string by taking the head of the string before the first underscore and
looking it up in one dict.

That one dict holds two vocabularies at once. Most of its keys are ISO 3166-1
alpha-2 country codes, which is what the shipped CWICR catalogue uses today
(``BR_SAOPAULO``, ``CA_TORONTO``, ``AR_BUENOSAIRES``, ``PT_LISBON``). A few are
heads of a superseded catalogue naming that keyed regions by language instead
(``ZH_SHANGHAI``, ``HI_MUMBAI``, ``SP_BARCELONA``, ``AR_DUBAI``,
``PT_SAOPAULO``) - every one of which ``core.match_service.region_language``
already renames to its ISO form.

Where the two vocabularies disagreed, the language reading used to win:

* ``AR`` means Arabic in the old naming and Argentina in ISO, so Buenos Aires
  was given the Gulf calendar.
* ``PT`` means Portuguese in the old naming and Portugal in ISO, so Lisbon was
  given the Brazilian week of six days.
* ``CA`` is Canada in ISO and appeared in neither reading, so the Canada
  calendar was unreachable by any country code at all.

The Gulf calendar has since been split in two, because the six GCC states do
not share one week: five work Sunday to Thursday and the UAE works Monday to
Friday. ``AE`` and its neighbours therefore resolve to different calendars.

This file asserts the ISO reading, over the whole of ISO 3166-1 alpha-2 rather
than over a hand-picked sample, so a future key that reintroduces the confusion
is caught by the sweep instead of by a customer.

Two neighbouring structures are deliberately *not* asserted on here, because
neither is what the date arithmetic reads:

* ``core.calendar._WORKING_WEEK`` maps a country to a bare frozenset of
  weekdays with no hours and no label. It belongs to another change in flight;
  this file imports it read-only to prove the shape differs, and never writes
  it.
* ``i18n_foundation``'s ``WorkCalendar`` rows carry ``work_hours_per_day`` and
  ISO weekday numbers where Monday is 1.

``WORK_CALENDARS`` carries ``hours_per_day`` and ``work_days`` where Monday is
0, and those are the field names and the convention the two consumers read.
``test_shape_proves_which_structure_the_arithmetic_reads`` pins that down.
"""

from __future__ import annotations

import app.modules.schedule.service as schedule_service
from app.modules.schedule.service import WORK_CALENDARS, compute_duration, get_work_calendar

# ISO 3166-1 alpha-2, officially assigned. Embedded as data so the sweep below
# is exhaustive rather than a sample, and so it does not depend on a package
# this product does not ship.
ISO_3166_ALPHA2 = frozenset(
    [
        "AD",
        "AE",
        "AF",
        "AG",
        "AI",
        "AL",
        "AM",
        "AO",
        "AQ",
        "AR",
        "AS",
        "AT",
        "AU",
        "AW",
        "AX",
        "AZ",
        "BA",
        "BB",
        "BD",
        "BE",
        "BF",
        "BG",
        "BH",
        "BI",
        "BJ",
        "BL",
        "BM",
        "BN",
        "BO",
        "BQ",
        "BR",
        "BS",
        "BT",
        "BV",
        "BW",
        "BY",
        "BZ",
        "CA",
        "CC",
        "CD",
        "CF",
        "CG",
        "CH",
        "CI",
        "CK",
        "CL",
        "CM",
        "CN",
        "CO",
        "CR",
        "CU",
        "CV",
        "CW",
        "CX",
        "CY",
        "CZ",
        "DE",
        "DJ",
        "DK",
        "DM",
        "DO",
        "DZ",
        "EC",
        "EE",
        "EG",
        "EH",
        "ER",
        "ES",
        "ET",
        "FI",
        "FJ",
        "FK",
        "FM",
        "FO",
        "FR",
        "GA",
        "GB",
        "GD",
        "GE",
        "GF",
        "GG",
        "GH",
        "GI",
        "GL",
        "GM",
        "GN",
        "GP",
        "GQ",
        "GR",
        "GS",
        "GT",
        "GU",
        "GW",
        "GY",
        "HK",
        "HM",
        "HN",
        "HR",
        "HT",
        "HU",
        "ID",
        "IE",
        "IL",
        "IM",
        "IN",
        "IO",
        "IQ",
        "IR",
        "IS",
        "IT",
        "JE",
        "JM",
        "JO",
        "JP",
        "KE",
        "KG",
        "KH",
        "KI",
        "KM",
        "KN",
        "KP",
        "KR",
        "KW",
        "KY",
        "KZ",
        "LA",
        "LB",
        "LC",
        "LI",
        "LK",
        "LR",
        "LS",
        "LT",
        "LU",
        "LV",
        "LY",
        "MA",
        "MC",
        "MD",
        "ME",
        "MF",
        "MG",
        "MH",
        "MK",
        "ML",
        "MM",
        "MN",
        "MO",
        "MP",
        "MQ",
        "MR",
        "MS",
        "MT",
        "MU",
        "MV",
        "MW",
        "MX",
        "MY",
        "MZ",
        "NA",
        "NC",
        "NE",
        "NF",
        "NG",
        "NI",
        "NL",
        "NO",
        "NP",
        "NR",
        "NU",
        "NZ",
        "OM",
        "PA",
        "PE",
        "PF",
        "PG",
        "PH",
        "PK",
        "PL",
        "PM",
        "PN",
        "PR",
        "PS",
        "PT",
        "PW",
        "PY",
        "QA",
        "RE",
        "RO",
        "RS",
        "RU",
        "RW",
        "SA",
        "SB",
        "SC",
        "SD",
        "SE",
        "SG",
        "SH",
        "SI",
        "SJ",
        "SK",
        "SL",
        "SM",
        "SN",
        "SO",
        "SR",
        "SS",
        "ST",
        "SV",
        "SX",
        "SY",
        "SZ",
        "TC",
        "TD",
        "TF",
        "TG",
        "TH",
        "TJ",
        "TK",
        "TL",
        "TM",
        "TN",
        "TO",
        "TR",
        "TT",
        "TV",
        "TW",
        "TZ",
        "UA",
        "UG",
        "UM",
        "US",
        "UY",
        "UZ",
        "VA",
        "VC",
        "VE",
        "VG",
        "VI",
        "VN",
        "VU",
        "WF",
        "WS",
        "YE",
        "YT",
        "ZA",
        "ZM",
        "ZW",
    ]
)

# The countries a shipped calendar is actually for. Every other ISO alpha-2
# code must resolve to DEFAULT: no calendar in the table is that country's, and
# the neutral week is the honest answer rather than a neighbour's week.
EXPECTED_CALENDAR_BY_COUNTRY = {
    "US": "US",
    "GB": "UK",
    "DE": "DACH",
    "AT": "DACH",
    "CH": "DACH",
    "CA": "CANADA",
    "FR": "FRANCE",
    "ES": "SPAIN",
    "BR": "BRAZIL",
    "RU": "RU",
    "TR": "TURKEY",
    # The Gulf is two calendars, not one. Five of the six GCC states work Sunday
    # to Thursday; the UAE moved to a Monday-Friday week on 1 January 2022 and is
    # the only one that did, so it cannot share an entry with its neighbours.
    "AE": "UAE",
    "SA": "GULF",
    "QA": "GULF",
    "BH": "GULF",
    "KW": "GULF",
    "OM": "GULF",
    "CN": "CHINA",
    "IN": "INDIA",
}

# Region ids the CWICR v3 catalogue ships today, for countries where the ISO
# head and the superseded language head disagree.
SHIPPED_CATALOGUE_REGIONS = {
    "AR_BUENOSAIRES": "DEFAULT",
    "PT_LISBON": "DEFAULT",
    "CA_TORONTO": "CANADA",
    "BR_SAOPAULO": "BRAZIL",
    "AE_DUBAI": "UAE",
    "ES_MADRID": "SPAIN",
    "GB_LONDON": "UK",
    "IN_MUMBAI": "INDIA",
    "DE_BERLIN": "DACH",
    "RU_MOSCOW": "RU",
    "FR_PARIS": "FRANCE",
}

# Human-readable region labels. Projects carry these instead of a code.
EXPECTED_CALENDAR_BY_LABEL = {
    "United States": "US",
    "United Kingdom": "UK",
    "Middle East": "GULF",
    "United Arab Emirates": "UAE",
    # Not the United States. The bare "UNITED" head sent every "United ..."
    # label that was neither States nor Kingdom to the American calendar.
    "United Republic of Tanzania": "DEFAULT",
    "France": "FRANCE",
}

# Population floors. If the table shrinks below these the sweeps above stop
# covering what they were written to cover, and that must fail loudly rather
# than pass vacuously.
_MIN_CALENDARS = 12
_MIN_MAPPED_COUNTRIES = 18

# Monday 2026-04-06 through Saturday 2026-04-11. One Saturday, no Sunday, so a
# six-day week answers 6 and a five-day week answers 5.
_WEEK_START = "2026-04-06"
_WEEK_END_SATURDAY = "2026-04-11"


def _calendar_name(calendar: dict) -> str:
    """Name the calendar a resolver answer came from, by its unique label."""
    by_label = {entry["label"]: key for key, entry in WORK_CALENDARS.items()}
    return by_label.get(calendar["label"], f"<unknown: {calendar['label']}>")


def _sweep_iso_codes(expected_by_country: dict[str, str]) -> list[str]:
    """Resolve every ISO alpha-2 code and report the ones that answer wrongly."""
    offenders = []
    for code in sorted(ISO_3166_ALPHA2):
        want = expected_by_country.get(code, "DEFAULT")
        got = _calendar_name(get_work_calendar(code))
        if got != want:
            offenders.append(f"  {code}: resolves to {got}, must be {want}")
    return offenders


def test_the_table_is_still_big_enough_to_be_worth_sweeping() -> None:
    """Population floor, so a shrunken table cannot make the sweeps vacuous."""
    assert len(WORK_CALENDARS) >= _MIN_CALENDARS, (
        f"WORK_CALENDARS holds {len(WORK_CALENDARS)}, floor is {_MIN_CALENDARS}"
    )
    assert "DEFAULT" in WORK_CALENDARS, "WORK_CALENDARS has no DEFAULT to fall back to"
    assert len(EXPECTED_CALENDAR_BY_COUNTRY) >= _MIN_MAPPED_COUNTRIES
    labels = [entry["label"] for entry in WORK_CALENDARS.values()]
    assert len(labels) == len(set(labels)), f"labels are not unique, so _calendar_name cannot name an answer: {labels}"


def test_argentina_gets_an_argentine_working_week() -> None:
    """AR is Argentina, not Arabic. Five 8-hour days, and Saturday is not one."""
    calendar = get_work_calendar("AR")
    assert calendar["work_days"] == {0, 1, 2, 3, 4}, (
        f"AR resolves to the {_calendar_name(calendar)} calendar, whose week is {sorted(calendar['work_days'])}. "
        "Argentina works Monday to Friday."
    )
    assert 5 not in calendar["work_days"], "Saturday is not an Argentine working day"
    assert calendar["hours_per_day"] == 8, (
        f"AR resolves to {calendar['hours_per_day']}h/day via {_calendar_name(calendar)}"
    )


def test_portugal_gets_a_portuguese_working_week() -> None:
    """PT is Portugal, not Portuguese. Five days, not the Brazilian six."""
    calendar = get_work_calendar("PT")
    assert calendar["work_days"] == {0, 1, 2, 3, 4}, (
        f"PT resolves to the {_calendar_name(calendar)} calendar, whose week is {sorted(calendar['work_days'])}. "
        "Portugal works Monday to Friday."
    )
    assert 5 not in calendar["work_days"], "Saturday is not a Portuguese working day"


def test_canada_is_reachable_by_its_country_code() -> None:
    """A Canada calendar ships. Before this change no country code reached it."""
    assert _calendar_name(get_work_calendar("CA")) == "CANADA"


def test_no_iso_country_code_resolves_to_another_countrys_calendar() -> None:
    """The census, as a gate: sweep all of ISO 3166-1 alpha-2, not a sample."""
    offenders = _sweep_iso_codes(EXPECTED_CALENDAR_BY_COUNTRY)
    assert offenders == [], (
        f"{len(offenders)} of {len(ISO_3166_ALPHA2)} ISO country codes resolve to a calendar that is not "
        "their country's:\n" + "\n".join(offenders)
    )


def test_the_sweep_can_fail() -> None:
    """Negative control: the sweep must report a wrong expectation as an offender.

    Without this, a sweep that silently stopped resolving anything would pass.
    It corrupts a local copy of the expectation, never the shipped table, because
    this tree is shared with other agents running tests against it.
    """
    corrupted = dict(EXPECTED_CALENDAR_BY_COUNTRY)
    corrupted["FR"] = "CHINA"  # France does not use the Chinese calendar
    offenders = _sweep_iso_codes(corrupted)
    assert any(line.strip().startswith("FR:") for line in offenders), (
        "the sweep did not notice a deliberately wrong expectation, so a clean run of it proves nothing"
    )


def test_shipped_catalogue_regions_resolve_to_their_own_country() -> None:
    """Drive the real region ids the CWICR v3 catalogue ships, not invented ones."""
    offenders = []
    for region, want in sorted(SHIPPED_CATALOGUE_REGIONS.items()):
        got = _calendar_name(get_work_calendar(region))
        if got != want:
            offenders.append(f"  {region}: resolves to {got}, must be {want}")
    assert offenders == [], "shipped catalogue region ids resolve to the wrong calendar:\n" + "\n".join(offenders)


def test_region_labels_resolve_to_their_own_country() -> None:
    """A label starting with 'United' is not automatically the United States."""
    offenders = []
    for label, want in sorted(EXPECTED_CALENDAR_BY_LABEL.items()):
        got = _calendar_name(get_work_calendar(label))
        if got != want:
            offenders.append(f"  {label!r}: resolves to {got}, must be {want}")
    assert offenders == [], "region labels resolve to the wrong calendar:\n" + "\n".join(offenders)


def test_duration_over_a_saturday_is_five_days_in_argentina_and_portugal() -> None:
    """The harm, at the consumer: compute_duration is what counts the days."""
    assert compute_duration(_WEEK_START, _WEEK_END_SATURDAY, "AR") == 5, (
        "Monday to Saturday is five working days in Argentina; a six-day answer means the Gulf calendar was applied"
    )
    assert compute_duration(_WEEK_START, _WEEK_END_SATURDAY, "PT") == 5, (
        "Monday to Saturday is five working days in Portugal; a six-day answer means the Brazilian calendar was applied"
    )
    assert compute_duration(_WEEK_START, _WEEK_END_SATURDAY, "AR_BUENOSAIRES") == 5
    assert compute_duration(_WEEK_START, _WEEK_END_SATURDAY, "PT_LISBON") == 5


def test_the_six_day_countries_still_count_six() -> None:
    """Guard against fixing the above by flattening every week to Monday-Friday.

    These three plan a six-day site week on purpose, and the table says so in
    its own comments. The Gulf states are deliberately not in this list: they
    were only ever six-day because one calendar served the whole region, and
    ``test_the_gulf_week_runs_sunday_to_thursday_at_the_consumer`` is what holds
    their week still now.
    """
    assert compute_duration(_WEEK_START, _WEEK_END_SATURDAY, "BR") == 6, "Brazil works Saturdays"
    assert compute_duration(_WEEK_START, _WEEK_END_SATURDAY, "CN") == 6, "China works Saturdays"
    assert compute_duration(_WEEK_START, _WEEK_END_SATURDAY, "IN") == 6, "India works Saturdays"
    assert compute_duration(_WEEK_START, _WEEK_END_SATURDAY, "US") == 5
    assert compute_duration(_WEEK_START, _WEEK_END_SATURDAY, "FR") == 5


def test_the_gulf_week_runs_sunday_to_thursday_at_the_consumer() -> None:
    """The harm this split repairs, measured where the days are counted.

    Friday is the statutory weekly rest day in the Gulf states that work Sunday
    to Thursday, and Sunday is an ordinary working day. A calendar that works
    Friday and rests Sunday is not a longer week or a shorter one, it is the
    weekend on the wrong days, and a duration still comes back as a plausible
    number either way. Only the day the span starts on tells the two apart.
    """
    sunday, saturday = "2026-04-05", "2026-04-11"

    for country in ("SA", "QA", "KW", "BH", "OM"):
        assert compute_duration(_WEEK_START, _WEEK_END_SATURDAY, country) == 4, (
            f"{country}: Monday to Saturday is four working days where the week is Sunday to Thursday; "
            "a six-day answer means Friday and Saturday are being worked"
        )
        assert compute_duration(sunday, saturday, country) == 5, (
            f"{country}: Sunday through Saturday is five working days; a four-day answer means Sunday, "
            "an ordinary working day here, is being treated as the weekend"
        )

    # The UAE left that week on 1 January 2022 and is the reason one Gulf entry
    # could not stay one entry.
    assert compute_duration(_WEEK_START, _WEEK_END_SATURDAY, "AE") == 5, "the UAE works Monday to Friday"
    assert compute_duration(sunday, saturday, "AE") == 5, "the UAE rests Sunday"


def test_shape_proves_which_structure_the_arithmetic_reads() -> None:
    """Four structures describe a working week here. Only one is consulted.

    Pin the distinguishing fields, so a later reader cannot put an assertion on
    a structure that computes nothing.
    """
    for key, entry in WORK_CALENDARS.items():
        assert set(entry) >= {"hours_per_day", "work_days", "label"}, f"{key} is missing a field the consumers read"
        assert "work_hours_per_day" not in entry, f"{key} uses the i18n field name, which nothing in schedule reads"
        assert entry["work_days"] <= {0, 1, 2, 3, 4, 5, 6}, f"{key} declares a weekday outside Monday=0..Sunday=6"
        assert 0 in entry["work_days"], f"{key} does not work Monday, which no shipped calendar intends"

    # Read-only: this structure belongs to another change in flight. It is a
    # bare frozenset of weekdays, so it carries no hours and cannot be what
    # compute_duration reads.
    from app.core.calendar import _WORKING_WEEK

    assert _WORKING_WEEK, "core.calendar._WORKING_WEEK is empty"
    sample = next(iter(_WORKING_WEEK.values()))
    assert isinstance(sample, frozenset), "core.calendar._WORKING_WEEK changed shape; re-check which structure is read"


def test_the_two_keyspaces_are_held_apart() -> None:
    """The structural fix, not just its effect.

    A head that is not an ISO country code (``ZH``, ``HI``, ``SP``, ``ENG``,
    ``USA``) belongs in its own table. If one dict holds both, a language head
    can shadow a country again the next time one is added, and nothing here
    would notice until the country resolved wrongly.
    """
    country_table = getattr(schedule_service, "_CALENDAR_BY_COUNTRY", None)
    legacy_table = getattr(schedule_service, "_CALENDAR_BY_LEGACY_HEAD", None)
    assert country_table is not None, "no _CALENDAR_BY_COUNTRY: the country keyspace is not held on its own"
    assert legacy_table is not None, "no _CALENDAR_BY_LEGACY_HEAD: the superseded heads are not held on their own"

    intruders = sorted(set(legacy_table) & ISO_3166_ALPHA2)
    assert intruders == [], (
        f"{intruders} are ISO 3166-1 country codes sitting in the superseded-head table. "
        "That is exactly the confusion this split exists to prevent."
    )
    strangers = sorted(set(country_table) - ISO_3166_ALPHA2)
    assert strangers == [], f"{strangers} are in the country table but are not ISO 3166-1 alpha-2 codes"

    # Order of consultation cannot matter if the keyspaces never overlap, which
    # is the property that makes the split a fix rather than a reshuffle.
    assert not (set(country_table) & set(legacy_table)), "the two tables share a key, so precedence decides the answer"

    # The third keyspace: the calendar keys themselves, which a project may
    # carry directly and which are matched before either table is consulted. A
    # key that is a two-letter ISO code therefore outranks the country table,
    # so it has to agree with it. US, UK and RU are safe today - two of them
    # agree and UK is not an assigned ISO code - but this is the same class of
    # confusion at the one door the disjointness checks above do not cover.
    for key in WORK_CALENDARS:
        if key in ISO_3166_ALPHA2:
            assert country_table.get(key) == key, (
                f"calendar key {key!r} is an ISO 3166-1 country code, so it is matched before the country "
                f"table and outranks it, but the country table maps {key} to {country_table.get(key)!r}"
            )
