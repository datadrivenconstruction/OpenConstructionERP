# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Displacement, rate and level arithmetic on the Riverside Yard wall points (no database).

The numbers are the course's: ``demo/riverside/expected.json`` holds them and a failing
assertion here means a lesson would show something else.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.monitoring import monitoring_math as mm
from app.modules.monitoring.profiles import DEMO_PROFILE

DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "monitoring" / "demo" / "riverside"
EXPECTED = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["monitoring"]
T = DEMO_PROFILE.thresholds


def at(day: int) -> datetime:
    return datetime(2026, 10, 9, tzinfo=UTC).replace(day=9 + day)


def z(day: int, value: str) -> mm.Reading:
    return mm.Reading(at(day), z=Decimal(value))


MP01 = [z(0, "34.512"), z(7, "34.506"), z(14, "34.497"), z(21, "34.489")]
MP02 = [z(0, "34.300"), z(7, "34.299"), z(14, "34.298"), z(21, "34.297")]


def test_lesson_1_mp01_after_three_epochs_is_minus_15_mm_at_alert() -> None:
    lesson = EXPECTED["lesson_1"]
    last = mm.evaluate("z", MP01[:3], T)[-1]
    assert last.displacement_mm == Decimal(str(lesson["displacement_mm"]))
    assert last.rate_mm_day == Decimal(str(lesson["rate_mm_day"]))  # -9 mm over 7 days
    assert last.level == lesson["level"]
    assert last.crossed


def test_lesson_1_mp02_is_2_mm_and_ok() -> None:
    other = EXPECTED["lesson_1"]["other_point"]
    last = mm.evaluate("z", MP02[:3], T)[-1]
    assert last.displacement_mm == Decimal(str(other["displacement_mm"]))
    assert last.level == other["level"]
    assert not last.crossed


def test_lesson_2_the_chart_series_and_bands() -> None:
    lesson = EXPECTED["lesson_2"]
    series = mm.evaluate("z", MP01[:3], T)
    assert [float(e.displacement_mm) for e in series] == lesson["displacements_mm"]
    assert [float(v) for v in (T.alert_mm, T.action_mm, T.alarm_mm)] == lesson["bands_mm"]


def test_lesson_3_epoch_4_is_minus_23_mm_at_action() -> None:
    lesson = EXPECTED["lesson_3"]
    last = mm.evaluate("z", MP01, T)[-1]
    assert last.displacement_mm == Decimal(str(lesson["displacement_mm"]))
    assert last.rate_mm_day == Decimal(str(lesson["rate_mm_day"]))  # -8 mm over 7 days
    assert last.level == lesson["level"]
    assert last.crossed


def test_lesson_5_report_has_one_point_at_action_and_mp02_ok() -> None:
    points = EXPECTED["lesson_5"]["points"]
    assert mm.evaluate("z", MP01, T)[-1].level == points["MP-01"]
    assert mm.evaluate("z", MP02, T)[-1].level == points["MP-02"]
    assert mm.evaluate("z", MP02, T)[-1].displacement_mm == Decimal("-3.0")


def test_the_baseline_is_ok_and_has_no_rate() -> None:
    first = mm.evaluate("z", MP01, T)[0]
    assert (first.displacement_mm, first.rate_mm_day, first.level, first.crossed) == (Decimal("0.0"), None, "ok", False)


def test_readings_are_judged_in_date_order_whatever_the_input_order() -> None:
    shuffled = [MP01[2], MP01[0], MP01[3], MP01[1]]
    assert mm.evaluate("z", shuffled, T) == mm.evaluate("z", MP01, T)


def test_decimal_arithmetic_has_no_float_noise() -> None:
    assert mm.displacement_mm("z", z(0, "34.512"), z(14, "34.497")) == Decimal("-15.000")


@pytest.mark.parametrize(
    ("displacement", "rate", "level"),
    [
        ("-9.9", None, "ok"),
        ("-10.0", None, "alert"),
        ("19.9", None, "alert"),
        ("-20.0", None, "action"),
        ("-30.0", None, "alarm"),
        ("-45.0", None, "alarm"),
        ("-5.0", "-0.99", "ok"),
        ("-5.0", "-1.00", "alert"),
        ("-5.0", "1.50", "alert"),
        ("-25.0", "-0.10", "action"),
        (None, None, "ok"),
    ],
)
def test_a_threshold_is_crossed_when_the_absolute_value_reaches_it(
    displacement: str | None, rate: str | None, level: str
) -> None:
    d = None if displacement is None else Decimal(displacement)
    r = None if rate is None else Decimal(rate)
    assert mm.level_of(d, r, T) == level


