"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-free tests for equipment billing guards and utilization windows."""

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.modules.equipment.models import EquipmentRental
from app.modules.equipment.repository import _busy_days_in_window
from app.modules.equipment.service import _non_negative, compute_rental_billing


def _rental(**kw) -> EquipmentRental:
    base = {
        "equipment_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "start_date": "2026-01-01",
        "internal_rate_per_day": Decimal("200"),
        "internal_rate_per_hour": Decimal("0"),
        "currency": "EUR",
        "status": "active",
    }
    base.update(kw)
    return EquipmentRental(**base)


# ---- _non_negative ---------------------------------------------------------
def test_non_negative_floors_and_coerces():
    assert _non_negative(Decimal("5")) == Decimal("5")
    assert _non_negative("-3") == Decimal("0")
    assert _non_negative(None) == Decimal("0")
    assert _non_negative("garbage") == Decimal("0")
    assert _non_negative(2.5) == Decimal("2.5")


# ---- billing guards --------------------------------------------------------
def test_negative_hours_never_bills_a_credit():
    rental = _rental(internal_rate_per_hour=Decimal("30"))
    # A negative logged-hours value floors to zero, not a negative charge.
    assert compute_rental_billing(rental, "2026-01-01", "2026-01-10", hours_logged=Decimal("-40")) == Decimal("0")


def test_negative_hour_rate_falls_back_to_day_billing():
    rental = _rental(internal_rate_per_hour=Decimal("-30"), internal_rate_per_day=Decimal("200"))
    # Clamped hour rate is not positive, so day billing applies: 10 days * 200.
    assert compute_rental_billing(rental, "2026-01-01", "2026-01-10", hours_logged=Decimal("40")) == Decimal("2000")


def test_negative_day_rate_floored():
    rental = _rental(internal_rate_per_day=Decimal("-200"))
    assert compute_rental_billing(rental, "2026-01-01", "2026-01-10") == Decimal("0")


# ---- _busy_days_in_window (pure) -------------------------------------------
def _r(start, end):
    return SimpleNamespace(start_date=start, end_date=end)


def test_busy_days_single_interval():
    days = _busy_days_in_window([_r("2026-01-01", "2026-01-05")], date(2026, 1, 1), date(2026, 1, 31))
    assert days == 5


def test_busy_days_overlap_merged_not_double_counted():
    rentals = [_r("2026-01-01", "2026-01-05"), _r("2026-01-03", "2026-01-10")]
    days = _busy_days_in_window(rentals, date(2026, 1, 1), date(2026, 1, 31))
    assert days == 10  # union 01-01..01-10, not 5 + 8


def test_busy_days_adjacent_intervals_merge():
    rentals = [_r("2026-01-01", "2026-01-05"), _r("2026-01-06", "2026-01-10")]
    assert _busy_days_in_window(rentals, date(2026, 1, 1), date(2026, 1, 31)) == 10


def test_busy_days_clipped_to_window():
    rentals = [_r("2025-12-01", "2026-01-05")]
    assert _busy_days_in_window(rentals, date(2026, 1, 1), date(2026, 1, 31)) == 5


def test_busy_days_open_ended_rental_uses_window_end():
    rentals = [_r("2026-01-10", None)]
    assert _busy_days_in_window(rentals, date(2026, 1, 1), date(2026, 1, 31)) == 22


def test_busy_days_empty_is_zero():
    assert _busy_days_in_window([], date(2026, 1, 1), date(2026, 1, 31)) == 0
