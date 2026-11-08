# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rule set​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ ``site_sensors``.

Payload built by ``SiteSensorsService.validation_payload``::

    {"devices": [{"id", "code", "kind", "active", "offline", "has_limit", "has_mix",
                  "interval_min", "max_gap_min", "max_jump_per_h", "min", "max"}],
     "mixes": [{"id", "code", "points", "r2"}],
     "pours": [{"id", "code", "strength_status"}],
     "exceedances": [{"id", "device", "status", "value", "limit"}],
     "strips": [{"id", "element", "struck", "target_mpa", "strength_at_strike_mpa", "reason"}]}

Each result carries ``details.message_key`` and its parameters for the client.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.site_sensors.analysis import TEMP_MAX_C, TEMP_MAX_JUMP_K_PER_H, TEMP_MIN_C

SENSOR_RULE_SET = "site_sensors"
#: A calibration with fewer cubes or a weaker fit than this is not trusted for a strike decision.
MIN_CALIBRATION_POINTS = 4
MIN_CALIBRATION_R2 = 0.9


def _rows(context: ValidationContext, key: str) -> list[dict[str, Any]]:
    data = context.data if isinstance(context.data, dict) else {}
    raw = data.get(key) or []
    return [r for r in raw if isinstance(r, dict)]


class _SensorRule(ValidationRule):
    standard = "site_sensors"
    category = RuleCategory.COMPLIANCE
    severity = Severity.WARNING
    key = ""
    text = ""
    rows_key = ""

    def _result(self, ref: str, passed: bool, **params: Any) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message="OK" if passed else self.text.format(**params),
            element_ref=ref,
            details={"message_key": f"siteSensors.rules.{self.key}", **{k: str(v) for k, v in params.items()}},
        )

    def check(self, row: dict[str, Any]) -> RuleResult | None:
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [r for row in _rows(context, self.rows_key) if (r := self.check(row)) is not None]


class SensorOnline(_SensorRule):
    """An active sensor has reported within its offline window."""

    key = "sensor_online"
    rule_id = "site_sensors.sensor_online"
    name = "Sensor Online"
    description = "Every active sensor reported within its offline window."
    rows_key = "devices"
    text = "Sensor {device} has stopped reporting"

    def check(self, row: dict[str, Any]) -> RuleResult | None:
        if not row.get("active"):
            return None
        return self._result(str(row.get("id")), not row.get("offline"), device=row.get("code", ""))


class ExceedanceAcknowledged(_SensorRule):
    """A reading above its limit has been seen and acknowledged by a person."""

    key = "exceedance_acknowledged"
    rule_id = "site_sensors.exceedance_acknowledged"
    name = "Exceedance Acknowledged"
    description = "Every limit exceedance is acknowledged."
    severity = Severity.ERROR
    rows_key = "exceedances"
    text = "Sensor {device} read {value} above its limit of {limit} and nobody has acknowledged it"

    def check(self, row: dict[str, Any]) -> RuleResult | None:
        return self._result(
            str(row.get("id")),
            row.get("status") != "open",
            device=row.get("device", ""),
            value=row.get("value"),
            limit=row.get("limit"),
        )


class StrikeAfterTargetStrength(_SensorRule):
    """Formwork was struck once the estimated strength reached the target, or with a recorded reason."""

    key = "strike_after_target_strength"
    rule_id = "site_sensors.strike_after_target_strength"
    name = "Strike After Target Strength"
    description = "No formwork is struck below its target strength without a recorded reason."
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    rows_key = "strips"
    text = "Formwork on {element} was struck at {strength} MPa, below the target of {target} MPa"

    def check(self, row: dict[str, Any]) -> RuleResult | None:
        if not row.get("struck"):
            return None
        raw = row.get("strength_at_strike_mpa")
        strength = Decimal(str(raw)) if raw is not None else Decimal("0")
        target = Decimal(str(row.get("target_mpa") or 0))
        return self._result(
            str(row.get("id")),
            strength >= target or bool(str(row.get("reason") or "").strip()),
            element=row.get("element", ""),
            strength=strength,
            target=target,
        )


class DeviceHasLimit(_SensorRule):
    """A monitoring sensor has a limit, its own or the country's, so an exceedance can be seen."""

    key = "device_has_limit"
    rule_id = "site_sensors.device_has_limit"
    name = "Device Has Limit"
    description = "Every active monitoring sensor has a limit from the device or the country data."
    category = RuleCategory.COMPLETENESS
    rows_key = "devices"
    text = "Sensor {device} has no limit; set one on the device"

    def check(self, row: dict[str, Any]) -> RuleResult | None:
        if not row.get("active") or "has_limit" not in row or row.get("kind") in ("concrete_maturity", "weather"):
            return None
        return self._result(str(row.get("id")), bool(row.get("has_limit")), device=row.get("code", ""))


class ConcreteSensorHasMix(_SensorRule):
    """A concrete sensor is linked to a mix, without which there is no strength."""

    key = "concrete_sensor_has_mix"
    rule_id = "site_sensors.concrete_sensor_has_mix"
    name = "Concrete Sensor Has Mix"
    description = "Every active concrete sensor is linked to a mix."
    category = RuleCategory.COMPLETENESS
    rows_key = "devices"
    text = "Concrete sensor {device} has no mix, so no strength can be estimated"

    def check(self, row: dict[str, Any]) -> RuleResult | None:
        if not row.get("active") or "has_mix" not in row or row.get("kind") != "concrete_maturity":
            return None
        return self._result(str(row.get("id")), bool(row.get("has_mix")), device=row.get("code", ""))


