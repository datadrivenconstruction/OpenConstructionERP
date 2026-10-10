"""The shipped PT/2026 dates must reach the runtime without covering other years.

The date roster is the existing sourced seed, not a new legal interpretation;
its delivery regression independently pins the same thirteen national dates.
No municipal days, substitute Mondays or future-year dates are inferred here.
"""

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from app.core import calendar as cal
from app.core.provenance import Source

SEED_PATH = Path(cal.__file__).resolve().parents[1] / "modules/i18n_foundation/seed_data/work_calendars.json"

EXPECTED_DATES = frozenset(
    date.fromisoformat(value)
    for value in (
        "2026-01-01",
        "2026-04-03",
        "2026-04-05",
        "2026-04-25",
        "2026-05-01",
        "2026-06-04",
        "2026-06-10",
        "2026-08-15",
        "2026-10-05",
        "2026-11-01",
        "2026-12-01",
        "2026-12-08",
        "2026-12-25",
    )
)


@pytest.fixture(autouse=True)
def isolated_holiday_cache():
    cal._holiday_cache.clear()
    yield
    cal._holiday_cache.clear()


@pytest.mark.parametrize("country", ["PT", "pt", " PT "])
def test_portugal_2026_runtime_answers_with_its_exact_shipped_dates(country):
    answer = cal.resolve_holidays(country, 2026)
    assert answer["dates"] == EXPECTED_DATES
    for axis, requested in (
        ("jurisdiction", "PT"),
        ("effective_year", "2026"),
        ("holiday_extent", "PT"),
    ):
        assert answer[axis].source is Source.DECLARED
        assert answer[axis].requested == answer[axis].used == requested
    assert answer["year"] == 2026
    assert answer["omitted"] == answer["placeholder_spans"] == ()


def test_portugal_day_is_excluded_but_the_next_ordinary_weekday_still_works():
    assert cal.is_working_day(date(2026, 6, 10), "PT") is False
    assert cal.next_working_day(date(2026, 6, 10), "PT") == date(2026, 6, 11)
    assert cal.is_working_day(date(2026, 6, 11), "PT") is True
    # This bridge covers holidays; it does not assert a statutory working week.
    assert "PT" not in cal._WORKING_WEEK


@pytest.mark.parametrize("year", [2025, 2027])
def test_an_unshipped_portugal_year_keeps_the_existing_unknown_jurisdiction(year):
    answer = cal.resolve_holidays("PT", year)
    assert answer["dates"] == frozenset()
    assert answer["jurisdiction"].source is Source.FALLBACK
    assert answer["jurisdiction"].requested == "PT"
    assert answer["jurisdiction"].used == cal.NO_PUBLIC_HOLIDAYS
    assert answer["jurisdiction"].answered is False
    # Preserve the existing no-table response rather than inventing year coverage.
    assert answer["effective_year"].source is Source.DECLARED
    assert answer["effective_year"].requested == str(year)
    assert answer["holiday_extent"].source is Source.DECLARED
    assert answer["omitted"] == answer["placeholder_spans"] == ()


@pytest.mark.parametrize("country", ["BE", "IE"])
def test_the_portugal_bridge_does_not_cover_another_pending_country(country):
    answer = cal.resolve_holidays(country, 2026)
    assert answer["dates"] == frozenset()
    assert answer["jurisdiction"].source is Source.FALLBACK
    assert answer["jurisdiction"].answered is False


def test_a_cached_unshipped_year_does_not_hide_the_shipped_year():
    absent = cal.resolve_holidays("PT", 2027)
    present = cal.resolve_holidays("PT", 2026)
    assert present["dates"] == EXPECTED_DATES
    assert present["jurisdiction"].answered is True
    assert cal.resolve_holidays("PT", 2027) is absent
    assert absent["dates"] == frozenset()
    assert absent["jurisdiction"].answered is False


def test_an_explicit_computed_binding_retains_precedence(monkeypatch):
    computed = frozenset({date(2026, 2, 2)})
    monkeypatch.setitem(cal._HOLIDAY_FUNCS, "PT", lambda year: computed)
    assert cal.resolve_holidays("PT", 2026)["dates"] == computed


