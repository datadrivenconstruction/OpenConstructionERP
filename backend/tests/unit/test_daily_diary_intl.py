"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the international, unit-safe daily-diary helpers.

These cover the pure functions in ``app.modules.daily_diary.intl``: no
database, no network. They pin the international robustness (unit and
locale neutrality), clarity (plain-language labels), edge-case safety
(division by zero, negatives, empty input, no NaN/inf), and
explainability (components exposed) contracts.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.modules.daily_diary.intl import (
    DEFAULT_WEATHER_DELAY_THRESHOLD,
    WeatherDelayThreshold,
    average_labour_hours_per_worker,
    celsius_to_fahrenheit,
    daily_summary_line,
    describe_delay_cause,
    describe_weather_condition,
    explain_concept,
    fahrenheit_to_celsius,
    format_temperature,
    humanize_code,
    labour_rollup,
    normalize_temperature,
    plant_utilization,
    to_iso_date,
    weather_delay_assessment,
)

# ── Temperature: accept C or F, store canonical Celsius ───────────────────


def test_celsius_fahrenheit_round_trip() -> None:
    assert celsius_to_fahrenheit(0.0) == pytest.approx(32.0)
    assert celsius_to_fahrenheit(100.0) == pytest.approx(212.0)
    assert fahrenheit_to_celsius(32.0) == pytest.approx(0.0)
    assert fahrenheit_to_celsius(212.0) == pytest.approx(100.0)


def test_normalize_temperature_celsius_is_identity() -> None:
    assert normalize_temperature(20.0, "C") == pytest.approx(20.0)
    assert normalize_temperature(20.0, "Celsius") == pytest.approx(20.0)


def test_normalize_temperature_fahrenheit_becomes_celsius() -> None:
    # 68 F is 20 C - canonical storage is always Celsius.
    assert normalize_temperature(68.0, "F") == pytest.approx(20.0)
    assert normalize_temperature(68.0, "fahrenheit") == pytest.approx(20.0)


def test_normalize_temperature_rejects_unknown_unit() -> None:
    with pytest.raises(ValueError, match="Unknown temperature unit"):
        normalize_temperature(20.0, "kelvin")


def test_normalize_temperature_rejects_non_numeric() -> None:
    with pytest.raises(ValueError):
        normalize_temperature("hot", "C")


def test_format_temperature_in_both_units() -> None:
    assert format_temperature(20.0, "C") == "20.0 C"
    # 20 C displays as 68 F without changing the stored Celsius value.
    assert format_temperature(20.0, "F") == "68.0 F"


def test_format_temperature_rejects_unknown_unit() -> None:
    with pytest.raises(ValueError):
        format_temperature(20.0, "R")


# ── Labour rollup: headcount and person-hours ─────────────────────────────


def test_labour_rollup_sums_person_hours() -> None:
    result = labour_rollup(
        [
            {"headcount": 10, "hours": 8, "company": "Alpha"},
            {"headcount": 2, "hours": 4, "company": "Beta"},
        ],
    )
    assert result["total_headcount"] == 12
    # 10*8 + 2*4 = 88 person-hours
    assert result["total_labour_hours"] == pytest.approx(88.0)
    assert result["hour_unit"] == "hours"
    assert len(result["components"]) == 2
    assert result["components"][0]["labour_hours"] == pytest.approx(80.0)


def test_labour_rollup_empty_is_zero_not_error() -> None:
    result = labour_rollup([])
    assert result["total_headcount"] == 0
    assert result["total_labour_hours"] == 0.0
    assert result["components"] == []


def test_labour_rollup_rejects_negative_headcount() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        labour_rollup([{"headcount": -3, "hours": 8}])


def test_labour_rollup_rejects_fractional_headcount() -> None:
    with pytest.raises(ValueError, match="whole count"):
        labour_rollup([{"headcount": 3.5, "hours": 8}])


def test_labour_rollup_rejects_negative_hours() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        labour_rollup([{"headcount": 3, "hours": -2}])


def test_labour_rollup_accepts_objects() -> None:
    from types import SimpleNamespace

    result = labour_rollup([SimpleNamespace(headcount=5, hours=8, label="Crew")])
    assert result["total_labour_hours"] == pytest.approx(40.0)
    assert result["components"][0]["label"] == "Crew"


def test_average_labour_hours_per_worker_guards_zero_crew() -> None:
    # Zero crew must not divide by zero; a well-defined 0.0 is returned.
    assert average_labour_hours_per_worker(0.0, 0) == 0.0


def test_average_labour_hours_per_worker_normal() -> None:
    assert average_labour_hours_per_worker(88.0, 12) == pytest.approx(7.3333, abs=0.001)


# ── Plant utilization: working vs idle ────────────────────────────────────


def test_plant_utilization_normal() -> None:
    result = plant_utilization(6.0, 2.0)
    assert result["utilization"] == pytest.approx(0.75)
    assert result["utilization_pct"] == pytest.approx(75.0)
    assert result["total_hours"] == pytest.approx(8.0)
    assert result["has_hours"] is True


def test_plant_utilization_zero_hours_is_well_defined() -> None:
    # No hours logged - utilization is 0.0, not NaN, and flagged.
    result = plant_utilization(0.0, 0.0)
    assert result["utilization"] == 0.0
    assert result["has_hours"] is False


def test_plant_utilization_rejects_negative() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        plant_utilization(-1.0, 2.0)