class CurveCalibrated(_SensorRule):
    """A mix curve rests on the mix's own calibration cubes, not on typed-in numbers alone."""

    key = "curve_calibrated"
    rule_id = "site_sensors.curve_calibrated"
    name = "Curve Calibrated"
    description = "Every mix curve has a calibration table of cube results."
    category = RuleCategory.COMPLETENESS
    rows_key = "mixes"
    text = "Mix {mix} has no calibration cubes; its curve is not verified"

    def check(self, row: dict[str, Any]) -> RuleResult | None:
        return self._result(str(row.get("id")), int(row.get("points") or 0) > 0, mix=row.get("code", ""))


class CalibrationQuality(_SensorRule):
    """A calibration has enough cubes and a close enough fit to trust."""

    key = "calibration_quality"
    rule_id = "site_sensors.calibration_quality"
    name = "Calibration Quality"
    description = "A mix calibration has at least 4 cubes and an R² of 0.9 or more."
    rows_key = "mixes"
    text = "Mix {mix} is calibrated on {points} cubes with R² {r2}; use at least 4 cubes and R² of 0.9 or more"

    def check(self, row: dict[str, Any]) -> RuleResult | None:
        points = int(row.get("points") or 0)
        if points == 0:
            return None
        r2 = row.get("r2")
        ok = points >= MIN_CALIBRATION_POINTS and r2 is not None and float(r2) >= MIN_CALIBRATION_R2
        shown = f"{float(r2):.2f}" if r2 is not None else "-"
        return self._result(str(row.get("id")), ok, mix=row.get("code", ""), points=points, r2=shown)


class EstimateInCalibratedRange(_SensorRule):
    """A strength estimate lies inside the maturity range the mix was calibrated over."""

    key = "estimate_in_calibrated_range"
    rule_id = "site_sensors.estimate_in_calibrated_range"
    name = "Estimate In Calibrated Range"
    description = "No strength estimate is extrapolated beyond the last calibration cube."
    rows_key = "pours"
    text = "Sensor {device} is past the last calibration cube; its strength is extrapolated"

    def check(self, row: dict[str, Any]) -> RuleResult | None:
        if row.get("strength_status") not in ("ok", "above_range"):
            return None
        return self._result(str(row.get("id")), row.get("strength_status") == "ok", device=row.get("code", ""))


class NoReadingGap(_SensorRule):
    """A sensor reports without gaps longer than twice its usual interval."""

    key = "no_reading_gap"
    rule_id = "site_sensors.no_reading_gap"
    name = "No Reading Gap"
    description = "No gap between readings is longer than twice the sensor's usual interval."
    rows_key = "devices"
    text = "Sensor {device} has a gap of {gap} min, more than twice its usual {interval} min"

    def check(self, row: dict[str, Any]) -> RuleResult | None:
        interval = row.get("interval_min")
        gap = row.get("max_gap_min")
        if not row.get("active") or not interval or gap is None:
            return None
        return self._result(
            str(row.get("id")),
            float(gap) <= 2 * float(interval),
            device=row.get("code", ""),
            gap=f"{float(gap):g}",
            interval=f"{float(interval):g}",
        )


class TemperaturePlausible(_SensorRule):
    """A concrete probe reads inside -30..90 degC and changes no faster than 15 K per hour."""

    key = "temperature_plausible"
    rule_id = "site_sensors.temperature_plausible"
    name = "Temperature Plausible"
    description = "Concrete temperatures stay within -30..90 °C and change by at most 15 K per hour."
    category = RuleCategory.CONSISTENCY
    rows_key = "devices"
    text = "Concrete sensor {device} reads {low}..{high} °C, changing up to {jump} K/h; check the probe"

    def check(self, row: dict[str, Any]) -> RuleResult | None:
        if row.get("kind") != "concrete_maturity" or row.get("min") is None:
            return None
        low, high, jump = float(row["min"]), float(row["max"]), float(row.get("max_jump_per_h") or 0)
        ok = low >= TEMP_MIN_C and high <= TEMP_MAX_C and jump <= TEMP_MAX_JUMP_K_PER_H
        return self._result(
            str(row.get("id")), ok, device=row.get("code", ""), low=f"{low:g}", high=f"{high:g}", jump=f"{jump:g}"
        )


SENSOR_RULES: tuple[type[_SensorRule], ...] = (
    SensorOnline,
    ExceedanceAcknowledged,
    StrikeAfterTargetStrength,
    DeviceHasLimit,
    ConcreteSensorHasMix,
    CurveCalibrated,
    CalibrationQuality,
    EstimateInCalibratedRange,
    NoReadingGap,
    TemperaturePlausible,
)


def register_sensor_rules() -> None:
    """Idempotently register the site sensor rules."""
    for rule in SENSOR_RULES:
        rule_registry.register(rule(), rule_sets=[SENSOR_RULE_SET])


async def run_rules(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every rule against one payload, as plain dicts."""
    context = ValidationContext(data=payload, metadata={})
    out: list[dict[str, Any]] = []
    for rule_cls in SENSOR_RULES:
        for r in await rule_cls().validate(context):
            out.append(
                {
                    "rule_id": r.rule_id,
                    "passed": r.passed,
                    "severity": str(getattr(r.severity, "value", r.severity)),
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "details": r.details,
                }
            )
    return out


register_sensor_rules()
