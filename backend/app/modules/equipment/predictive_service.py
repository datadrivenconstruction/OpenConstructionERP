# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Equipment predictive maintenance and fleet analytics.

Deterministic, on-the-fly analytics computed from the existing
:class:`~app.modules.equipment.models.TelemetryReading` history plus open
maintenance work orders. No new tables are introduced: every figure is derived
from rows that already exist, in keeping with the LIGHTWEIGHT rule.

The module is split into two layers:

* **Pure helpers** (no I/O) operate on plain dataclasses / numeric samples so
  they are trivially unit-testable without a database. These hold all of the
  analytics: health scoring, anomaly detection (robust z-score), usage-trend
  linear regression, failure forecasting and fleet optimisation.
* **Service methods** (:class:`EquipmentPredictiveService`) fetch the rows
  from the repositories and feed the pure helpers, returning Pydantic response
  schemas for the router.

Plain-English vocabulary is used deliberately (Health Score, not MTBF/PHM) so
the output is legible to a fleet manager rather than a reliability engineer.
"""

from __future__ import annotations

import math
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from app.modules.equipment.repository import (
    EquipmentRepository,
    TelemetryRepository,
    WorkOrderRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.equipment.models import TelemetryReading

# Tunable constants (kept module-level so tests can reference them).
HEALTH_GREEN_THRESHOLD = 75.0
HEALTH_AMBER_THRESHOLD = 50.0
# Robust z-score above which a reading is flagged anomalous. 3.5 is the
# Iglewicz-Hoaglin recommendation for the modified (MAD-based) z-score.
ANOMALY_Z_THRESHOLD = 3.5
# Minimum samples before trend / anomaly maths is meaningful.
MIN_SAMPLES_FOR_TREND = 4
MIN_SAMPLES_FOR_ANOMALY = 5
# A unit is "underutilised" below this monthly utilisation %.
UNDERUTILISED_THRESHOLD_PCT = 35.0
# Default daily holding cost assumption (used only when a unit has no rate
# data) keeps savings estimates non-zero and explainable.
DEFAULT_IDLE_DAY_COST = Decimal("120")


# ── Sample / value objects ────────────────────────────────────────────────


@dataclass(frozen=True)
class TelemetrySample:
    """A flattened telemetry reading used by the pure analytics helpers."""

    recorded_at: datetime
    hour_meter: float | None = None
    odometer_km: float | None = None
    fuel_level: float | None = None
    engine_status: str | None = None


@dataclass
class TrendResult:
    """Linear-regression result over a usage series."""

    slope_per_day: float
    direction: str  # "rising" | "falling" | "flat"
    daily_usage_recent: float  # mean hours/day over the recent window
    samples: int


@dataclass
class Anomaly:
    """A single anomalous reading."""

    recorded_at: datetime
    metric: str
    value: float
    z_score: float
    reason: str


@dataclass
class HealthAssessment:
    """Outcome of :func:`analyze_health`."""

    health_score: float
    band: str  # "green" | "amber" | "red"
    anomaly_detected: bool
    anomalies: list[Anomaly] = field(default_factory=list)
    maintenance_trend: str = "stable"  # "improving" | "stable" | "deteriorating"
    reasons: list[str] = field(default_factory=list)
    sample_count: int = 0


@dataclass
class FailureForecast:
    """Outcome of :func:`forecast_failure`."""

    predicted_failure_date: str | None
    failure_confidence: float  # 0.0 - 1.0
    days_to_failure: int | None
    basis: str
    daily_usage: float


# ── Pure helpers ───────────────────────────────────────────────────────────


def _ensure_aware(dt: datetime) -> datetime:
    """Normalise to a tz-aware UTC datetime for safe comparison."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _sorted_samples(samples: list[TelemetrySample]) -> list[TelemetrySample]:
    """Return samples sorted oldest-first by recorded_at."""
    return sorted(samples, key=lambda s: _ensure_aware(s.recorded_at))