def test_plant_utilization_fully_idle() -> None:
    result = plant_utilization(0.0, 8.0)
    assert result["utilization"] == 0.0
    assert result["has_hours"] is True


# ── Weather delay: data-driven threshold ──────────────────────────────────


def test_weather_delay_flags_heavy_rain() -> None:
    result = weather_delay_assessment(precipitation_mm=30.0)
    assert result["lost"] is True
    assert any("precipitation" in r for r in result["reasons"])


def test_weather_delay_within_limits() -> None:
    result = weather_delay_assessment(
        temperature_c=18.0,
        precipitation_mm=2.0,
        wind_speed_kmh=10.0,
    )
    assert result["lost"] is False
    assert result["reasons"] == []


def test_weather_delay_is_climate_neutral_when_limit_unset() -> None:
    # A hot-climate threshold that sets no lower temperature limit must
    # never flag cold on its own.
    hot_climate = WeatherDelayThreshold(max_temp_c=48.0, max_precipitation_mm=30.0)
    result = weather_delay_assessment(temperature_c=-5.0, threshold=hot_climate)
    assert result["lost"] is False


def test_weather_delay_custom_threshold_low_temp() -> None:
    cold_site = WeatherDelayThreshold(min_temp_c=0.0)
    result = weather_delay_assessment(temperature_c=-3.0, threshold=cold_site)
    assert result["lost"] is True
    assert any("below" in r for r in result["reasons"])


def test_weather_delay_reports_threshold_and_components() -> None:
    result = weather_delay_assessment(precipitation_mm=30.0, wind_speed_kmh=70.0)
    assert result["components"]["precipitation_mm"] == pytest.approx(30.0)
    assert result["components"]["wind_speed_kmh"] == pytest.approx(70.0)
    assert result["components"]["temperature_c"] is None
    assert result["threshold"] == DEFAULT_WEATHER_DELAY_THRESHOLD.as_dict()


def test_weather_delay_rejects_negative_precipitation() -> None:
    with pytest.raises(ValueError):
        weather_delay_assessment(precipitation_mm=-5.0)


def test_weather_delay_no_measures_is_not_lost() -> None:
    result = weather_delay_assessment()
    assert result["lost"] is False


# ── ISO 8601 date handling ────────────────────────────────────────────────


def test_to_iso_date_from_various_inputs() -> None:
    assert to_iso_date(date(2026, 4, 10)) == "2026-04-10"
    assert to_iso_date(datetime(2026, 4, 10, 9, 0, tzinfo=UTC)) == "2026-04-10"
    assert to_iso_date("2026-04-10") == "2026-04-10"
    assert to_iso_date("2026-04-10T09:00:00Z") == "2026-04-10"


def test_to_iso_date_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        to_iso_date("not-a-date")


# ── Plain-language labels and explanations ────────────────────────────────


def test_explain_concept_known() -> None:
    assert "person-hours" in explain_concept("labour_hours")
    assert "idle" in explain_concept("plant_idle")


def test_explain_concept_unknown_has_fallback() -> None:
    # Never raises - a UI can call it for any label.
    text = explain_concept("some_new_field")
    assert "Some new field" in text


def test_humanize_code() -> None:
    assert humanize_code("rain_heavy") == "Rain heavy"
    assert humanize_code("equipment-breakdown") == "Equipment breakdown"
    assert humanize_code("") == ""


def test_describe_weather_condition() -> None:
    assert describe_weather_condition("rain_heavy") == "Heavy rain"
    assert describe_weather_condition("") == "Not recorded"
    # Unknown code falls back to a humanized label, never a raw token.
    assert describe_weather_condition("sandstorm") == "Sandstorm"


def test_describe_delay_cause() -> None:
    assert describe_delay_cause("materials") == "Waiting on materials"
    assert describe_delay_cause("") == "Not recorded"
    assert describe_delay_cause("custom_cause") == "Custom cause"


# ── Daily summary line ────────────────────────────────────────────────────


def test_daily_summary_line_basic() -> None:
    line = daily_summary_line(diary_date="2026-04-10", headcount=12, labour_hours=88.0)
    assert line == "2026-04-10: 12 workers on site, 88.0 labour hours."


def test_daily_summary_line_singular_worker() -> None:
    line = daily_summary_line(diary_date="2026-04-10", headcount=1, labour_hours=8.0)
    assert "1 worker on site" in line


def test_daily_summary_line_with_plant_and_weather() -> None:
    plant = plant_utilization(6.0, 2.0)
    weather = weather_delay_assessment(precipitation_mm=30.0)
    line = daily_summary_line(
        diary_date=datetime(2026, 4, 10, tzinfo=UTC),
        headcount=12,
        labour_hours=88.0,
        plant=plant,
        weather_delay=weather,
    )
    assert "plant 75.0% utilized" in line
    assert "working day lost" in line


def test_daily_summary_line_weather_within_limits() -> None:
    weather = weather_delay_assessment(temperature_c=18.0, precipitation_mm=1.0)
    line = daily_summary_line(
        diary_date="2026-04-10",
        headcount=5,
        labour_hours=40.0,
        weather_delay=weather,
    )
    assert "within working limits" in line


def test_daily_summary_line_rejects_negative_headcount() -> None:
    with pytest.raises(ValueError):
        daily_summary_line(diary_date="2026-04-10", headcount=-1, labour_hours=8.0)
