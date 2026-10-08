# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A Canadian project that names its province works the province's holidays.

The federal list was the only Canadian one, so an Ontario schedule worked
Family Day and stopped on Remembrance Day, and a Quebec one worked 24 June.
Each deadline counted across one of those days landed a day off.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.calendar import has_subdivision_holidays, is_working_day, resolve_holidays
from app.modules.schedule.service import get_work_calendar

Y = 2026


def _dates(code: str) -> frozenset[date]:
    return resolve_holidays(code, Y)["dates"]


def test_ontario_keeps_family_day_and_not_remembrance_day() -> None:
    on = _dates("CA-ON")
    assert date(2026, 2, 16) in on  # Family Day
    assert date(2026, 12, 28) in on  # Boxing Day, Saturday 26th moved past Christmas' Monday
    assert date(2026, 11, 11) not in on
    assert date(2026, 9, 30) not in on
    assert date(2026, 2, 16) not in _dates("CA")


def test_quebec_keeps_the_fete_nationale_and_not_boxing_day() -> None:
    qc = _dates("CA-QC")
    assert date(2026, 6, 24) in qc
    assert date(2026, 5, 18) in qc  # National Patriots' Day
    assert date(2026, 2, 16) not in qc
    assert not any(d.month == 12 and d.day > 25 for d in qc)


@pytest.mark.parametrize(
    ("code", "day", "kept"),
    [
        ("CA-BC", date(2026, 8, 3), True),  # BC Day
        ("CA-BC", date(2026, 9, 30), True),
        ("CA-BC", date(2026, 11, 11), True),
        ("CA-AB", date(2026, 11, 11), True),
        ("CA-AB", date(2026, 9, 30), False),
        ("CA-MB", date(2026, 2, 16), True),  # Louis Riel Day
        ("CA-MB", date(2026, 9, 30), True),
        ("CA-MB", date(2026, 11, 11), False),
    ],
)
def test_each_province_has_its_own_days(code: str, day: date, kept: bool) -> None:
    assert (day in _dates(code)) is kept


def test_every_province_list_is_declared_for_the_province() -> None:
    for code in ("CA-ON", "CA-QC", "CA-BC", "CA-AB", "CA-MB"):
        assert has_subdivision_holidays(code)
        assert resolve_holidays(code, Y)["jurisdiction"].answered


def test_a_province_without_a_list_answers_with_the_federal_one_and_says_so() -> None:
    ns = resolve_holidays("CA-NS", Y)
    assert ns["dates"] == _dates("CA")
    assert (ns["jurisdiction"].requested, ns["jurisdiction"].used) == ("CA-NS", "CA")


def test_a_province_works_the_country_week() -> None:
    assert is_working_day(date(2026, 2, 16), "CA")
    assert not is_working_day(date(2026, 2, 16), "CA-ON")
    assert not is_working_day(date(2026, 2, 14), "CA-ON")  # Saturday


def test_the_schedule_calendar_reads_the_project_province() -> None:
    assert get_work_calendar("CA", "CA-QC")["holiday_country"] == "CA-QC"
    assert get_work_calendar("CA", None)["holiday_country"] == "CA"
    # A subdivision of another country, or one with no list, leaves the country.
    assert get_work_calendar("CA", "US-CA")["holiday_country"] == "CA"
    assert get_work_calendar("CA", "CA-NS")["holiday_country"] == "CA"


def test_the_contract_form_asks_for_the_province_only_where_it_matters() -> None:
    from app.modules.contracts.country_defaults import has_subdivision_rows

    assert has_subdivision_rows("CA")
    assert not has_subdivision_rows("DE")
    assert not has_subdivision_rows(None)