def test_rate_levels_use_the_highest_of_displacement_and_rate() -> None:
    t = mm.Thresholds(alert_mm=Decimal(10), rate_alert=Decimal(1), rate_action=Decimal(3))
    assert mm.level_of(Decimal("12"), Decimal("3.2"), t) == "action"
    assert mm.level_of(Decimal("12"), Decimal("0.5"), t) == "alert"


def test_no_thresholds_never_trigger() -> None:
    assert mm.level_of(Decimal(500), Decimal(50), mm.Thresholds()) == "ok"
    assert mm.Thresholds().is_empty()
    assert all(e.level == "ok" for e in mm.evaluate("z", MP01, mm.Thresholds()))


def test_rate_needs_time_to_pass() -> None:
    assert mm.rate_mm_day(Decimal(0), Decimal(-5), Decimal(0)) is None
    assert mm.rate_mm_day(None, Decimal(-5), Decimal(1)) is None
    assert mm.rate_mm_day(Decimal(0), Decimal(-1), mm.days_between(at(0), at(0).replace(hour=12))) == Decimal("-2.00")


def test_horizontal_displacement_is_a_distance_from_the_baseline() -> None:
    base = mm.Reading(at(0), e=Decimal("100.0000"), n=Decimal("200.0000"))
    moved = mm.Reading(at(7), e=Decimal("100.0120"), n=Decimal("199.9910"))
    assert mm.displacement_mm("horizontal", base, moved) == Decimal("15.0")  # 12 mm east, 9 mm south
    assert mm.displacement_mm("horizontal", base, moved) >= 0


def test_3d_needs_all_three_and_includes_height() -> None:
    base = mm.Reading(at(0), e=Decimal(0), n=Decimal(0), z=Decimal(10))
    moved = mm.Reading(at(7), e=Decimal("0.003"), n=Decimal("0.004"), z=Decimal("9.988"))
    assert mm.displacement_mm("3d", base, moved) == Decimal("13.0")  # 3-4-12 triangle
    assert mm.displacement_mm("3d", base, mm.Reading(at(7), e=Decimal(0), n=Decimal(0))) is None


def test_value_axis_keeps_the_sign_for_convergence_chords() -> None:
    base = mm.Reading(at(0), value=Decimal("12.3450"))
    narrowed = mm.Reading(at(7), value=Decimal("12.3390"))
    assert mm.displacement_mm("value", base, narrowed) == Decimal("-6.0")


def test_unknown_axis_is_rejected() -> None:
    with pytest.raises(ValueError):
        mm.displacement_mm("x", MP01[0], MP01[1])  # type: ignore[arg-type]


def test_a_gap_in_a_series_keeps_the_rate_against_the_last_usable_reading() -> None:
    blank = mm.Reading(at(7))
    series = mm.evaluate("z", [MP01[0], blank, MP01[2]], T)
    assert series[1].displacement_mm is None
    assert series[2].rate_mm_day == Decimal("-1.07")  # -15 mm over 14 days


def test_thresholds_must_rise_and_be_positive() -> None:
    assert mm.ordered(T)
    assert not mm.ordered(mm.Thresholds(alert_mm=Decimal(20), action_mm=Decimal(10)))
    assert not mm.ordered(mm.Thresholds(alert_mm=Decimal(10), action_mm=Decimal(10)))
    assert not mm.ordered(mm.Thresholds(rate_alert=Decimal(0)))


def test_the_demo_profile_matches_the_course_numbers() -> None:
    profile = EXPECTED["profile"]
    assert DEMO_PROFILE.name == profile["name"]
    assert DEMO_PROFILE.reference == "Demo values, not a standard"
    assert (T.alert_mm, T.action_mm, T.alarm_mm) == (Decimal(10), Decimal(20), Decimal(30))
    assert T.rate_alert == Decimal(str(profile["rate_alert_mm_day"]))
    assert T.rate_action is None
    assert T.rate_alarm is None
