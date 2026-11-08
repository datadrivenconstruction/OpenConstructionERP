# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests: datum, equivalent age, calibration fit, strength floor, projection range, zoned limits, rules."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.site_monitoring import night_noise_by_ordinance, sensor_limit
from app.modules.site_sensors.analysis import reading_stats, rolling_mean, sparkline
from app.modules.site_sensors.maturity import (
    equivalent_age,
    fit_log_curve,
    hours_to_target_range,
    nurse_saul,
    strength_estimate,
)
from app.modules.site_sensors.pour_record import pour_record_csv, pour_record_pdf
from app.modules.site_sensors.schemas import MixCreate
from app.modules.site_sensors.validators import run_rules

T0 = datetime(2026, 11, 1, tzinfo=UTC)


def _const(temp: float, hours: int) -> list[tuple[datetime, float]]:
    return [(T0 + timedelta(hours=h), temp) for h in range(hours + 1)]


def test_default_datum_is_zero_degrees() -> None:
    assert nurse_saul(_const(20.0, 48))[-1][1] == pytest.approx(20 * 48)
    mix = MixCreate(code="C30", curve_a=Decimal("-43.1"), curve_b=Decimal("18.4"))
    assert mix.datum_temp_c == 0 and mix.method == "nurse_saul"
    assert mix.activation_energy_kj_mol == 40 and mix.reference_temp_c == 20


def test_equivalent_age_at_reference_is_elapsed_time_and_faster_when_warm() -> None:
    assert equivalent_age(_const(20.0, 24))[-1][1] == pytest.approx(24)
    factor = math.exp(40000 / 8.314 * (1 / 293.15 - 1 / 303.15))
    assert equivalent_age(_const(30.0, 10))[-1][1] == pytest.approx(10 * factor)
    assert factor == pytest.approx(1.718, abs=0.01)


def test_log_fit_recovers_the_curve_and_its_r2() -> None:
    a, b = -43.1, 18.4
    pts = [(m, a + b * math.log10(m)) for m in (500, 1000, 2000, 4000)]
    fit = fit_log_curve(pts)
    assert fit is not None
    assert fit[0] == pytest.approx(a) and fit[1] == pytest.approx(b) and fit[2] == pytest.approx(1.0)
    noisy = [(500, 8.0), (1000, 16.0), (2000, 14.0), (4000, 30.0)]
    assert fit_log_curve(noisy)[2] < 0.9
    assert fit_log_curve([(500, 8.0)]) is None


def test_no_strength_below_the_first_cube_and_extrapolation_is_flagged() -> None:
    a, b = -43.1, 18.4
    assert strength_estimate(1.0, a, b) == (None, "below_range")
    assert strength_estimate(300, a, b, lo=500, hi=4000) == (None, "below_range")
    value, status = strength_estimate(1000, a, b, lo=500, hi=4000)
    assert status == "ok" and value == pytest.approx(a + b * 3, abs=0.01)
    assert strength_estimate(6000, a, b, lo=500, hi=4000)[1] == "above_range"
    assert strength_estimate(1000, a, b)[1] == "uncalibrated"


def test_hours_to_target_is_a_range_from_the_last_six_hours() -> None:
    temps = [(T0 + timedelta(hours=h), 20.0 if h % 2 else 10.0) for h in range(13)]
    series = nurse_saul(temps)
    m_last = series[-1][1]
    lo, hi = hours_to_target_range(series, m_last + 150)
    assert lo == pytest.approx(10) and hi == pytest.approx(10)
    ramp = [(T0 + timedelta(hours=h), 10.0 + h) for h in range(13)]
    series = nurse_saul(ramp)
    lo, hi = hours_to_target_range(series, series[-1][1] + 100)
    assert lo < hi
    assert hours_to_target_range(series, 0) == (0.0, 0.0)
    assert hours_to_target_range(nurse_saul(_const(-5.0, 10)), 100) is None


def test_german_noise_is_zoned_and_defaults_to_residential() -> None:
    day = datetime(2026, 11, 2, 10).time()
    night = datetime(2026, 11, 2, 23).time()
    lim = sensor_limit("DE", "noise", day)
    assert lim is not None and lim.value == 55 and "(d)" in lim.source
    assert sensor_limit("DE", "noise", night).value == 40
    assert sensor_limit("DE", "noise", day, zone="a").value == 70
    assert sensor_limit("DE", "noise", night, zone="e").value == 35
    assert night_noise_by_ordinance("US") and not night_noise_by_ordinance("DE")
    assert sensor_limit("US", "noise", night).value == 90


def test_din_4150_3_limit_follows_frequency_and_building_class() -> None:
    assert sensor_limit("DE", "vibration").value == 5
    assert sensor_limit("DE", "vibration", frequency_hz=30).value == 10
    assert sensor_limit("DE", "vibration", band="50_100").value == 15
    assert sensor_limit("DE", "vibration", building_class="1", frequency_hz=75).value == 45
    assert sensor_limit("DE", "vibration", building_class="3", frequency_hz=200).value == 10
    assert "line 2" in sensor_limit("DE", "vibration", frequency_hz=30).source
    assert sensor_limit("GB", "vibration").value == 15


