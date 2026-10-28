"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the framework-free accommodation intl helpers.

Pure Decimal / date / string math, no database and no FastAPI, so this file
runs on its own without any fixtures. Covers the international guarantees:
Decimal-exact money, no currency blending, ISO 8601 dates, zero guards, and
localised status labels with an English fallback.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.accommodation import intl

# ── Stay length: nights and bed-nights ────────────────────────────────────────


def test_nights_between_counts_whole_nights() -> None:
    assert intl.nights_between("2026-07-01", "2026-07-05") == 4


def test_nights_between_same_day_is_zero() -> None:
    assert intl.nights_between("2026-07-01", "2026-07-01") == 0


def test_nights_between_accepts_date_objects() -> None:
    assert intl.nights_between(date(2026, 7, 1), date(2026, 7, 3)) == 2


def test_nights_between_rejects_reversed_dates() -> None:
    with pytest.raises(ValueError, match="must not precede"):
        intl.nights_between("2026-07-05", "2026-07-01")


def test_nights_between_rejects_bad_date() -> None:
    with pytest.raises(ValueError, match="ISO 8601"):
        intl.nights_between("not-a-date", "2026-07-05")


def test_bed_nights_multiplies_people_by_nights() -> None:
    # 3 people, 4 nights = 12 person-nights.
    assert intl.bed_nights(3, "2026-07-01", "2026-07-05") == 12


def test_bed_nights_zero_occupants_is_zero() -> None:
    assert intl.bed_nights(0, "2026-07-01", "2026-07-05") == 0


def test_bed_nights_same_day_is_zero() -> None:
    assert intl.bed_nights(5, "2026-07-01", "2026-07-01") == 0


def test_bed_nights_rejects_negative_occupants() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        intl.bed_nights(-1, "2026-07-01", "2026-07-05")


def test_bed_nights_rejects_fractional_occupants() -> None:
    with pytest.raises(ValueError, match="whole number"):
        intl.bed_nights("2.5", "2026-07-01", "2026-07-05")


# ── Cost math (Decimal-exact) ─────────────────────────────────────────────────


def test_total_accommodation_cost_rate_times_person_nights() -> None:
    # 25.50 per person-night * 12 person-nights = 306.00.
    assert intl.total_accommodation_cost("25.50", 12) == Decimal("306.00")


def test_total_accommodation_cost_is_decimal_exact() -> None:
    # 0.1 * 3 must be exactly 0.30, not 0.30000000000000004 (float drift).
    result = intl.total_accommodation_cost("0.10", 3)
    assert result == Decimal("0.30")
    assert isinstance(result, Decimal)


def test_total_accommodation_cost_zero_nights_is_zero() -> None:
    assert intl.total_accommodation_cost("99.99", 0) == Decimal("0.00")


def test_total_accommodation_cost_rejects_negative_rate() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        intl.total_accommodation_cost("-5", 3)


def test_total_accommodation_cost_rejects_nan() -> None:
    with pytest.raises(ValueError, match="finite"):
        intl.total_accommodation_cost("NaN", 3)


def test_cost_per_person_night_divides() -> None:
    assert intl.cost_per_person_night("306.00", 12) == Decimal("25.50")


def test_cost_per_person_night_zero_guard() -> None:
    # Zero person-nights: well-defined zero, never a division-by-zero crash.
    assert intl.cost_per_person_night("100.00", 0) == Decimal("0.00")


def test_cost_per_person_night_rounds_half_up() -> None:
    # 100 / 3 = 33.333... -> 33.33 at two decimals.
    assert intl.cost_per_person_night("100.00", 3) == Decimal("33.33")


# ── Stay cost breakdown (explainable components) ──────────────────────────────


def test_stay_cost_breakdown_components() -> None:
    report = intl.stay_cost_breakdown("30.00", 2, "2026-07-01", "2026-07-06", "USD")
    assert report["occupants"] == "2"
    assert report["nights"] == "5"
    assert report["bed_nights"] == "10"
    assert report["rate_per_person_night"] == "30.00"
    assert report["rate_unit"] == "per person per night"
    assert report["currency"] == "USD"
    assert report["total_cost"] == "300.00"
    assert report["cost_per_person_night"] == "30.00"


def test_stay_cost_breakdown_currency_not_guessed() -> None:
    report = intl.stay_cost_breakdown("30.00", 1, "2026-07-01", "2026-07-02", None)
    # No currency stated stays empty; we never default to EUR/USD.
    assert report["currency"] == ""