def _series(samples: list[TelemetrySample], metric: str) -> list[tuple[datetime, float]]:
    """Extract (timestamp, value) pairs for ``metric``, dropping None values."""
    out: list[tuple[datetime, float]] = []
    for s in samples:
        raw = getattr(s, metric, None)
        if raw is None:
            continue
        try:
            out.append((_ensure_aware(s.recorded_at), float(raw)))
        except (TypeError, ValueError):
            continue
    return out


def modified_zscores(values: list[float]) -> list[float]:
    """Compute the modified (MAD-based) z-score for each value.

    Robust to outliers, unlike the classic mean/stdev z-score. Returns a list
    the same length as ``values``; an empty / degenerate input yields all-zero
    scores so callers never raise.
    """
    n = len(values)
    if n < 1:
        return []
    median = statistics.median(values)
    abs_dev = [abs(v - median) for v in values]
    mad = statistics.median(abs_dev)
    if mad == 0:
        # Fall back to mean-absolute-deviation scaling when MAD collapses
        # (e.g. a long run of identical values with a single spike).
        mean_ad = sum(abs_dev) / n
        if mean_ad == 0:
            return [0.0] * n
        return [0.7979 * (v - median) / mean_ad for v in values]
    return [0.6745 * (v - median) / mad for v in values]


def detect_anomalies(
    samples: list[TelemetrySample],
    *,
    z_threshold: float = ANOMALY_Z_THRESHOLD,
) -> list[Anomaly]:
    """Flag anomalous fuel-level and per-day usage-rate readings.

    Two signals are checked:

    * **fuel_level**: a robust z-score over reported fuel %. A sudden drop or
      implausible spike (sensor fault / theft / leak) stands out.
    * **usage rate**: the per-day hour-meter delta between consecutive
      readings. A day where the machine logs wildly more hours than usual is a
      strong wear signal.
    """
    ordered = _sorted_samples(samples)
    anomalies: list[Anomaly] = []

    # Fuel-level anomalies.
    fuel = _series(ordered, "fuel_level")
    if len(fuel) >= MIN_SAMPLES_FOR_ANOMALY:
        zs = modified_zscores([v for _, v in fuel])
        for (ts, val), z in zip(fuel, zs, strict=True):
            if abs(z) >= z_threshold:
                anomalies.append(
                    Anomaly(
                        recorded_at=ts,
                        metric="fuel_level",
                        value=round(val, 2),
                        z_score=round(z, 2),
                        reason=("Fuel reading far outside the normal range (possible sensor fault, leak or theft)"),
                    )
                )

    # Usage-rate anomalies from the hour-meter series.
    hours = _series(ordered, "hour_meter")
    if len(hours) >= MIN_SAMPLES_FOR_ANOMALY:
        rates: list[tuple[datetime, float]] = []
        for (t0, v0), (t1, v1) in zip(hours, hours[1:], strict=False):
            days = max((t1 - t0).total_seconds() / 86400.0, 1e-6)
            delta = v1 - v0
            if delta < 0:
                # Meter rollback / replacement: flag explicitly.
                anomalies.append(
                    Anomaly(
                        recorded_at=t1,
                        metric="hour_meter",
                        value=round(v1, 1),
                        z_score=0.0,
                        reason="Hour-meter went backwards (meter reset or data error)",
                    )
                )
                continue
            rates.append((t1, delta / days))
        if len(rates) >= MIN_SAMPLES_FOR_ANOMALY - 1:
            zs = modified_zscores([r for _, r in rates])
            for (ts, rate), z in zip(rates, zs, strict=True):
                if z >= z_threshold:
                    anomalies.append(
                        Anomaly(
                            recorded_at=ts,
                            metric="usage_rate",
                            value=round(rate, 2),
                            z_score=round(z, 2),
                            reason="Daily running hours spiked well above the usual pattern",
                        )
                    )
    return anomalies


