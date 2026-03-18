"""Built-in validation rules.

Registers all standard rule sets that ship with OpenEstimate.
Modules can register additional rules via the rule_registry.
"""

import logging
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

logger = logging.getLogger(__name__)


# ── BOQ Quality Rules (Universal) ──────────────────────────────────────────


class PositionHasQuantity(ValidationRule):
    rule_id = "boq_quality.position_has_quantity"
    name = "Position Has Quantity"
    standard = "boq_quality"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Every BOQ position must have a non-zero quantity"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            qty = pos.get("quantity", 0)
            passed = qty is not None and float(qty) > 0
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Position {pos.get('ordinal', '?')} has zero/missing quantity",
                    element_ref=pos.get("id"),
                    suggestion="Set a quantity greater than 0" if not passed else None,
                )
            )
        return results


class PositionHasUnitRate(ValidationRule):
    rule_id = "boq_quality.position_has_unit_rate"
    name = "Position Has Unit Rate"
    standard = "boq_quality"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Every BOQ position should have a unit rate assigned"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            rate = pos.get("unit_rate", 0)
            passed = rate is not None and float(rate) > 0
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Position {pos.get('ordinal', '?')} has no unit rate",
                    element_ref=pos.get("id"),
                    suggestion="Assign a rate from the cost database" if not passed else None,
                )
            )
        return results


class PositionHasDescription(ValidationRule):
    rule_id = "boq_quality.position_has_description"
    name = "Position Has Description"
    standard = "boq_quality"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Every BOQ position must have a description"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            desc = (pos.get("description") or "").strip()
            passed = len(desc) >= 3
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Position {pos.get('ordinal', '?')} missing description",
                    element_ref=pos.get("id"),
                )
            )
        return results


class NoDuplicateOrdinals(ValidationRule):
    rule_id = "boq_quality.no_duplicate_ordinals"
    name = "No Duplicate Ordinals"
    standard = "boq_quality"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "BOQ positions must have unique ordinal numbers"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        positions = _get_positions(context)
        ordinals: dict[str, list[str]] = {}
        for pos in positions:
            ord_val = pos.get("ordinal", "")
            if ord_val:
                ordinals.setdefault(ord_val, []).append(pos.get("id", "?"))

        results: list[RuleResult] = []
        for ordinal, ids in ordinals.items():
            passed = len(ids) == 1
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Duplicate ordinal '{ordinal}' found in {len(ids)} positions",
                    element_ref=ids[0] if len(ids) == 1 else None,
                    details={"duplicate_ids": ids} if not passed else {},
                )
            )
        return results


class UnitRateInRange(ValidationRule):
    rule_id = "boq_quality.unit_rate_in_range"
    name = "Unit Rate Anomaly Detection"
    standard = "boq_quality"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "Flags unit rates that deviate significantly from median"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        positions = _get_positions(context)
        rates = [float(p.get("unit_rate", 0)) for p in positions if p.get("unit_rate")]
        if len(rates) < 3:
            return []

        rates_sorted = sorted(rates)
        median = rates_sorted[len(rates_sorted) // 2]
        threshold = median * 5  # Flag if >5x median

        results: list[RuleResult] = []
        for pos in positions:
            rate = float(pos.get("unit_rate", 0)) if pos.get("unit_rate") else 0
            if rate <= 0:
                continue
            passed = rate <= threshold
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else (
                        f"Position {pos.get('ordinal', '?')}: rate {rate:.2f} "
                        f"is >{threshold:.2f} (5x median)"
                    ),
                    element_ref=pos.get("id"),
                    details={"rate": rate, "median": median, "threshold": threshold},
                    suggestion="Verify this unit rate — it's unusually high"
                    if not passed
                    else None,
                )
            )
        return results


# ── DIN 276 Rules (DACH) ──────────────────────────────────────────────────


class DIN276CostGroupRequired(ValidationRule):
    rule_id = "din276.cost_group_required"
    name = "DIN 276 Cost Group Required"
    standard = "din276"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Every BOQ position must have a DIN 276 cost group (Kostengruppe)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            kg = (pos.get("classification") or {}).get("din276", "")
            passed = bool(kg) and len(str(kg)) >= 3
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Position {pos.get('ordinal', '?')} missing DIN 276 KG",
                    element_ref=pos.get("id"),
                    suggestion="Assign a 3-digit DIN 276 Kostengruppe (e.g., 330 for walls)"
                    if not passed
                    else None,
                )
            )
        return results


class DIN276ValidCostGroup(ValidationRule):
    rule_id = "din276.valid_cost_group"
    name = "Valid DIN 276 Cost Group"
    standard = "din276"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "DIN 276 cost group code must be a valid 3-digit code"

    # Valid top-level groups (1st digit)
    VALID_TOP_GROUPS = {"1", "2", "3", "4", "5", "6", "7"}

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            kg = str((pos.get("classification") or {}).get("din276", ""))
            if not kg:
                continue  # Handled by cost_group_required
            passed = len(kg) == 3 and kg.isdigit() and kg[0] in self.VALID_TOP_GROUPS
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Invalid DIN 276 code '{kg}' in position {pos.get('ordinal', '?')}",
                    element_ref=pos.get("id"),
                    details={"given_code": kg},
                )
            )
        return results


# ── GAEB Rules (DACH) ─────────────────────────────────────────────────────


class GAEBOrdinalFormat(ValidationRule):
    rule_id = "gaeb.ordinal_format"
    name = "GAEB Ordinal Number Format"
    standard = "gaeb"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Ordinal numbers should follow GAEB LV structure (e.g., 01.02.0030)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        import re

        pattern = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")  # XX.XX.XXXX
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            ordinal = pos.get("ordinal", "")
            if not ordinal:
                continue
            passed = bool(pattern.match(ordinal))
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Ordinal '{ordinal}' doesn't match GAEB format XX.XX.XXXX",
                    element_ref=pos.get("id"),
                    suggestion="Use format like 01.02.0030" if not passed else None,
                )
            )
        return results


# ── Helpers ─────────────────────────────────────────────────────────────────


def _get_positions(context: ValidationContext) -> list[dict[str, Any]]:
    """Extract positions list from context data (handles different data shapes)."""
    data = context.data
    if isinstance(data, dict):
        return data.get("positions", [])
    if isinstance(data, list):
        return data
    return []


# ── Registration ────────────────────────────────────────────────────────────


def register_builtin_rules() -> None:
    """Register all built-in validation rules."""
    rules: list[tuple[ValidationRule, list[str] | None]] = [
        # BOQ Quality (universal)
        (PositionHasQuantity(), None),
        (PositionHasUnitRate(), None),
        (PositionHasDescription(), None),
        (NoDuplicateOrdinals(), None),
        (UnitRateInRange(), None),
        # DIN 276 (DACH)
        (DIN276CostGroupRequired(), None),
        (DIN276ValidCostGroup(), None),
        # GAEB (DACH)
        (GAEBOrdinalFormat(), None),
    ]

    for rule, sets in rules:
        rule_registry.register(rule, sets)

    logger.info(
        "Registered %d built-in validation rules across %d rule sets",
        len(rules),
        len(rule_registry.list_rule_sets()),
    )