def test_stay_cost_breakdown_normalizes_currency() -> None:
    report = intl.stay_cost_breakdown("10", 1, "2026-07-01", "2026-07-02", " eur ")
    assert report["currency"] == "EUR"


# ── Occupancy rate (zero-capacity guard) ──────────────────────────────────────


def test_occupancy_rate_half_full() -> None:
    report = intl.occupancy_rate(5, 10)
    assert report["rate"] == "0.5000"
    assert report["rate_percent"] == "50.00"
    assert report["vacant"] == "5"
    assert report["is_full"] == "false"
    assert report["overbooked"] == "false"


def test_occupancy_rate_full() -> None:
    report = intl.occupancy_rate(10, 10)
    assert report["rate"] == "1.0000"
    assert report["is_full"] == "true"
    assert report["overbooked"] == "false"


def test_occupancy_rate_zero_capacity_guard() -> None:
    # Zero capacity must not divide by zero; rate is a well-defined 0.
    report = intl.occupancy_rate(0, 0)
    assert report["rate"] == "0.0000"
    assert report["vacant"] == "0"
    assert report["is_full"] == "false"


def test_occupancy_rate_overbooked_caps_at_one() -> None:
    report = intl.occupancy_rate(12, 10)
    assert report["rate"] == "1.0000"
    assert report["overbooked"] == "true"
    assert report["vacant"] == "0"


def test_occupancy_rate_rejects_negative() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        intl.occupancy_rate(-1, 10)


# ── Currency safety ───────────────────────────────────────────────────────────


def test_ensure_single_currency_agrees() -> None:
    assert intl.ensure_single_currency(["USD", "usd", None, ""]) == "USD"


def test_ensure_single_currency_empty_is_blank() -> None:
    assert intl.ensure_single_currency([None, "", "  "]) == ""


def test_ensure_single_currency_rejects_mix() -> None:
    with pytest.raises(ValueError, match="different currencies"):
        intl.ensure_single_currency(["USD", "EUR"])


def test_normalize_currency_never_guesses() -> None:
    assert intl.normalize_currency(None) == ""
    assert intl.normalize_currency("  gbp ") == "GBP"


# ── Localised status labels (en/de/ru + English fallback) ─────────────────────


def test_describe_room_status_english() -> None:
    assert intl.describe_room_status("maintenance") == "Under maintenance"


def test_describe_room_status_german() -> None:
    assert intl.describe_room_status("maintenance", "de") == "In Wartung"


def test_describe_room_status_russian() -> None:
    assert intl.describe_room_status("occupied", "ru") == "Занято"


def test_describe_booking_status_localized() -> None:
    assert intl.describe_booking_status("checked_in", "de") == "Eingecheckt"
    assert intl.describe_booking_status("checked_in", "ru") == "Заселен"
    assert intl.describe_booking_status("checked_in") == "Checked in"


def test_describe_charge_status_localized() -> None:
    assert intl.describe_charge_status("paid", "de") == "Bezahlt"
    assert intl.describe_charge_status("paid", "ru") == "Оплачено"


def test_describe_kind_localized() -> None:
    assert intl.describe_kind("worker_camp") == "Worker camp"
    assert intl.describe_kind("worker_camp", "ru") == "Рабочий городок"


def test_unknown_locale_falls_back_to_english() -> None:
    # A locale we do not carry gets the English label, never a raw code.
    assert intl.describe_room_status("available", "zh") == "Available"


def test_locale_region_suffix_is_stripped() -> None:
    assert intl.describe_room_status("available", "de-CH") == "Verfügbar"


def test_unknown_code_is_humanised_not_blank() -> None:
    # A status a newer module introduced still renders readably.
    assert intl.describe_booking_status("no_show") == "No show"


def test_missing_code_is_localized_unknown() -> None:
    assert intl.describe_booking_status(None) == "Unknown"
    assert intl.describe_booking_status(None, "de") == "Unbekannt"
    assert intl.describe_booking_status("", "ru") == "Неизвестно"


# ── Glossary ──────────────────────────────────────────────────────────────────


def test_explain_known_concept() -> None:
    text = intl.explain("occupancy_rate")
    assert "occupied" in text.lower()


def test_explain_unknown_concept_raises() -> None:
    with pytest.raises(ValueError, match="Unknown accommodation concept"):
        intl.explain("nope")
