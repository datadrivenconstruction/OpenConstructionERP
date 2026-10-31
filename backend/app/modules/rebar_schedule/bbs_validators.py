# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules for manually entered bar bending schedules (rule set ``bar_bending_schedule``).

Each rule reads the dict built by ``RebarScheduleService.bbs_validation_payload``:
``{"rows": [{"id", "member", "bar_mark", "diameter_mm", "lap_length_mm", "unit_weight_kg_m",
"weight_kg", "boq_position_id"}], "positions": {id: {"ordinal", "unit", "quantity"}},
"lap_multiple": Decimal, "tolerance_pct": Decimal}``.

* ``bar_bending_schedule.lap_length_min`` (ERROR): a stated lap or anchorage length is at least
  the configured multiple of the bar diameter (default 50).
* ``bar_bending_schedule.unit_weight`` (ERROR): the row's unit weight is d squared over 162.
* ``bar_bending_schedule.total_vs_boq`` (WARNING): the steel scheduled against a BOQ
  reinforcement position is within the tolerance (default 5 percent) of its quantity.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.rebar_schedule.bbs import unit_weight

RULE_SET = "bar_bending_schedule"

DEFAULT_LAP_MULTIPLE = Decimal("50")
DEFAULT_TOLERANCE_PCT = Decimal("5")

#: Kilograms per BOQ unit for the units a reinforcement position is billed in.
KG_PER_UNIT: dict[str, Decimal] = {
    "kg": Decimal("1"),
    "t": Decimal("1000"),
    "to": Decimal("1000"),
    "tonne": Decimal("1000"),
    "mt": Decimal("1000"),
    "qtl": Decimal("100"),
    "cwt": Decimal("50.80234544"),
}


def _dec(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _ref(row: dict[str, Any]) -> str:
    return f"{row.get('member')}/{row.get('bar_mark')}"


class _Rule(ValidationRule):
    standard = RULE_SET

    def _result(self, ref: str, passed: bool, message: str, **details: Any) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message="OK" if passed else message,
            element_ref=ref,
            details={k: str(v) if isinstance(v, Decimal) else v for k, v in details.items()},
        )


class LapLengthMinRule(_Rule):
    rule_id = "bar_bending_schedule.lap_length_min"
    name = "Lap or anchorage length at least the diameter multiple"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "A stated lap or anchorage length is at least the configured multiple of the bar diameter"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        multiple = _dec(data.get("lap_multiple")) or DEFAULT_LAP_MULTIPLE
        out = []
        for row in data.get("rows") or []:
            lap = _dec(row.get("lap_length_mm"))
            dia = _dec(row.get("diameter_mm"))
            if lap is None or dia is None:
                continue
            need = (multiple * dia).normalize()
            out.append(
                self._result(
                    _ref(row),
                    lap >= need,
                    f"Bar {_ref(row)}: lap {lap} mm is under {multiple} x {dia} mm = {need} mm",
                    lap_length_mm=lap,
                    required_mm=need,
                )
            )
        return out


class UnitWeightRule(_Rule):
    rule_id = "bar_bending_schedule.unit_weight"
    name = "Unit weight is d squared over 162"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "The unit weight of each bar mark matches d squared over 162 kg/m"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for row in _data(context).get("rows") or []:
            dia = _dec(row.get("diameter_mm"))
            stated = _dec(row.get("unit_weight_kg_m"))
            if dia is None or stated is None:
                continue
            expected = unit_weight(dia)
            out.append(
                self._result(
                    _ref(row),
                    abs(stated - expected) <= expected * Decimal("0.005"),
                    f"Bar {_ref(row)}: unit weight {stated} kg/m, expected {expected} kg/m for {dia} mm",
                    stated=stated,
                    expected=expected,
                )
            )
        return out


class TotalVsBoqRule(_Rule):
    rule_id = "bar_bending_schedule.total_vs_boq"
    name = "Scheduled steel matches the BOQ reinforcement quantity"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Steel scheduled against a BOQ position is within the tolerance of its quantity"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        tolerance = _dec(data.get("tolerance_pct")) or DEFAULT_TOLERANCE_PCT
        positions: dict[str, dict[str, Any]] = data.get("positions") or {}
        scheduled: dict[str, Decimal] = {}
        for row in data.get("rows") or []:
            pid = row.get("boq_position_id")
            if pid:
                scheduled[str(pid)] = scheduled.get(str(pid), Decimal("0")) + (_dec(row.get("weight_kg")) or 0)
        out = []
        for pid, kg in scheduled.items():
            pos = positions.get(pid)
            if pos is None:
                continue
            unit = str(pos.get("unit") or "").strip().lower()
            factor = KG_PER_UNIT.get(unit)
            ordinal = pos.get("ordinal") or pid
            if factor is None:
                out.append(
                    self._result(
                        str(ordinal),
                        False,
                        f"Position {ordinal} is billed in {unit or '-'}, not a weight; scheduled steel is {kg} kg",
                        scheduled_kg=kg,
                    )
                )
                continue
            boq_kg = (_dec(pos.get("quantity")) or Decimal("0")) * factor
            dev = (abs(kg - boq_kg) / boq_kg * 100).quantize(Decimal("0.01")) if boq_kg else Decimal("100")
            out.append(
                self._result(
                    str(ordinal),
                    dev <= tolerance,
                    f"Position {ordinal}: scheduled {kg.quantize(Decimal('0.1'))} kg against BOQ "
                    f"{boq_kg.quantize(Decimal('0.1'))} kg, {dev}% apart (tolerance {tolerance}%)",
                    scheduled_kg=kg,
                    boq_kg=boq_kg,
                    deviation_pct=dev,
                )
            )
        return out


RULES: tuple[ValidationRule, ...] = (LapLengthMinRule(), UnitWeightRule(), TotalVsBoqRule())


def register_bbs_rules() -> None:
    """Register the ``bar_bending_schedule`` rule set."""
    for rule in RULES:
        rule_registry.register(rule, [RULE_SET])