def usage_trend(samples: list[TelemetrySample], *, recent_window_days: int = 30) -> TrendResult:
    """Least-squares trend of hour-meter usage rate over time.

    ``slope_per_day`` is the change in daily-usage (hours/day) per day, where a
    positive slope means the machine is being worked progressively harder.
    ``daily_usage_recent`` is the mean hours/day over the trailing window,
    which the forecast uses to project hours to the next service.
    """
    hours = _series(_sorted_samples(samples), "hour_meter")
    if len(hours) < 2:
        return TrendResult(slope_per_day=0.0, direction="flat", daily_usage_recent=0.0, samples=len(hours))

    t0 = hours[0][0]
    # Per-interval usage rate (hours per day) and the interval mid-point in days.
    points: list[tuple[float, float]] = []
    for (ta, va), (tb, vb) in zip(hours, hours[1:], strict=False):
        days = max((tb - ta).total_seconds() / 86400.0, 1e-6)
        delta = vb - va
        if delta < 0:
            continue
        mid_day = ((ta - t0).total_seconds() + (tb - t0).total_seconds()) / 2 / 86400.0
        points.append((mid_day, delta / days))

    if len(points) < 2:
        rate = points[0][1] if points else 0.0
        return TrendResult(slope_per_day=0.0, direction="flat", daily_usage_recent=rate, samples=len(hours))

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    n = len(points)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    slope = 0.0 if denom == 0 else sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / denom

    # Recent daily usage: mean of rates inside the trailing window.
    last_day = xs[-1]
    recent = [y for x, y in zip(xs, ys, strict=True) if x >= last_day - recent_window_days]
    daily_usage_recent = sum(recent) / len(recent) if recent else mean_y

    if slope > 0.01:
        direction = "rising"
    elif slope < -0.01:
        direction = "falling"
    else:
        direction = "flat"

    return TrendResult(
        slope_per_day=round(slope, 4),
        direction=direction,
        daily_usage_recent=round(daily_usage_recent, 3),
        samples=len(hours),
    )


def analyze_health(
    samples: list[TelemetrySample],
    *,
    open_work_orders: int = 0,
    overdue_inspection: bool = False,
    today: datetime | None = None,
) -> HealthAssessment:
    """Compute a 0-100 health score with a red/amber/green band.

    The score starts at 100 and is reduced by deterministic penalties:

    * each anomalous reading (capped),
    * open maintenance work orders (capped),
    * a stale telemetry feed (no recent data),
    * an overdue statutory inspection,
    * a steeply rising usage trend (machine being pushed harder over time).

    ``maintenance_trend`` summarises whether the unit's condition is improving,
    stable or deteriorating based on the usage-rate slope and anomaly density.
    """
    now = _ensure_aware(today) if today else datetime.now(UTC)
    score = 100.0
    reasons: list[str] = []

    ordered = _sorted_samples(samples)
    sample_count = len(ordered)

    anomalies = detect_anomalies(ordered)
    if anomalies:
        penalty = min(40.0, 8.0 * len(anomalies))
        score -= penalty
        reasons.append(f"{len(anomalies)} anomalous reading(s) detected")

    if open_work_orders > 0:
        penalty = min(30.0, 10.0 * open_work_orders)
        score -= penalty
        reasons.append(f"{open_work_orders} open maintenance work order(s)")

    if overdue_inspection:
        score -= 25.0
        reasons.append("A required inspection is overdue")

    # Stale telemetry feed: if the newest reading is old, we are flying blind.
    if ordered:
        newest = _ensure_aware(ordered[-1].recorded_at)
        age_days = (now - newest).total_seconds() / 86400.0
        if age_days > 45:
            score -= 15.0
            reasons.append("No telemetry in the last 45 days")
        elif age_days > 21:
            score -= 7.0
            reasons.append("Telemetry feed is going stale")
    else:
        score -= 10.0
        reasons.append("No telemetry recorded yet")

    trend = usage_trend(ordered)
    if trend.direction == "rising" and trend.slope_per_day > 0.05:
        score -= 8.0
        reasons.append("Daily usage is climbing steeply")

    score = max(0.0, min(100.0, score))

    if score >= HEALTH_GREEN_THRESHOLD:
        band = "green"
    elif score >= HEALTH_AMBER_THRESHOLD:
        band = "amber"
    else:
        band = "red"

    # Maintenance trend narrative.
    if len(anomalies) >= 2 or (trend.direction == "rising" and trend.slope_per_day > 0.05):
        maintenance_trend = "deteriorating"
    elif not anomalies and open_work_orders == 0 and not overdue_inspection:
        maintenance_trend = "improving" if band == "green" else "stable"
    else:
        maintenance_trend = "stable"

    if not reasons:
        reasons.append("All monitored signals within normal range")

    return HealthAssessment(
        health_score=round(score, 1),
        band=band,
        anomaly_detected=bool(anomalies),
        anomalies=anomalies,
        maintenance_trend=maintenance_trend,
        reasons=reasons,
        sample_count=sample_count,
    )


