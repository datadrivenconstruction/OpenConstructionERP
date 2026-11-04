# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rule set​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ ``equipment_telematics``.

The rules read one payload, built by ``TelematicsService.validation_payload``::

    {
      "today": "YYYY-MM-DD",
      "idle_threshold": "0.35",
      "machines": [{"equipment_id", "code", "on_site_project_id", "allocated_project_id",
                    "maintenance_overdue": [...], "outside_geofence_m", "idle_ratio_7d"}],
    }

Each result carries ``details.message_key`` and its parameters so the client
renders the sentence in the user's language; ``message`` is the English text.
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

EQUIPMENT_RULE_SET = "equipment_telematics"


def _machines(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data if isinstance(context.data, dict) else {}
    rows = data.get("machines") or []
    return [r for r in rows if isinstance(r, dict)]


class _MachineRule(ValidationRule):
    standard = "equipment"
    category = RuleCategory.CONSISTENCY
    severity = Severity.WARNING
    key = ""
    text = ""

    def _result(self, machine: dict[str, Any], passed: bool, **params: Any) -> RuleResult:
        params = {"equipment": machine.get("code", ""), **params}
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message="OK" if passed else self.text.format(**params),
            element_ref=str(machine.get("equipment_id") or ""),
            details={"message_key": f"equipment.rules.{self.key}", **{k: str(v) for k, v in params.items()}},
        )

    def check(self, machine: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [r for m in _machines(context) if (r := self.check(m, context)) is not None]


class MachineOnSiteHasAllocation(_MachineRule):
    """A machine standing inside a project's site fence must be allocated to a project."""

    key = "on_site_allocated"
    rule_id = "equipment_telematics.on_site_allocated"
    name = "Machine On Site Is Allocated"
    description = "A machine inside a site geofence has an active rental to a project."
    severity = Severity.ERROR
    text = "{equipment} is on site but not allocated to any project, so its hire cost goes nowhere"

    def check(self, machine: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        if not machine.get("on_site_project_id"):
            return None
        return self._result(machine, bool(machine.get("allocated_project_id")))


class MaintenanceNotOverdue(_MachineRule):
    """No active maintenance schedule is past its engine-hour or date threshold."""

    key = "maintenance_overdue"
    rule_id = "equipment_telematics.maintenance_overdue"
    name = "Maintenance Not Overdue"
    description = "Every active maintenance schedule is below its due engine hours or date."
    severity = Severity.ERROR
    text = "{equipment} is overdue for maintenance (due at {due}, now {now})"

    def check(self, machine: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        overdue = machine.get("maintenance_overdue") or []
        if not overdue:
            return self._result(machine, True)
        first = overdue[0]
        return self._result(machine, False, due=first.get("due", ""), now=first.get("now", ""))


class MachineInsideGeofence(_MachineRule):
    """An allocated machine with a position stays inside its project's site fence."""

    key = "inside_geofence"
    rule_id = "equipment_telematics.inside_geofence"
    name = "Machine Inside Geofence"
    description = "An allocated machine's last position is inside its project's geofence."
    text = "{equipment} is {distance_m} m outside the site boundary of its project"

    def check(self, machine: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        raw = machine.get("outside_geofence_m")
        if raw is None:
            return None
        outside = Decimal(str(raw))
        return self._result(machine, outside <= 0, distance_m=outside)


class IdleBelowThreshold(_MachineRule):
    """Idle share of engine hours over the last seven days stays under the threshold."""

    key = "idle_threshold"
    rule_id = "equipment_telematics.idle_threshold"
    name = "Idle Below Threshold"
    description = "Idle hours are less than the threshold share of engine hours over seven days."
    severity = Severity.INFO
    text = "{equipment} idled {idle_pct}% of its engine hours this week (limit {limit_pct}%)"

    def check(self, machine: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        raw = machine.get("idle_ratio_7d")
        if raw is None:
            return None
        data = context.data if isinstance(context.data, dict) else {}
        limit = Decimal(str(data.get("idle_threshold") or "0.35"))
        ratio = Decimal(str(raw))
        return self._result(
            machine,
            ratio <= limit,
            idle_pct=(ratio * 100).quantize(Decimal("0.1")),
            limit_pct=(limit * 100).quantize(Decimal("0.1")),
        )


class DeviceReportsRegularly(_MachineRule):
    """A hired machine with a telematics device has sent a reading within the last 24 hours."""

    key = "device_silent"
    rule_id = "equipment_telematics.device_silent"
    name = "Device Reports Regularly"
    description = "A telematics device on a machine hired to a project has reported in the last 24 hours."
    text = "{equipment} has not reported for {hours} h while hired to a project; check the device and its power"

    def check(self, machine: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        if not machine.get("has_device") or not machine.get("allocated_project_id"):
            return None
        silent = machine.get("device_silent_hours")
        return self._result(machine, silent is None, hours=silent if silent is not None else 0)


class OwningCostKnown(_MachineRule):
    """A machine on the cost board has an owning cost basis, otherwise its cost reads as zero."""

    key = "owning_cost_known"
    rule_id = "equipment_telematics.owning_cost_known"
    name = "Owning Cost Known"
    description = "The machine has a purchase value with a useful life, or a monthly holding cost or rent."
    text = "{equipment} has no purchase value with useful life and no holding cost, so its owning cost shows as zero"

    def check(self, machine: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        known = machine.get("ownership_cost_known")
        if known is None:
            return None
        return self._result(machine, bool(known))


class CostPerHourWithinMarket(_MachineRule):
    """Total cost per used hour stays at or below the market hire rate per hour."""

    key = "cost_within_market"
    rule_id = "equipment_telematics.cost_within_market"
    name = "Cost Per Used Hour Within Market"
    description = "Owning plus operating cost per used hour does not exceed the market hire rate per hour."
    text = "{equipment} costs {cost_per_hour} per used hour against a market hire rate of {market_per_hour}"

    def check(self, machine: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        cost, market = machine.get("cost_per_used_hour"), machine.get("market_hour_rate")
        if cost is None or market is None or machine.get("currency_mismatch"):
            return None
        return self._result(
            machine,
            Decimal(str(cost)) <= Decimal(str(market)),
            cost_per_hour=cost,
            market_per_hour=market,
        )


EQUIPMENT_RULES: tuple[type[_MachineRule], ...] = (
    MachineOnSiteHasAllocation,
    MaintenanceNotOverdue,
    MachineInsideGeofence,
    IdleBelowThreshold,
    DeviceReportsRegularly,
    OwningCostKnown,
    CostPerHourWithinMarket,
)


def register_equipment_rules() -> None:
    """Idempotently register the equipment telematics rules."""
    for rule in EQUIPMENT_RULES:
        rule_registry.register(rule(), rule_sets=[EQUIPMENT_RULE_SET])


async def run_rules(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every rule against one payload, as plain dicts."""
    context = ValidationContext(data=payload, metadata={})
    out: list[dict[str, Any]] = []
    for rule_cls in EQUIPMENT_RULES:
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


register_equipment_rules()
