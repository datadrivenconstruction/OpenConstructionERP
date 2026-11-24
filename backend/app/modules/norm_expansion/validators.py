# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rule set ``norm_expansion``.

Payload::

    {"norm": {"work_key", "labor_hours_per_unit", "machine_hours_per_unit",
              "materials": [{"name", "unit", "qty_per_unit"}]}}

All rules are warnings: a norm in progress may be saved incomplete, but the
estimator hears why it would expand into no (or double-counted) resources.
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

NORM_EXPANSION_RULE_SET = "norm_expansion"


def _norm(context: ValidationContext) -> dict[str, Any]:
    data = context.data if isinstance(context.data, dict) else {}
    norm = data.get("norm")
    return norm if isinstance(norm, dict) else {}


def _materials(norm: dict[str, Any]) -> list[dict[str, Any]]:
    return [m for m in (norm.get("materials") or []) if isinstance(m, dict)]


def _num(value: Any) -> Decimal:
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")
    return dec if dec.is_finite() else Decimal("0")


def _result(rule: ValidationRule, passed: bool, message: str, ref: str, **details: Any) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message="OK" if passed else message,
        element_ref=ref,
        details=details,
    )


class NormHasDemand(ValidationRule):
    """A norm demands some labour, plant or material per unit."""

    rule_id = "norm_expansion.norm_has_demand"
    name = "Norm Has Demand"
    standard = "norm_expansion"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A production norm has labour-hours, machine-hours or a material above zero."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        norm = _norm(context)
        if not norm:
            return []
        ref = str(norm.get("work_key") or "")
        demand = (
            _num(norm.get("labor_hours_per_unit")) > 0
            or _num(norm.get("machine_hours_per_unit")) > 0
            or any(_num(m.get("qty_per_unit")) > 0 for m in _materials(norm))
        )
        return [_result(self, demand, f"Norm {ref} expands into no labour, plant or material", ref)]


class MaterialQuantityPositive(ValidationRule):
    """Every material line consumes a quantity above zero."""

    rule_id = "norm_expansion.material_qty_positive"
    name = "Material Quantity Positive"
    standard = "norm_expansion"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A material line on a norm has a quantity per unit above zero."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        norm = _norm(context)
        ref = str(norm.get("work_key") or "")
        zero = [str(m.get("name") or "") for m in _materials(norm) if _num(m.get("qty_per_unit")) <= 0]
        if not norm:
            return []
        return [
            _result(
                self,
                not zero,
                f"Norm {ref} has materials with no quantity: " + ", ".join(zero),
                ref,
                materials=zero,
            )
        ]


class NoDuplicateMaterial(ValidationRule):
    """The same material in the same unit appears once per norm."""

    rule_id = "norm_expansion.no_duplicate_material"
    name = "No Duplicate Material"
    standard = "norm_expansion"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "A material in one unit is listed once on a norm, so its demand is not counted twice."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        norm = _norm(context)
        if not norm:
            return []
        ref = str(norm.get("work_key") or "")
        seen: set[tuple[str, str]] = set()
        dupes: list[str] = []
        for m in _materials(norm):
            key = (str(m.get("name") or "").strip().lower(), str(m.get("unit") or "").strip().lower())
            if key in seen and key[0]:
                dupes.append(str(m.get("name")))
            seen.add(key)
        return [_result(self, not dupes, f"Norm {ref} lists a material twice: " + ", ".join(dupes), ref)]


NORM_EXPANSION_RULES = (NormHasDemand, MaterialQuantityPositive, NoDuplicateMaterial)


def register_norm_expansion_rules() -> None:
    """Idempotently register the norm expansion rules."""
    for rule in NORM_EXPANSION_RULES:
        rule_registry.register(rule(), rule_sets=[NORM_EXPANSION_RULE_SET])


register_norm_expansion_rules()