def forecast_failure(
    samples: list[TelemetrySample],
    *,
    current_hour_meter: float,
    next_service_meter: float | None,
    health: HealthAssessment | None = None,
    today: datetime | None = None,
) -> FailureForecast:
    """Forecast when the unit will next need attention.

    Strategy (deterministic):

    * If a maintenance schedule provides ``next_service_meter``, project the
      recent daily-usage rate forward to estimate the calendar date that meter
      will be reached. This is the primary, explainable basis.
    * Otherwise fall back to a health-driven horizon: a healthy machine is
      assumed to run far longer before intervention than a red-band one.

    ``failure_confidence`` reflects how much signal backs the estimate (sample
    count, usage stability and health band) and never claims certainty.
    """
    now = _ensure_aware(today) if today else datetime.now(UTC)
    trend = usage_trend(samples)
    daily_usage = trend.daily_usage_recent

    # Primary path: project to the next scheduled service meter.
    if next_service_meter is not None and next_service_meter > current_hour_meter and daily_usage > 0:
        remaining = next_service_meter - current_hour_meter
        days = int(math.ceil(remaining / daily_usage))
        days = max(0, min(days, 3650))
        predicted = (now + timedelta(days=days)).date().isoformat()
        # Confidence grows with sample count and usage stability; trims down
        # when the usage trend is volatile (steep slope relative to the rate).
        confidence = _forecast_confidence(trend, health, has_schedule=True)
        return FailureForecast(
            predicted_failure_date=predicted,
            failure_confidence=round(confidence, 2),
            days_to_failure=days,
            basis="projected_usage_to_service",
            daily_usage=round(daily_usage, 2),
        )

    # Fallback path: health-band horizon.
    band = health.band if health else "amber"
    horizon = {"green": 180, "amber": 75, "red": 21}.get(band, 75)
    # Heavier daily use shortens the horizon proportionally.
    if daily_usage > 0:
        horizon = int(horizon * (1.0 / (1.0 + daily_usage / 12.0)))
        horizon = max(7, horizon)
    predicted = (now + timedelta(days=horizon)).date().isoformat()
    confidence = _forecast_confidence(trend, health, has_schedule=False)
    return FailureForecast(
        predicted_failure_date=predicted,
        failure_confidence=round(confidence, 2),
        days_to_failure=horizon,
        basis="health_band_horizon",
        daily_usage=round(daily_usage, 2),
    )


def _forecast_confidence(
    trend: TrendResult,
    health: HealthAssessment | None,
    *,
    has_schedule: bool,
) -> float:
    """Blend sample count, usage stability and band into a 0-1 confidence."""
    base = 0.55 if has_schedule else 0.3
    # More samples → more confidence (saturating).
    sample_boost = min(0.25, 0.03 * max(0, trend.samples - MIN_SAMPLES_FOR_TREND))
    # Stable usage (small slope relative to rate) → more confidence.
    stability = 0.0
    if trend.daily_usage_recent > 0:
        volatility = abs(trend.slope_per_day) / (trend.daily_usage_recent + 1e-6)
        stability = max(0.0, 0.15 * (1.0 - min(1.0, volatility)))
    band_adj = 0.0
    if health is not None:
        band_adj = {"green": 0.05, "amber": 0.0, "red": -0.05}.get(health.band, 0.0)
    conf = base + sample_boost + stability + band_adj
    return max(0.05, min(0.95, conf))