@pytest.mark.parametrize(
    "damage",
    [
        "missing_file",
        "malformed_json",
        "wrong_root_type",
        "missing_row",
        "wrong_row_year",
        "duplicate_row",
        "empty_roster",
        "wrong_roster_type",
        "wrong_entry_type",
        "unknown_holiday_type",
        "invalid_date",
        "noncanonical_date",
        "wrong_year",
        "wrong_date_type",
        "duplicate_date",
        "missing_date",
        "extra_date",
    ],
)
def test_broken_expected_seed_is_not_an_empty_calendar_or_a_cached_failure(monkeypatch, damage):
    original_text = SEED_PATH.read_text(encoding="utf-8")
    rows = json.loads(original_text)
    portugal = next(row for row in rows if row["country_code"] == "PT")
    if damage == "wrong_root_type":
        rows = {"calendars": rows}
    elif damage == "missing_row":
        rows.remove(portugal)
    elif damage == "wrong_row_year":
        portugal["year"] = "2027"
    elif damage == "duplicate_row":
        rows.append(copy.deepcopy(portugal))
    elif damage == "empty_roster":
        portugal["exceptions"] = []
    elif damage == "wrong_roster_type":
        portugal["exceptions"] = {}
    elif damage == "wrong_entry_type":
        portugal["exceptions"][0] = "2026-01-01"
    elif damage == "unknown_holiday_type":
        portugal["exceptions"][0]["type"] = "unknown_holiday"
    elif damage == "invalid_date":
        portugal["exceptions"][0]["date"] = "2026-02-30"
    elif damage == "noncanonical_date":
        portugal["exceptions"][0]["date"] = "20260101"
    elif damage == "wrong_year":
        portugal["exceptions"][0]["date"] = "2027-01-01"
    elif damage == "wrong_date_type":
        portugal["exceptions"][0]["date"] = 20260101
    elif damage == "duplicate_date":
        portugal["exceptions"][-1] = copy.deepcopy(portugal["exceptions"][0])
    elif damage == "missing_date":
        portugal["exceptions"].pop()
    elif damage == "extra_date":
        portugal["exceptions"].append({"date": "2026-02-02", "type": "public_holiday"})
    payload = "not JSON" if damage == "malformed_json" else json.dumps(rows)
    current = [payload]
    original_read = Path.read_text

    def read_seed(path, *args, **kwargs):
        if path == SEED_PATH:
            if damage == "missing_file" and current[0] != original_text:
                raise FileNotFoundError(path)
            return current[0]
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_seed)
    for _ in range(2):
        with pytest.raises(cal.HolidayCalculationError) as error:
            cal.resolve_holidays("PT", 2026)
        assert error.value.country_code == "PT"
        assert error.value.year == 2026
        assert ("PT", 2026) not in cal._holiday_cache
    current[0] = original_text
    assert cal.resolve_holidays("PT", 2026)["dates"] == EXPECTED_DATES


def test_a_different_seed_year_is_not_a_duplicate_or_automatically_enabled(monkeypatch):
    rows = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    future = copy.deepcopy(next(row for row in rows if row["country_code"] == "PT"))
    future["year"] = "2027"
    future["exceptions"] = [{"date": "2027-01-01", "type": "public_holiday"}]
    rows.append(future)
    original_read = Path.read_text

    def read_seed(path, *args, **kwargs):
        return json.dumps(rows) if path == SEED_PATH else original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_seed)
    assert cal.resolve_holidays("PT", 2026)["dates"] == EXPECTED_DATES
    future_answer = cal.resolve_holidays("PT", 2027)
    assert future_answer["dates"] == frozenset()
    assert future_answer["jurisdiction"].answered is False


@pytest.mark.parametrize("country, year", [("PT", 2027), ("BE", 2026), ("IE", 2026), ("DE", 2026)])
def test_other_country_years_do_not_open_the_portugal_seed(monkeypatch, country, year):
    original_read = Path.read_text

    def refuse_seed(path, *args, **kwargs):
        if path == SEED_PATH:
            pytest.fail("an unrelated country/year must not open the PT seed")
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", refuse_seed)
    answer = cal.resolve_holidays(country, year)
    assert answer["jurisdiction"].answered is (country == "DE")
