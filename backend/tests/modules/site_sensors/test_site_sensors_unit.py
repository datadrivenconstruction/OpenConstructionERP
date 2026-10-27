# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: Nurse-Saul maturity, the strength curve and the site sensor and equipment rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.equipment.validators import run_rules as run_equipment_rules
from app.modules.site_sensors.maturity import (
    hours_to_strength,
    maturity_for_strength,
    nurse_saul,
    strength_from_maturity,
)
from app.modules.site_sensors.validators import run_rules as run_sensor_rules

T0 = datetime(2026, 10, 20, tzinfo=UTC)


def test_nurse_saul_at_constant_20c_is_30_degree_hours_per_hour() -> None:
    series = nurse_saul([(T0 + timedelta(hours=h), 20.0) for h in range(49)], datum_c=-10)
    assert series[0][1] == 0
    assert series[-1][1] == pytest.approx(30 * 48)


def test_nurse_saul_ignores_time_below_the_datum() -> None:
    series = nurse_saul([(T0, -15.0), (T0 + timedelta(hours=10), -15.0), (T0 + timedelta(hours=11), -5.0)], -10)
    # Only the last hour counts, at a mean of -10: zero contribution.
    assert series[-1][1] == 0


def test_strength_curve_and_its_inverse_agree() -> None:
    a, b = -43.1, 18.4
    m = maturity_for_strength(15.0, a, b)
    assert m is not None
    assert strength_from_maturity(m, a, b) == pytest.approx(15.0)
    assert strength_from_maturity(0.0, a, b) == 0
    assert maturity_for_strength(15.0, a, 0) is None


def test_hours_to_strength_extrapolates_the_recent_rate() -> None:
    series = nurse_saul([(T0 + timedelta(hours=h), 20.0) for h in range(25)], -10)
    assert hours_to_strength(series, 30 * 34) == pytest.approx(10)
    assert hours_to_strength(series, 10) == 0


async def test_sensor_rules_flag_offline_unacknowledged_and_early_strike() -> None:
    payload = {
        "devices": [
            {"id": "d1", "code": "NS-01", "active": True, "offline": True},
            {"id": "d2", "code": "CM-01", "active": True, "offline": False},
            {"id": "d3", "code": "OLD", "active": False, "offline": True},
        ],
        "exceedances": [
            {"id": "a1", "device": "NS-01", "status": "open", "value": 78.5, "limit": 70},
            {"id": "a2", "device": "NS-01", "status": "acknowledged", "value": 72, "limit": 70},
        ],
        "strips": [
            {"id": "s1", "element": "Slab", "struck": True, "target_mpa": "15", "strength_at_strike_mpa": "12.4"},
            {"id": "s2", "element": "Wall", "struck": True, "target_mpa": "15", "strength_at_strike_mpa": "16"},
            {"id": "s3", "element": "Beam", "struck": False, "target_mpa": "15", "strength_at_strike_mpa": None},
        ],
    }
    results = await run_sensor_rules(payload)
    failed = {(r["rule_id"], r["element_ref"]) for r in results if not r["passed"]}
    assert failed == {
        ("site_sensors.sensor_online", "d1"),
        ("site_sensors.exceedance_acknowledged", "a1"),
        ("site_sensors.strike_after_target_strength", "s1"),
    }
    early = next(r for r in results if r["element_ref"] == "s1")
    assert early["details"]["message_key"] == "siteSensors.rules.strike_after_target_strength"
    assert early["details"]["strength"] == "12.4"


async def test_equipment_rules_flag_each_condition() -> None:
    payload = {
        "today": "2026-10-20",
        "idle_threshold": "0.35",
        "machines": [
            {"equipment_id": "e1", "code": "A", "on_site_project_id": "p", "allocated_project_id": None},
            {
                "equipment_id": "e2",
                "code": "B",
                "on_site_project_id": "p",
                "allocated_project_id": "p",
                "maintenance_overdue": [{"due": "100", "now": "130"}],
                "outside_geofence_m": "0",
                "idle_ratio_7d": "0.45",
            },
            {
                "equipment_id": "e3",
                "code": "C",
                "allocated_project_id": "p",
                "outside_geofence_m": "640.5",
                "idle_ratio_7d": "0.2",
            },
        ],
    }
    results = await run_equipment_rules(payload)
    failed = {(r["rule_id"], r["element_ref"]) for r in results if not r["passed"]}
    assert failed == {
        ("equipment_telematics.on_site_allocated", "e1"),
        ("equipment_telematics.maintenance_overdue", "e2"),
        ("equipment_telematics.idle_threshold", "e2"),
        ("equipment_telematics.inside_geofence", "e3"),
    }
