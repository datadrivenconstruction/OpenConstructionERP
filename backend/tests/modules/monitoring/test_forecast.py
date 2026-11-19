# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Monitoring forecast from the worked example and SRV-120."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.monitoring import monitoring_math as mm
from app.modules.monitoring.validators import ForecastRule

T0 = datetime(2026, 11, 1, tzinfo=UTC)


def _series(values: list[float], step_days: float = 5.0) -> list[mm.Evaluation]:
    return [
        mm.Evaluation(T0 + timedelta(days=i * step_days), Decimal(str(v)), None, "ok", False)
        for i, v in enumerate(values)
    ]


def test_minus_8_at_minus_0_4_per_day_reaches_alarm_15_in_17_5_days() -> None:
    evals = _series([-0.0, -2.0, -4.0, -6.0, -8.0])
    t = mm.Thresholds(alert_mm=Decimal(5), action_mm=Decimal(8), alarm_mm=Decimal(15))
    fc = mm.forecast(evals, t)
    assert fc is not None
    assert fc.slope_mm_day == pytest.approx(-0.4)
    assert fc.fitted_mm == pytest.approx(-8.0)
    assert (fc.level, fc.limit_mm, fc.days) == ("alarm", 15.0, 17.5)


def test_next_threshold_is_the_lowest_not_yet_reached() -> None:
    fc = mm.forecast(_series([-2.0, -4.0, -6.0, -8.0]), mm.Thresholds(alert_mm=Decimal(10), alarm_mm=Decimal(15)))
    assert fc is not None and fc.level == "alert" and fc.days == pytest.approx(5.0)


def test_a_trend_back_to_zero_reaches_nothing() -> None:
    fc = mm.forecast(_series([-8.0, -6.0, -4.0]), mm.Thresholds(alarm_mm=Decimal(15)))
    assert fc is not None and not fc.level and fc.days is None


def test_one_epoch_is_no_forecast() -> None:
    assert mm.forecast(_series([-1.0]), mm.Thresholds(alarm_mm=Decimal(15))) is None


async def _failed(data: dict) -> list:
    ctx = ValidationContext(data=data, metadata={"locale": "en"})
    return [r for r in await ForecastRule().validate(ctx) if not r.passed]


async def test_srv120_inside_the_horizon() -> None:
    [hit] = await _failed({"points": [{"code": "MP-07", "forecast_level": "alarm", "forecast_days": 17.5}]})
    assert hit.rule_id == "SRV-120"
    assert "MP-07" in hit.message and "17.5" in hit.message


async def test_srv120_silent_beyond_the_horizon_or_without_a_level() -> None:
    assert await _failed({"points": [{"code": "A", "forecast_level": "alarm", "forecast_days": 45.0}]}) == []
    assert await _failed({"points": [{"code": "B", "forecast_level": "", "forecast_days": None}]}) == []