def test_reading_stats_rolling_mean_and_sparkline() -> None:
    rows = [(T0 + timedelta(minutes=10 * i), 20.0) for i in range(6)] + [(T0 + timedelta(minutes=90), 40.0)]
    stats = reading_stats(rows)
    assert stats["interval_min"] == 10 and stats["max_gap_min"] == 40
    assert stats["max_jump_per_h"] == pytest.approx(30)
    pm = [(T0 + timedelta(hours=h), v) for h, v in enumerate([30.0, 61.0, 72.0])]
    assert rolling_mean(pm, pm[-1][0]) == pytest.approx(163 / 3)
    line = sparkline(pm, T0 + timedelta(hours=2, minutes=30))
    assert len(line) == 24 and line[-1] == 72.0 and line[0] is None


async def test_new_sensor_rules() -> None:
    payload = {
        "devices": [
            {"id": "n1", "code": "NS-1", "kind": "noise", "active": True, "has_limit": False},
            {"id": "c1", "code": "CM-1", "kind": "concrete_maturity", "active": True, "has_mix": False},
            {
                "id": "c2",
                "code": "CM-2",
                "kind": "concrete_maturity",
                "active": True,
                "has_mix": True,
                "interval_min": 15,
                "max_gap_min": 45,
                "max_jump_per_h": 22,
                "min": 5,
                "max": 30,
            },
        ],
        "mixes": [
            {"id": "m0", "code": "C25", "points": 0, "r2": None},
            {"id": "m1", "code": "C30", "points": 3, "r2": 0.98},
            {"id": "m2", "code": "C35", "points": 5, "r2": 0.95},
        ],
        "pours": [
            {"id": "c2", "code": "CM-2", "strength_status": "above_range"},
            {"id": "c3", "code": "CM-3", "strength_status": "below_range"},
        ],
        "strips": [
            {"id": "s1", "element": "W1", "struck": True, "target_mpa": "15", "strength_at_strike_mpa": "9"},
            {
                "id": "s2",
                "element": "W2",
                "struck": True,
                "target_mpa": "15",
                "strength_at_strike_mpa": "9",
                "reason": "Cube 16.2 MPa",
            },
        ],
    }
    failed = sorted((r["rule_id"].split(".")[1], r["element_ref"]) for r in await run_rules(payload) if not r["passed"])
    assert failed == [
        ("calibration_quality", "m1"),
        ("concrete_sensor_has_mix", "c1"),
        ("curve_calibrated", "m0"),
        ("device_has_limit", "n1"),
        ("estimate_in_calibrated_range", "c2"),
        ("no_reading_gap", "c2"),
        ("strike_after_target_strength", "s1"),
        ("temperature_plausible", "c2"),
    ]


def test_pour_record_csv_and_pdf() -> None:
    record = {
        "strip_id": str(uuid.uuid4()),
        "element": "Slab L3",
        "device_code": "CM-01",
        "pour_ref": "P-07",
        "mix_code": "C30",
        "index_unit": "c_h",
        "target_strength_mpa": "15.00",
        "struck_at": "2026-11-03T08:00:00+00:00",
        "strength_at_strike_mpa": "12.40",
        "maturity_at_strike": 1100.0,
        "struck_by": "Site manager",
        "strike_reason": "Back-propped; cube 15.8 MPa",
        "series": [
            {"t": f"2026-11-0{1 + i // 24}T{i % 24:02d}:00:00", "temp": 18.0, "maturity": 18.0 * i} for i in range(60)
        ],
    }
    text = pour_record_csv(record).decode("utf-8-sig")
    assert "Back-propped; cube 15.8 MPa" in text and "Maturity (°C·h)" in text
    assert len(text.strip().splitlines()) == 11 + 1 + 1 + 60
    assert "Betonierprotokoll" not in text and "Reife (°C·h)" in pour_record_csv(record, "de").decode("utf-8-sig")
    assert pour_record_pdf(record).startswith(b"%PDF")


def test_limit_grading_follows_country_data() -> None:
    from app.core.site_monitoring import limit_grading

    de = limit_grading("DE")
    assert de["noise_zones"] and de["building_classes"]
    none = limit_grading("ZZ")
    assert none["noise_zones"] == [] and none["building_classes"] == []


def test_pour_record_labels_come_from_backend_locales() -> None:
    from app.modules.site_sensors.pour_record import LABELS

    assert LABELS["en"]["title"] == "Pour record"
    assert LABELS["ru"]["title"] == "Протокол бетонирования"
    assert set(LABELS["fr"]) == set(LABELS["en"])
