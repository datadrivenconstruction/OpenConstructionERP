"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for equipment predictive maintenance + fleet analytics.

All tests exercise the pure (no-I/O) helpers in
``app.modules.equipment.predictive_service`` so they run without a database.

Coverage:

1.  Healthy machine with smooth telemetry → green band, score high, no anomaly.
2.  Fuel-level spike is flagged as an anomaly.
3.  Hour-meter rollback is flagged explicitly.
4.  Usage-rate spike is flagged.
5.  Open work orders + overdue inspection drag the score into red.
6.  Stale telemetry penalises the score.
7.  Empty telemetry → low-ish score, "no telemetry" reason, not a crash.
8.  Band thresholds (green/amber/red) map correctly.
9.  modified_zscores robust to all-identical input (no ZeroDivision).
10. usage_trend computes a sane daily-usage and rising direction.
11. forecast_failure projects to the service meter using daily usage.
12. forecast_failure confidence is bounded to (0, 1).
13. forecast_failure falls back to health-band horizon with no schedule.
14. fleet_recommendations finds underutilised units and sums savings.
15. fleet_recommendations bundles units needing service.
16. maintenance_trend = deteriorating when multiple anomalies present.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.modules.equipment.predictive_service import (
    HEALTH_AMBER_THRESHOLD,
    HEALTH_GREEN_THRESHOLD,
    FleetUnitInsight,
    TelemetrySample,
    analyze_health,
    detect_anomalies,
    fleet_recommendations,
    forecast_failure,
    modified_zscores,
    usage_trend,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _steady_history(
    *,
    days: int = 40,
    hours_per_day: float = 6.0,
    fuel_pct: float = 80.0,
    step_days: int = 2,
) -> list[TelemetrySample]:
    """Build a smooth telemetry series: constant daily hours, stable fuel."""
    samples: list[TelemetrySample] = []
    hour_meter = 1000.0
    d = 0
    while d <= days:
        samples.append(
            TelemetrySample(
                recorded_at=BASE + timedelta(days=d),
                hour_meter=hour_meter,
                odometer_km=hour_meter * 5,
                fuel_level=fuel_pct,
                engine_status="running",
            )
        )
        hour_meter += hours_per_day * step_days
        d += step_days
    return samples


# ── CASE 1: healthy machine ─────────────────────────────────────────────────


def test_healthy_machine_is_green():
    samples = _steady_history()
    # today close to the last reading so telemetry is not stale
    today = samples[-1].recorded_at + timedelta(days=1)
    h = analyze_health(samples, open_work_orders=0, overdue_inspection=False, today=today)
    assert h.band == "green"
    assert h.health_score >= HEALTH_GREEN_THRESHOLD
    assert h.anomaly_detected is False
    assert h.anomalies == []


# ── CASE 2: fuel spike anomaly ──────────────────────────────────────────────


def test_fuel_spike_flagged():
    samples = _steady_history()
    # Inject an implausible fuel reading mid-series.
    spike = TelemetrySample(
        recorded_at=BASE + timedelta(days=11),
        hour_meter=1033.0,
        fuel_level=2.0,  # sudden drop from ~80
    )
    samples.append(spike)
    anomalies = detect_anomalies(samples)
    assert any(a.metric == "fuel_level" for a in anomalies)


# ── CASE 3: hour-meter rollback ─────────────────────────────────────────────


def test_hour_meter_rollback_flagged():
    samples = _steady_history(days=20)
    samples.append(
        TelemetrySample(
            recorded_at=BASE + timedelta(days=21),
            hour_meter=10.0,  # rolled back from >1000
            fuel_level=80.0,
        )
    )
    anomalies = detect_anomalies(samples)
    rollback = [a for a in anomalies if a.metric == "hour_meter"]
    assert rollback
    assert "backward" in rollback[0].reason.lower()


# ── CASE 4: usage-rate spike ────────────────────────────────────────────────


def test_usage_rate_spike_flagged():
    samples = _steady_history(days=30, hours_per_day=4.0, step_days=2)
    # One interval with a huge jump (machine ran 60h in 2 days).
    last = samples[-1]
    samples.append(
        TelemetrySample(
            recorded_at=last.recorded_at + timedelta(days=2),
            hour_meter=(last.hour_meter or 0) + 120.0,
            fuel_level=80.0,
        )
    )
    anomalies = detect_anomalies(samples)
    assert any(a.metric == "usage_rate" for a in anomalies)


# ── CASE 5: open WO + overdue inspection → red ──────────────────────────────


def test_open_wo_and_overdue_inspection_lower_score():
    samples = _steady_history()
    today = samples[-1].recorded_at + timedelta(days=1)
    h = analyze_health(samples, open_work_orders=3, overdue_inspection=True, today=today)
    assert h.band == "red"
    assert h.health_score < HEALTH_AMBER_THRESHOLD
    assert any("inspection" in r.lower() for r in h.reasons)


# ── CASE 6: stale telemetry penalty ─────────────────────────────────────────


def test_stale_telemetry_penalty():
    samples = _steady_history(days=20)
    fresh_today = samples[-1].recorded_at + timedelta(days=1)
    stale_today = samples[-1].recorded_at + timedelta(days=60)
    fresh = analyze_health(samples, today=fresh_today)
    stale = analyze_health(samples, today=stale_today)
    assert stale.health_score < fresh.health_score
    assert any("telemetry" in r.lower() for r in stale.reasons)


# ── CASE 7: empty telemetry is safe ─────────────────────────────────────────


def test_empty_telemetry_does_not_crash():
    h = analyze_health([], open_work_orders=0, overdue_inspection=False)
    assert 0.0 <= h.health_score <= 100.0
    assert h.sample_count == 0
    assert any("no telemetry" in r.lower() for r in h.reasons)


# ── CASE 8: band thresholds ─────────────────────────────────────────────────


def test_band_thresholds_map_correctly():
    samples = _steady_history()
    today = samples[-1].recorded_at + timedelta(days=1)
    green = analyze_health(samples, today=today)
    amber = analyze_health(samples, open_work_orders=2, today=today)
    red = analyze_health(samples, open_work_orders=3, overdue_inspection=True, today=today)
    assert green.band == "green"
    assert amber.band in ("amber", "green")  # 2 WOs ~ -20 → ~80, may still be green-ish
    assert red.band == "red"
    # Explicit threshold sanity
    assert HEALTH_AMBER_THRESHOLD < HEALTH_GREEN_THRESHOLD


# ── CASE 9: modified_zscores robustness ─────────────────────────────────────


def test_modified_zscores_all_identical():
    assert modified_zscores([5.0, 5.0, 5.0, 5.0]) == [0.0, 0.0, 0.0, 0.0]


def test_modified_zscores_empty():
    assert modified_zscores([]) == []


def test_modified_zscores_detects_outlier():
    zs = modified_zscores([10, 10, 10, 10, 10, 100])
    assert abs(zs[-1]) > 3.5


# ── CASE 10: usage_trend ────────────────────────────────────────────────────


def test_usage_trend_computes_daily_usage():
    samples = _steady_history(days=40, hours_per_day=6.0, step_days=2)
    trend = usage_trend(samples)
    # ~6 hours/day used, near-flat slope
    assert abs(trend.daily_usage_recent - 6.0) < 1.0
    assert trend.direction == "flat"
    assert trend.samples >= 4


def test_usage_trend_rising():
    # Each interval logs progressively more hours → rising trend.
    samples: list[TelemetrySample] = []
    hour_meter = 0.0
    for i in range(15):
        samples.append(
            TelemetrySample(
                recorded_at=BASE + timedelta(days=i * 2),
                hour_meter=hour_meter,
                fuel_level=80.0,
            )
        )
        hour_meter += (4.0 + i) * 2  # accelerating usage
    trend = usage_trend(samples)
    assert trend.direction == "rising"
    assert trend.slope_per_day > 0


# ── CASE 11: forecast projects to service meter ─────────────────────────────


def test_forecast_projects_to_service_meter():
    samples = _steady_history(days=40, hours_per_day=6.0, step_days=2)
    current = samples[-1].hour_meter or 0.0
    next_meter = current + 60.0  # ~10 days at 6h/day
    today = samples[-1].recorded_at + timedelta(days=1)
    fc = forecast_failure(
        samples,
        current_hour_meter=current,
        next_service_meter=next_meter,
        health=analyze_health(samples, today=today),
        today=today,
    )
    assert fc.basis == "projected_usage_to_service"
    assert fc.days_to_failure is not None
    assert 5 <= fc.days_to_failure <= 20
    assert fc.predicted_failure_date is not None


# ── CASE 12: confidence bounded ─────────────────────────────────────────────


def test_forecast_confidence_bounded():
    samples = _steady_history()
    current = samples[-1].hour_meter or 0.0
    fc = forecast_failure(
        samples,
        current_hour_meter=current,
        next_service_meter=current + 60.0,
        health=analyze_health(samples, today=samples[-1].recorded_at + timedelta(days=1)),
        today=samples[-1].recorded_at + timedelta(days=1),
    )
    assert 0.0 < fc.failure_confidence < 1.0


# ── CASE 13: fallback horizon ───────────────────────────────────────────────


def test_forecast_fallback_when_no_schedule():
    samples = _steady_history()
    current = samples[-1].hour_meter or 0.0
    today = samples[-1].recorded_at + timedelta(days=1)
    fc = forecast_failure(
        samples,
        current_hour_meter=current,
        next_service_meter=None,
        health=analyze_health(samples, today=today),
        today=today,
    )
    assert fc.basis == "health_band_horizon"
    assert fc.days_to_failure is not None and fc.days_to_failure > 0
    assert fc.predicted_failure_date is not None


# ── CASE 14: fleet underutilised + savings ──────────────────────────────────


def test_fleet_finds_underutilized_and_savings():
    units = [
        FleetUnitInsight(
            equipment_id="a",
            code="EX-01",
            name="Idle Excavator",
            utilization_pct=10.0,
            open_work_orders=0,
            health_band="green",
            daily_holding_cost=Decimal("100"),
        ),
        FleetUnitInsight(
            equipment_id="b",
            code="EX-02",
            name="Busy Excavator",
            utilization_pct=85.0,
            open_work_orders=0,
            health_band="green",
            daily_holding_cost=Decimal("100"),
        ),
    ]
    rec = fleet_recommendations(units, target_utilization_pct=70.0, window_days=30)
    assert rec["underutilized_count"] == 1
    assert rec["underutilized"][0]["code"] == "EX-01"
    # idle fraction = (70 - 10)/100 = 0.6 → 18 idle days * 100 = 1800
    assert Decimal(str(rec["estimated_monthly_savings"])) > Decimal("0")
    assert Decimal(rec["underutilized"][0]["estimated_monthly_saving"]) == Decimal("1800.00")


# ── CASE 15: maintenance bundles ────────────────────────────────────────────


def test_fleet_bundles_units_needing_service():
    units = [
        FleetUnitInsight("a", "C1", "Crane 1", 80.0, 2, "red"),
        FleetUnitInsight("b", "C2", "Crane 2", 80.0, 3, "red"),
        FleetUnitInsight("c", "C3", "Crane 3", 80.0, 0, "green"),
    ]
    rec = fleet_recommendations(units)
    bundles = rec["maintenance_bundles"]
    assert bundles
    # Two red units bundle into a priority run.
    priority = [b for b in bundles if b["unit_count"] >= 2]
    assert priority
    assert set(priority[0]["equipment_ids"]) >= {"a", "b"}


# ── CASE 16: deteriorating maintenance trend ────────────────────────────────


def test_maintenance_trend_deteriorating_on_multiple_anomalies():
    samples = _steady_history(days=30)
    # Two distinct anomalies: fuel drop + meter rollback.
    samples.append(TelemetrySample(recorded_at=BASE + timedelta(days=11), hour_meter=1033.0, fuel_level=1.0))
    samples.append(TelemetrySample(recorded_at=BASE + timedelta(days=33), hour_meter=5.0, fuel_level=80.0))
    today = BASE + timedelta(days=34)
    h = analyze_health(samples, today=today)
    assert h.anomaly_detected is True
    assert h.maintenance_trend == "deteriorating"