@dataclass
class FleetUnitInsight:
    """Per-unit figures used to build fleet recommendations."""

    equipment_id: str
    code: str
    name: str
    utilization_pct: float
    open_work_orders: int
    health_band: str = "amber"
    daily_holding_cost: Decimal = DEFAULT_IDLE_DAY_COST


def fleet_recommendations(
    units: list[FleetUnitInsight],
    *,
    target_utilization_pct: float = 70.0,
    window_days: int = 30,
) -> dict[str, object]:
    """Build deterministic fleet-optimisation recommendations.

    Returns a dict shaped for :class:`FleetOptimizationResponse`:

    * **underutilized**: units below the utilisation floor, with the
      estimated idle-cost saving from redeploying / off-hiring them.
    * **maintenance_bundles**: units that should be serviced together
      (grouped by health band) to share a single mobilisation.
    * **estimated_monthly_savings**: sum of the idle-cost opportunities.
    """
    underutilized: list[dict[str, object]] = []
    total_savings = Decimal("0")

    for u in units:
        if u.utilization_pct < UNDERUTILISED_THRESHOLD_PCT:
            idle_fraction = max(0.0, (target_utilization_pct - u.utilization_pct) / 100.0)
            idle_days = idle_fraction * window_days
            saving = (u.daily_holding_cost * Decimal(str(round(idle_days, 2)))).quantize(Decimal("0.01"))
            total_savings += saving
            underutilized.append(
                {
                    "equipment_id": u.equipment_id,
                    "code": u.code,
                    "name": u.name,
                    "utilization_pct": round(u.utilization_pct, 1),
                    "estimated_idle_days": round(idle_days, 1),
                    "estimated_monthly_saving": str(saving),
                }
            )

    # Maintenance bundles: group units needing attention (amber/red band or
    # open WOs) so a single technician trip covers several machines.
    needs_service = [u for u in units if u.health_band in ("amber", "red") or u.open_work_orders > 0]
    bundles: list[dict[str, object]] = []
    if len(needs_service) >= 2:
        red = [u for u in needs_service if u.health_band == "red"]
        amber = [u for u in needs_service if u.health_band != "red"]
        if len(red) >= 2:
            bundles.append(_bundle("Priority service run", red))
        if len(amber) >= 2:
            bundles.append(_bundle("Routine service run", amber))
        if not bundles:
            bundles.append(_bundle("Combined service run", needs_service))

    underutilized.sort(key=lambda d: float(d["estimated_monthly_saving"]), reverse=True)  # type: ignore[arg-type]

    return {
        "underutilized": underutilized,
        "underutilized_count": len(underutilized),
        "maintenance_bundles": bundles,
        "estimated_monthly_savings": str(total_savings.quantize(Decimal("0.01"))),
        "target_utilization_pct": target_utilization_pct,
    }


def _bundle(label: str, units: list[FleetUnitInsight]) -> dict[str, object]:
    return {
        "label": label,
        "equipment_ids": [u.equipment_id for u in units],
        "codes": [u.code for u in units],
        "unit_count": len(units),
    }


# ── Service layer ──────────────────────────────────────────────────────────


