# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rule set ``measurement``.

Payload::

    {"sheets": [{"item_ref", "unit", "row_decimals", "target_quantity",
                 "lines": [{"ref", "description", "formula", "variables", ...}]}]}

``target_quantity`` is the quantity of the BOQ position the sheet belongs to;
a sheet without one is not reconciled.
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
from app.modules.measurement.formula import MeasurementError, safe_eval
from app.modules.measurement.model import build_sheet, reconcile

MEASUREMENT_RULE_SET = "measurement"


def _sheets(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data if isinstance(context.data, dict) else {}
    rows = data.get("sheets") or []
    return [r for r in rows if isinstance(r, dict)]


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


class FormulaParses(ValidationRule):
    """Every formula line of a sheet evaluates, so its quantity is not silently zero."""

    rule_id = "measurement.formula_parses"
    name = "Measurement Formula Parses"
    standard = "measurement"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Every take-off formula parses and evaluates with its variables."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for sheet in _sheets(context):
            for index, line in enumerate(sheet.get("lines") or [], start=1):
                if not isinstance(line, dict):
                    continue
                # Dimension mode (Nos x L x B x D) ignores the formula.
                if any(line.get(k) not in (None, "") for k in ("nos", "length", "breadth", "depth")):
                    continue
                ref = f"{sheet.get('item_ref', '')}#{line.get('ref') or index}"
                try:
                    safe_eval(str(line.get("formula") or ""), line.get("variables") or {})
                except MeasurementError as exc:
                    out.append(_result(self, False, f"Formula on {ref} does not evaluate: {exc}", ref, error=str(exc)))
                else:
                    out.append(_result(self, True, "", ref))
        return out


class SheetReconcilesWithBoqQty(ValidationRule):
    """A sheet's measured total matches the quantity of the position it supports."""

    rule_id = "measurement.sheet_reconciles_with_boq_qty"
    name = "Measurement Sheet Reconciles With BOQ Quantity"
    standard = "measurement"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "The take-off total equals the BOQ position quantity within tolerance."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for sheet in _sheets(context):
            target = sheet.get("target_quantity")
            if target in (None, ""):
                continue
            ref = str(sheet.get("item_ref") or "")
            try:
                Decimal(str(target))
                built = build_sheet(
                    item_ref=ref,
                    description="",
                    unit=str(sheet.get("unit") or ""),
                    lines=list(sheet.get("lines") or []),
                    strict=False,
                    row_decimals=sheet.get("row_decimals"),
                )
            except (MeasurementError, InvalidOperation, ValueError):
                continue  # an unreadable sheet is formula_parses' finding
            result = reconcile(built, target, tolerance=sheet.get("tolerance") or "0.001")
            out.append(
                _result(
                    self,
                    bool(result["matches"]),
                    (
                        f"Take-off for {ref} totals {result['measured_quantity']} but the position quantity is "
                        f"{result['target_quantity']} (difference {result['difference']})"
                    ),
                    ref,
                    **{k: str(v) for k, v in result.items()},
                )
            )
        return out


MEASUREMENT_RULES = (FormulaParses, SheetReconcilesWithBoqQty)


def register_measurement_rules() -> None:
    """Idempotently register the measurement rules."""
    for rule in MEASUREMENT_RULES:
        rule_registry.register(rule(), rule_sets=[MEASUREMENT_RULE_SET])


register_measurement_rules()