class EquipmentPredictiveService:
    """Orchestrates predictive analytics over persisted equipment data."""

    def __init__(self, session: AsyncSession, tenant_id: str | None = None) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.equipment_repo = EquipmentRepository(session, tenant_id)
        self.telemetry_repo = TelemetryRepository(session, tenant_id)
        self.workorder_repo = WorkOrderRepository(session, tenant_id)

    @staticmethod
    def _to_samples(readings: list[TelemetryReading]) -> list[TelemetrySample]:
        out: list[TelemetrySample] = []
        for r in readings:
            out.append(
                TelemetrySample(
                    recorded_at=r.recorded_at,
                    hour_meter=float(r.hour_meter) if r.hour_meter is not None else None,
                    odometer_km=float(r.odometer_km) if r.odometer_km is not None else None,
                    fuel_level=float(r.fuel_level) if r.fuel_level is not None else None,
                    engine_status=r.engine_status,
                )
            )
        return out

    async def _overdue_inspection(self, equipment_id: uuid.UUID) -> bool:
        from app.modules.equipment.repository import InspectionRepository

        repo = InspectionRepository(self.session, self.tenant_id)
        today_iso = date.today().isoformat()
        expired = await repo.expired_for_equipment(equipment_id, today_iso)
        return len(expired) > 0

    async def analyze_equipment_health(self, equipment_id: uuid.UUID) -> HealthAssessment:
        """Health score + anomalies + maintenance trend for one unit."""
        # Pull a generous history window so the maths has enough samples.
        readings = await self.telemetry_repo.list_since(equipment_id, since=None, limit=1000)
        samples = self._to_samples(readings)
        open_wo = await self.workorder_repo.count_open_for_equipment(equipment_id)
        overdue = await self._overdue_inspection(equipment_id)
        return analyze_health(
            samples,
            open_work_orders=open_wo,
            overdue_inspection=overdue,
        )

    async def forecast_maintenance_need(self, equipment_id: uuid.UUID) -> FailureForecast:
        """Predicted next-service date + confidence for one unit."""
        from app.modules.equipment.repository import MaintenanceScheduleRepository

        equipment = await self.equipment_repo.get_by_id(equipment_id)
        current_hours = float(equipment.hour_meter) if equipment and equipment.hour_meter is not None else 0.0

        readings = await self.telemetry_repo.list_since(equipment_id, since=None, limit=1000)
        samples = self._to_samples(readings)

        sched_repo = MaintenanceScheduleRepository(self.session, self.tenant_id)
        schedules = await sched_repo.list_for_equipment(equipment_id)
        # Earliest upcoming hours-based service meter, if any.
        next_meter: float | None = None
        for s in schedules:
            if not s.active or s.trigger_type != "hours" or s.next_due_meter is None:
                continue
            meter = float(s.next_due_meter)
            if meter > current_hours and (next_meter is None or meter < next_meter):
                next_meter = meter

        open_wo = await self.workorder_repo.count_open_for_equipment(equipment_id)
        overdue = await self._overdue_inspection(equipment_id)
        health = analyze_health(samples, open_work_orders=open_wo, overdue_inspection=overdue)

        return forecast_failure(
            samples,
            current_hour_meter=current_hours,
            next_service_meter=next_meter,
            health=health,
        )

    async def fleet_optimization_recommendations(
        self,
        *,
        target_utilization_pct: float = 70.0,
        window_days: int = 30,
    ) -> dict[str, object]:
        """Fleet-wide optimisation: idle units, service bundles, savings."""
        from app.modules.equipment.repository import utilization_for_equipment

        units, _ = await self.equipment_repo.list_(limit=10_000)
        today = date.today()
        month_start = today.replace(day=1).isoformat()
        today_iso = today.isoformat()

        insights: list[FleetUnitInsight] = []
        for e in units:
            util = await utilization_for_equipment(self.session, e.id, month_start, today_iso)
            open_wo = await self.workorder_repo.count_open_for_equipment(e.id)
            # Cheap health proxy from open WOs only (full telemetry health per
            # unit would be O(N) extra queries; the bundle grouping only needs
            # a coarse band).
            if open_wo >= 2:
                band = "red"
            elif open_wo == 1 or e.status != "active":
                band = "amber"
            else:
                band = "green"
            holding = DEFAULT_IDLE_DAY_COST
            insights.append(
                FleetUnitInsight(
                    equipment_id=str(e.id),
                    code=e.code,
                    name=e.name,
                    utilization_pct=util,
                    open_work_orders=open_wo,
                    health_band=band,
                    daily_holding_cost=holding,
                )
            )

        result = fleet_recommendations(
            insights,
            target_utilization_pct=target_utilization_pct,
            window_days=window_days,
        )
        result["total_units"] = len(units)
        result["window_days"] = window_days
        return result
