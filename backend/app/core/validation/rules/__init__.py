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


# ── Additional BOQ Quality Rules ──────────────────────────────────────────


class NegativeValues(ValidationRule):
    rule_id = "boq_quality.negative_values"
    name = "No Negative Values"
    standard = "boq_quality"
    severity = Severity.ERROR
    category = RuleCategory.QUALITY
    description = "Positions must not have negative quantity or unit_rate"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            qty = pos.get("quantity")
            rate = pos.get("unit_rate")
            qty_val = float(qty) if qty is not None else 0
            rate_val = float(rate) if rate is not None else 0
            passed = qty_val >= 0 and rate_val >= 0
            if not passed:
                parts: list[str] = []
                if qty_val < 0:
                    parts.append(f"quantity={qty_val}")
                if rate_val < 0:
                    parts.append(f"unit_rate={rate_val}")
                msg = (
                    f"Position {pos.get('ordinal', '?')} has negative "
                    f"{', '.join(parts)}"
                )
            else:
                msg = "OK"
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=msg,
                    element_ref=pos.get("id"),
                    suggestion="Correct negative values — use positive numbers"
                    if not passed
                    else None,
                )
            )
        return results


class UnrealisticRate(ValidationRule):
    rule_id = "boq_quality.unrealistic_rate"
    name = "Unrealistic Rate Detection"
    standard = "boq_quality"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "Flags positions with unit rate > 100,000 or total > 10,000,000"

    RATE_THRESHOLD = 100_000
    TOTAL_THRESHOLD = 10_000_000

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            rate = float(pos.get("unit_rate", 0)) if pos.get("unit_rate") is not None else 0
            total = float(pos.get("total", 0)) if pos.get("total") is not None else 0
            rate_ok = rate <= self.RATE_THRESHOLD
            total_ok = total <= self.TOTAL_THRESHOLD
            passed = rate_ok and total_ok
            if not passed:
                parts: list[str] = []
                if not rate_ok:
                    parts.append(f"unit_rate {rate:,.2f} > {self.RATE_THRESHOLD:,}")
                if not total_ok:
                    parts.append(f"total {total:,.2f} > {self.TOTAL_THRESHOLD:,}")
                msg = (
                    f"Position {pos.get('ordinal', '?')}: "
                    f"{'; '.join(parts)}"
                )
            else:
                msg = "OK"
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=msg,
                    element_ref=pos.get("id"),
                    details={"unit_rate": rate, "total": total},
                    suggestion="Verify this value — it seems unrealistically high"
                    if not passed
                    else None,
                )
            )
        return results


class TotalMismatch(ValidationRule):
    rule_id = "boq_quality.total_mismatch"
    name = "Total Matches Quantity × Rate"
    standard = "boq_quality"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Computed total (quantity × unit_rate) must match stored total within tolerance"

    TOLERANCE = 0.01

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            qty = pos.get("quantity")
            rate = pos.get("unit_rate")
            stored_total = pos.get("total")
            # Skip positions where any of the three values is missing
            if qty is None or rate is None or stored_total is None:
                continue
            qty_val = float(qty)
            rate_val = float(rate)
            stored_val = float(stored_total)
            computed = qty_val * rate_val
            diff = abs(computed - stored_val)
            passed = diff <= self.TOLERANCE
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
                        f"Position {pos.get('ordinal', '?')}: "
                        f"computed {computed:.2f} != stored {stored_val:.2f} "
                        f"(diff={diff:.2f})"
                    ),
                    element_ref=pos.get("id"),
                    details={
                        "quantity": qty_val,
                        "unit_rate": rate_val,
                        "computed_total": computed,
                        "stored_total": stored_val,
                        "difference": diff,
                    },
                    suggestion="Recalculate total = quantity × unit_rate"
                    if not passed
                    else None,
                )
            )
        return results


class EmptyUnit(ValidationRule):
    rule_id = "boq_quality.empty_unit"
    name = "Position Has Unit"
    standard = "boq_quality"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Every BOQ position must have a unit field (e.g., m, m2, m3, kg, pcs)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            unit = (pos.get("unit") or "").strip()
            passed = len(unit) > 0
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Position {pos.get('ordinal', '?')} has empty or missing unit",
                    element_ref=pos.get("id"),
                    suggestion="Assign a measurement unit (m, m2, m3, kg, pcs, lsum, etc.)"
                    if not passed
                    else None,
                )
            )
        return results


class SectionWithoutItems(ValidationRule):
    rule_id = "boq_quality.section_without_items"
    name = "Section Has Child Items"
    standard = "boq_quality"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Section-type positions should contain at least one child position"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        positions = _get_positions(context)
        # Build a set of all parent IDs
        parent_ids: set[str] = set()
        for pos in positions:
            pid = pos.get("parent_id")
            if pid:
                parent_ids.add(pid)

        results: list[RuleResult] = []
        for pos in positions:
            pos_type = (pos.get("type") or "").lower()
            if pos_type != "section":
                continue
            pos_id = pos.get("id", "")
            has_children = pos_id in parent_ids
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=has_children,
                    message="OK"
                    if has_children
                    else (
                        f"Section {pos.get('ordinal', '?')} "
                        f"({pos.get('description', 'untitled')}) has no child items"
                    ),
                    element_ref=pos_id,
                    suggestion="Add positions under this section or remove the empty section"
                    if not has_children
                    else None,
                )
            )
        return results


# ── Benchmark & Coverage Rules ────────────────────────────────────────────


class RateVsBenchmark(ValidationRule):
    rule_id = "boq_quality.rate_vs_benchmark"
    name = "Rate vs Benchmark"
    standard = "boq_quality"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = (
        "Compares unit rates against typical benchmark thresholds per unit type. "
        "Flags rates that are potentially unrealistic compared to industry medians."
    )

    # Simple heuristic thresholds per unit (upper bound for typical rates)
    UNIT_THRESHOLDS: dict[str, float] = {
        "m2": 10_000,   # > 10,000 per m2 is suspicious
        "m3": 50_000,   # > 50,000 per m3 is suspicious
    }

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            rate = pos.get("unit_rate")
            if rate is None:
                continue
            rate_val = float(rate)
            if rate_val <= 0:
                continue
            unit = (pos.get("unit") or "").strip().lower()
            threshold = self.UNIT_THRESHOLDS.get(unit)
            if threshold is None:
                continue
            passed = rate_val <= threshold
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
                        f"Position {pos.get('ordinal', '?')}: unit rate "
                        f"{rate_val:,.2f}/{unit} exceeds benchmark threshold "
                        f"{threshold:,.2f}/{unit} — potentially unrealistic"
                    ),
                    element_ref=pos.get("id"),
                    details={
                        "unit_rate": rate_val,
                        "unit": unit,
                        "benchmark_threshold": threshold,
                    },
                    suggestion=(
                        f"Verify this rate — typical rates for {unit} should be "
                        f"below {threshold:,.2f}. Check for unit or decimal errors."
                    )
                    if not passed
                    else None,
                )
            )
        return results


class LumpSumRatio(ValidationRule):
    rule_id = "boq_quality.lump_sum_ratio"
    name = "Lump Sum Ratio"
    standard = "boq_quality"
    severity = Severity.INFO
    category = RuleCategory.QUALITY
    description = (
        "Flags BOQs where more than 30% of positions use lump sum (lsum) unit — "
        "indicates poor estimation granularity"
    )

    THRESHOLD = 0.30  # 30%

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        positions = _get_positions(context)
        if not positions:
            return []

        total_count = len(positions)
        lsum_count = sum(
            1
            for pos in positions
            if (pos.get("unit") or "").strip().lower() == "lsum"
        )
        ratio = lsum_count / total_count
        passed = ratio <= self.THRESHOLD

        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message="OK"
                if passed
                else (
                    f"{lsum_count} of {total_count} positions "
                    f"({ratio:.0%}) use lump sum — exceeds {self.THRESHOLD:.0%} threshold"
                ),
                details={
                    "lsum_count": lsum_count,
                    "total_count": total_count,
                    "ratio": round(ratio, 3),
                    "threshold": self.THRESHOLD,
                },
                suggestion=(
                    "Break down lump sum positions into measured quantities "
                    "(m, m2, m3, kg, pcs) for better estimation accuracy"
                )
                if not passed
                else None,
            )
        ]


class CostConcentration(ValidationRule):
    rule_id = "boq_quality.cost_concentration"
    name = "Cost Concentration"
    standard = "boq_quality"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "Flags positions that account for more than 40% of total BOQ cost — "
        "indicates potential scope error or missing breakdown"
    )

    THRESHOLD = 0.40  # 40%

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        positions = _get_positions(context)
        if not positions:
            return []

        # Compute total from each position
        totals: list[tuple[dict[str, Any], float]] = []
        grand_total = 0.0
        for pos in positions:
            pos_total = pos.get("total")
            if pos_total is None:
                # Fallback: compute from quantity × unit_rate
                qty = pos.get("quantity")
                rate = pos.get("unit_rate")
                if qty is not None and rate is not None:
                    val = float(qty) * float(rate)
                else:
                    val = 0.0
            else:
                val = float(pos_total)
            totals.append((pos, val))
            grand_total += val

        if grand_total <= 0:
            return []

        results: list[RuleResult] = []
        for pos, val in totals:
            if val <= 0:
                continue
            share = val / grand_total
            if share > self.THRESHOLD:
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=self.severity,
                        category=self.category,
                        passed=False,
                        message=(
                            f"Position {pos.get('ordinal', '?')} accounts for "
                            f"{share:.0%} of total BOQ cost ({val:,.2f} of "
                            f"{grand_total:,.2f}) — exceeds {self.THRESHOLD:.0%} threshold"
                        ),
                        element_ref=pos.get("id"),
                        details={
                            "position_total": val,
                            "grand_total": grand_total,
                            "share": round(share, 3),
                            "threshold": self.THRESHOLD,
                        },
                        suggestion=(
                            "Break this position into smaller items or verify "
                            "the cost — a single position should not dominate "
                            "the estimate"
                        ),
                    )
                )

        # If no positions exceeded the threshold, emit a single passing result
        if not results:
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message="OK",
                    details={"grand_total": grand_total, "threshold": self.THRESHOLD},
                )
            )

        return results


# ── Additional DIN 276 Rules ─────────────────────────────────────────────


class DIN276Hierarchy(ValidationRule):
    rule_id = "din276.hierarchy"
    name = "DIN 276 Cost Group Hierarchy"
    standard = "din276"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = (
        "Child KG code should be nested under the correct parent "
        "(e.g., 331 under 330 under 300)"
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        positions = _get_positions(context)
        # Build a map from position id to its DIN 276 KG code
        id_to_kg: dict[str, str] = {}
        id_to_pos: dict[str, dict[str, Any]] = {}
        for pos in positions:
            pos_id = pos.get("id", "")
            kg = str((pos.get("classification") or {}).get("din276", ""))
            if pos_id and kg:
                id_to_kg[pos_id] = kg
                id_to_pos[pos_id] = pos

        results: list[RuleResult] = []
        for pos in positions:
            kg = str((pos.get("classification") or {}).get("din276", ""))
            parent_id = pos.get("parent_id")
            if not kg or not parent_id or parent_id not in id_to_kg:
                continue
            parent_kg = id_to_kg[parent_id]
            # A valid hierarchy means the child KG starts with the parent KG prefix.
            # e.g., child "331" should start with parent "330" is wrong;
            # but child "331" should start with parent "33" or "3" level.
            # DIN 276 hierarchy: 3xx (top) → 3x0 (mid) → 3xx (detail)
            # The parent KG prefix (ignoring trailing zeros) should match.
            # Simpler check: the child code must start with the same leading digit(s)
            # as the parent code at a higher level.
            # parent=300 (3 chars) → child should start with "3"
            # parent=330 (3 chars) → child should start with "33"
            # Determine the significant prefix of the parent
            parent_prefix = parent_kg.rstrip("0") or parent_kg[0]
            passed = kg.startswith(parent_prefix)
            if not passed:
                msg = (
                    f"Position {pos.get('ordinal', '?')}: KG {kg} is not "
                    f"under parent KG {parent_kg} (expected prefix '{parent_prefix}')"
                )
            else:
                msg = "OK"
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=msg,
                    element_ref=pos.get("id"),
                    details={"child_kg": kg, "parent_kg": parent_kg},
                    suggestion=(
                        f"Move position to correct parent or update KG code to "
                        f"match parent hierarchy ({parent_prefix}xx)"
                    )
                    if not passed
                    else None,
                )
            )
        return results


class DIN276Completeness(ValidationRule):
    rule_id = "din276.completeness"
    name = "DIN 276 Major Groups Present"
    standard = "din276"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Major KG groups 300 (Building Construction) and 400 (Technical Systems) should be present"

    REQUIRED_GROUPS = {"300", "400"}

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        positions = _get_positions(context)
        # Collect all top-level KG groups (first digit × 100) present in the BOQ
        present_groups: set[str] = set()
        for pos in positions:
            kg = str((pos.get("classification") or {}).get("din276", ""))
            if kg and len(kg) >= 3 and kg.isdigit():
                # Normalize to top-level group: e.g., 331 → 300, 421 → 400
                top_group = kg[0] + "00"
                present_groups.add(top_group)

        results: list[RuleResult] = []
        for group in sorted(self.REQUIRED_GROUPS):
            passed = group in present_groups
            group_names = {
                "300": "Building Construction (Baukonstruktionen)",
                "400": "Technical Systems (Technische Anlagen)",
            }
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
                        f"KG group {group} — {group_names.get(group, '')} "
                        f"is missing from BOQ"
                    ),
                    details={
                        "required_group": group,
                        "present_groups": sorted(present_groups),
                    },
                    suggestion=(
                        f"Add positions for KG {group} "
                        f"({group_names.get(group, '')}) to ensure complete coverage"
                    )
                    if not passed
                    else None,
                )
            )
        return results


# ── NRM Rules (UK) ───────────────────────────────────────────────────────


class NRMClassificationRequired(ValidationRule):
    rule_id = "nrm.classification_required"
    name = "NRM Classification Required"
    standard = "nrm"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Every BOQ position must have an NRM element code"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            nrm = (pos.get("classification") or {}).get("nrm", "")
            passed = bool(nrm) and len(str(nrm)) >= 3
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Position {pos.get('ordinal', '?')} missing NRM element code",
                    element_ref=pos.get("id"),
                    suggestion="Assign an NRM 1/2 element code (e.g., 2.6.1 for external walls)"
                    if not passed
                    else None,
                )
            )
        return results


class NRMValidElement(ValidationRule):
    rule_id = "nrm.valid_element"
    name = "Valid NRM Element Code"
    standard = "nrm"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "NRM element code must match NRM 1/2 structure (e.g., 1.1, 2.6.1)"

    VALID_GROUPS = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13"}

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        import re

        pattern = re.compile(r"^\d{1,2}(\.\d{1,2}){0,3}$")
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            nrm = str((pos.get("classification") or {}).get("nrm", ""))
            if not nrm:
                continue
            top = nrm.split(".")[0]
            passed = bool(pattern.match(nrm)) and top in self.VALID_GROUPS
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Invalid NRM code '{nrm}' in position {pos.get('ordinal', '?')}",
                    element_ref=pos.get("id"),
                    details={"given_code": nrm},
                )
            )
        return results


class NRMCompleteness(ValidationRule):
    rule_id = "nrm.completeness"
    name = "NRM Major Groups Present"
    standard = "nrm"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Major NRM groups (Substructure, Superstructure, Services) should be present"

    REQUIRED_GROUPS = {"1", "2", "5"}  # 1=Substructure, 2=Superstructure, 5=Services

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        positions = _get_positions(context)
        present_groups: set[str] = set()
        for pos in positions:
            nrm = str((pos.get("classification") or {}).get("nrm", ""))
            if nrm:
                present_groups.add(nrm.split(".")[0])

        group_names = {
            "1": "Substructure",
            "2": "Superstructure",
            "5": "Services",
        }
        results: list[RuleResult] = []
        for group in sorted(self.REQUIRED_GROUPS):
            passed = group in present_groups
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"NRM group {group} — {group_names.get(group, '')} missing from BOQ",
                    details={"required_group": group, "present_groups": sorted(present_groups)},
                    suggestion=f"Add positions for NRM group {group} ({group_names.get(group, '')})"
                    if not passed
                    else None,
                )
            )
        return results


# ── MasterFormat Rules (US) ──────────────────────────────────────────────


class MasterFormatClassificationRequired(ValidationRule):
    rule_id = "masterformat.classification_required"
    name = "MasterFormat Classification Required"
    standard = "masterformat"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Every BOQ position must have a CSI MasterFormat division code"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            mf = (pos.get("classification") or {}).get("masterformat", "")
            passed = bool(mf) and len(str(mf).replace(" ", "")) >= 4
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Position {pos.get('ordinal', '?')} missing MasterFormat code",
                    element_ref=pos.get("id"),
                    suggestion="Assign a MasterFormat code (e.g., 03 30 00 for Cast-in-Place Concrete)"
                    if not passed
                    else None,
                )
            )
        return results


class MasterFormatValidDivision(ValidationRule):
    rule_id = "masterformat.valid_division"
    name = "Valid MasterFormat Division"
    standard = "masterformat"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "MasterFormat code must be a valid division (00-49)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        import re

        pattern = re.compile(r"^\d{2}(\s?\d{2}){0,2}(\.\d{2})?$")
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            mf = str((pos.get("classification") or {}).get("masterformat", ""))
            if not mf:
                continue
            div = mf[:2]
            valid_div = div.isdigit() and 0 <= int(div) <= 49
            passed = bool(pattern.match(mf)) and valid_div
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Invalid MasterFormat code '{mf}' in position {pos.get('ordinal', '?')}",
                    element_ref=pos.get("id"),
                    details={"given_code": mf},
                    suggestion="Use 6-digit MasterFormat format: XX XX XX (e.g., 03 30 00)"
                    if not passed
                    else None,
                )
            )
        return results


class MasterFormatCompleteness(ValidationRule):
    rule_id = "masterformat.completeness"
    name = "MasterFormat Core Divisions Present"
    standard = "masterformat"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Core divisions (03 Concrete, 05 Metals, 26 Electrical) should be present"

    REQUIRED_DIVISIONS = {"03", "05", "26"}

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        positions = _get_positions(context)
        present_divs: set[str] = set()
        for pos in positions:
            mf = str((pos.get("classification") or {}).get("masterformat", ""))
            if mf and len(mf) >= 2:
                present_divs.add(mf[:2])

        div_names = {
            "03": "Concrete",
            "05": "Metals",
            "26": "Electrical",
        }
        results: list[RuleResult] = []
        for div in sorted(self.REQUIRED_DIVISIONS):
            passed = div in present_divs
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Division {div} — {div_names.get(div, '')} missing from BOQ",
                    details={"required_div": div, "present_divs": sorted(present_divs)},
                    suggestion=f"Add positions for Division {div} ({div_names.get(div, '')})"
                    if not passed
                    else None,
                )
            )
        return results


# ── SINAPI Rules (Brazil) ───────────────────────────────────────────────


class SINAPICodeRequired(ValidationRule):
    rule_id = "sinapi.code_required"
    name = "SINAPI Code Required"
    standard = "sinapi"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "BOQ positions should have a SINAPI composition code"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = (pos.get("classification") or {}).get("sinapi", "")
            passed = bool(code) and len(str(code)) >= 4
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Position {pos.get('ordinal', '?')} missing SINAPI code",
                    element_ref=pos.get("id"),
                    suggestion="Assign a SINAPI composition code (e.g., 87878 for concrete C30)"
                    if not passed
                    else None,
                )
            )
        return results


class SINAPIValidCode(ValidationRule):
    rule_id = "sinapi.valid_code"
    name = "Valid SINAPI Code Format"
    standard = "sinapi"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "SINAPI codes should be 5-digit numeric codes"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = str((pos.get("classification") or {}).get("sinapi", ""))
            if not code:
                continue
            passed = code.isdigit() and 4 <= len(code) <= 6
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Invalid SINAPI code '{code}' in position {pos.get('ordinal', '?')}",
                    element_ref=pos.get("id"),
                    details={"given_code": code},
                )
            )
        return results


# ── GESN Rules (Russia/CIS) ─────────────────────────────────────────────


class GESNCodeRequired(ValidationRule):
    rule_id = "gesn.code_required"
    name = "GESN/FER Code Required"
    standard = "gesn"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "BOQ positions should have a ГЭСН/ФЕР code"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = (pos.get("classification") or {}).get("gesn", "")
            passed = bool(code) and len(str(code)) >= 5
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Position {pos.get('ordinal', '?')} missing ГЭСН/ФЕР code",
                    element_ref=pos.get("id"),
                    suggestion="Assign a ГЭСН code (e.g., 06-01-001-01 for concrete)"
                    if not passed
                    else None,
                )
            )
        return results


class GESNValidCode(ValidationRule):
    rule_id = "gesn.valid_code"
    name = "Valid GESN Code Format"
    standard = "gesn"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "ГЭСН codes should follow XX-XX-XXX-XX format"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        import re

        pattern = re.compile(r"^\d{2}-\d{2}-\d{3}-\d{2}$")
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = str((pos.get("classification") or {}).get("gesn", ""))
            if not code:
                continue
            passed = bool(pattern.match(code))
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"ГЭСН code '{code}' doesn't match format XX-XX-XXX-XX",
                    element_ref=pos.get("id"),
                    details={"given_code": code},
                    suggestion="Use format: NN-NN-NNN-NN (e.g., 06-01-001-01)"
                    if not passed
                    else None,
                )
            )
        return results


# ── DPGF Rules (France) ─────────────────────────────────────────────────


class DPGFLotRequired(ValidationRule):
    rule_id = "dpgf.lot_required"
    name = "DPGF Lot Technique Required"
    standard = "dpgf"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "BOQ positions must be assigned to a Lot technique (trade package)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            lot = (pos.get("classification") or {}).get("dpgf", "") or pos.get("section", "")
            passed = bool(lot)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Position {pos.get('ordinal', '?')} not assigned to any Lot technique",
                    element_ref=pos.get("id"),
                    suggestion="Assign a Lot technique (e.g., Lot 01 Gros Œuvre)"
                    if not passed
                    else None,
                )
            )
        return results


class DPGFPricingComplete(ValidationRule):
    rule_id = "dpgf.pricing_complete"
    name = "DPGF Pricing Complete"
    standard = "dpgf"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "All DPGF positions should have complete pricing (unit rate or lump sum)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        positions = _get_positions(context)
        if not positions:
            return []
        priced = sum(1 for p in positions if p.get("unit_rate") and float(p["unit_rate"]) > 0)
        total = len(positions)
        ratio = priced / total if total > 0 else 0
        passed = ratio >= 0.80
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message="OK"
                if passed
                else f"Only {priced}/{total} positions ({ratio:.0%}) have pricing — below 80% threshold",
                details={"priced": priced, "total": total, "ratio": round(ratio, 3)},
                suggestion="Complete pricing for all positions before DPGF submission"
                if not passed
                else None,
            )
        ]


# ── ÖNORM Rules (Austria) ───────────────────────────────────────────────


class ONORMPositionFormat(ValidationRule):
    rule_id = "onorm.position_format"
    name = "ÖNORM B 2063 Position Format"
    standard = "onorm"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Position ordinals should follow ÖNORM B 2063 LV structure"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        import re

        pattern = re.compile(r"^\d{2}\.\d{2}\.\d{2,4}[A-Z]?$")
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
                    else f"Ordinal '{ordinal}' doesn't match ÖNORM format XX.XX.XXXXA",
                    element_ref=pos.get("id"),
                    suggestion="Use ÖNORM B 2063 format (e.g., 01.02.01A)"
                    if not passed
                    else None,
                )
            )
        return results


class ONORMDescriptionLength(ValidationRule):
    rule_id = "onorm.description_length"
    name = "ÖNORM Description Length"
    standard = "onorm"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "ÖNORM positions should have descriptions with sufficient detail (min 20 chars)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            desc = (pos.get("description") or "").strip()
            passed = len(desc) >= 20
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
                        f"Position {pos.get('ordinal', '?')}: description too short "
                        f"({len(desc)} chars, min 20)"
                    ),
                    element_ref=pos.get("id"),
                    suggestion="Add more detail to the position description per ÖNORM B 2063"
                    if not passed
                    else None,
                )
            )
        return results


# ── GB/T 50500 Rules (China) ────────────────────────────────────────────


class GBT50500CodeRequired(ValidationRule):
    rule_id = "gbt50500.code_required"
    name = "GB/T 50500 Code Required"
    standard = "gbt50500"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "BOQ positions must have a GB/T 50500 item code (工程量清单编码)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = (pos.get("classification") or {}).get("gbt50500", "")
            passed = bool(code) and len(str(code)) >= 6
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Position {pos.get('ordinal', '?')} missing GB/T 50500 code",
                    element_ref=pos.get("id"),
                    suggestion="Assign a 9-digit GB/T 50500 code (e.g., 010101001)"
                    if not passed
                    else None,
                )
            )
        return results


class GBT50500ValidCode(ValidationRule):
    rule_id = "gbt50500.valid_code"
    name = "Valid GB/T 50500 Code"
    standard = "gbt50500"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "GB/T 50500 codes should be 9-digit or 12-digit numeric codes"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = str((pos.get("classification") or {}).get("gbt50500", ""))
            if not code:
                continue
            passed = code.isdigit() and len(code) in (9, 12)
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Invalid GB/T 50500 code '{code}' — expected 9 or 12 digits",
                    element_ref=pos.get("id"),
                    details={"given_code": code},
                )
            )
        return results


# ── CPWD Rules (India) ──────────────────────────────────────────────────


class CPWDCodeRequired(ValidationRule):
    rule_id = "cpwd.code_required"
    name = "CPWD/DSR Code Required"
    standard = "cpwd"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "BOQ positions should have a CPWD/DSR item reference"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = (pos.get("classification") or {}).get("cpwd", "")
            passed = bool(code) and len(str(code)) >= 3
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Position {pos.get('ordinal', '?')} missing CPWD/DSR code",
                    element_ref=pos.get("id"),
                    suggestion="Assign a CPWD DSR item reference (e.g., 4.1.1)"
                    if not passed
                    else None,
                )
            )
        return results


class CPWDMeasurementUnits(ValidationRule):
    rule_id = "cpwd.measurement_units"
    name = "CPWD IS 1200 Measurement Units"
    standard = "cpwd"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Units must follow IS 1200 measurement standards (metric only)"

    VALID_UNITS = {
        "m", "m2", "m3", "kg", "t", "nos", "pcs", "rm", "rmt",
        "sqm", "cum", "each", "lsum", "ls", "set", "pair", "litre", "kl",
    }

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            unit = (pos.get("unit") or "").strip().lower()
            if not unit:
                continue
            passed = unit in self.VALID_UNITS
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Unit '{unit}' in position {pos.get('ordinal', '?')} not standard IS 1200",
                    element_ref=pos.get("id"),
                    suggestion="Use standard IS 1200 units: m, m2, m3, kg, nos, rm, etc."
                    if not passed
                    else None,
                )
            )
        return results


# ── Birim Fiyat Rules (Turkey) ──────────────────────────────────────────


class BirimFiyatCodeRequired(ValidationRule):
    rule_id = "birimfiyat.code_required"
    name = "Birim Fiyat Poz Required"
    standard = "birimfiyat"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "BOQ positions must have a Bayındırlık birim fiyat poz number"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = (pos.get("classification") or {}).get("birimfiyat", "")
            passed = bool(code) and len(str(code)) >= 4
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Position {pos.get('ordinal', '?')} missing birim fiyat poz number",
                    element_ref=pos.get("id"),
                    suggestion="Assign a Bayındırlık poz number (e.g., 04.013/1)"
                    if not passed
                    else None,
                )
            )
        return results


class BirimFiyatValidPoz(ValidationRule):
    rule_id = "birimfiyat.valid_poz"
    name = "Valid Birim Fiyat Poz Format"
    standard = "birimfiyat"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Poz numbers should follow Bayındırlık format (XX.XXX/X)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        import re

        pattern = re.compile(r"^\d{2}\.\d{3}(/\d{1,2})?$")
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = str((pos.get("classification") or {}).get("birimfiyat", ""))
            if not code:
                continue
            passed = bool(pattern.match(code))
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Poz '{code}' doesn't match format XX.XXX/X",
                    element_ref=pos.get("id"),
                    details={"given_code": code},
                    suggestion="Use format: NN.NNN or NN.NNN/N (e.g., 04.013/1)"
                    if not passed
                    else None,
                )
            )
        return results


# ── Sekisan Rules (Japan) ───────────────────────────────────────────────


class SekisanCodeRequired(ValidationRule):
    rule_id = "sekisan.code_required"
    name = "Sekisan Code Required"
    standard = "sekisan"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "BOQ positions should have a 積算基準 item code"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            code = (pos.get("classification") or {}).get("sekisan", "")
            passed = bool(code) and len(str(code)) >= 3
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Position {pos.get('ordinal', '?')} missing 積算 code",
                    element_ref=pos.get("id"),
                    suggestion="Assign a 積算基準 item code" if not passed else None,
                )
            )
        return results


class SekisanMetricUnits(ValidationRule):
    rule_id = "sekisan.metric_units"
    name = "Sekisan Metric Units"
    standard = "sekisan"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Units must be metric per Japanese construction standards"

    VALID_UNITS = {
        "m", "m2", "m3", "kg", "t", "本", "枚", "箇所", "式",
        "台", "セット", "個", "組", "m2/回", "pcs", "set", "lsum",
    }

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for pos in _get_positions(context):
            unit = (pos.get("unit") or "").strip().lower()
            if not unit:
                continue
            passed = unit in self.VALID_UNITS or unit in {u.lower() for u in self.VALID_UNITS}
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK"
                    if passed
                    else f"Unit '{unit}' in position {pos.get('ordinal', '?')} not standard",
                    element_ref=pos.get("id"),
                    suggestion="Use standard metric units: m, m2, m3, kg, t, 式, etc."
                    if not passed
                    else None,
                )
            )
        return results


# ── Universal Additional Rules ──────────────────────────────────────────


class CurrencyConsistency(ValidationRule):
    rule_id = "boq_quality.currency_consistency"
    name = "Currency Consistency"
    standard = "boq_quality"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "All positions in a BOQ should use the same currency"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        positions = _get_positions(context)
        currencies: set[str] = set()
        for pos in positions:
            ccy = (pos.get("currency") or "").strip().upper()
            if ccy:
                currencies.add(ccy)
        if len(currencies) <= 1:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message="OK",
                )
            ]
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=f"Mixed currencies found: {', '.join(sorted(currencies))}",
                details={"currencies": sorted(currencies)},
                suggestion="Use a single currency throughout the BOQ",
            )
        ]


class MeasurementConsistency(ValidationRule):
    rule_id = "boq_quality.measurement_consistency"
    name = "Measurement Unit Consistency"
    standard = "boq_quality"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags mixing of metric and imperial units in the same BOQ"

    IMPERIAL_UNITS = {"ft", "ft2", "ft3", "yd", "yd2", "yd3", "in", "lb", "ton", "gal", "sf", "sy", "cy", "lf"}
    METRIC_UNITS = {"m", "m2", "m3", "mm", "cm", "km", "kg", "t", "l", "kl", "ml"}

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        positions = _get_positions(context)
        has_metric = False
        has_imperial = False
        for pos in positions:
            unit = (pos.get("unit") or "").strip().lower()
            if unit in self.IMPERIAL_UNITS:
                has_imperial = True
            if unit in self.METRIC_UNITS:
                has_metric = True
        if has_metric and has_imperial:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message="BOQ mixes metric and imperial units — use one system consistently",
                    suggestion="Convert all quantities to either metric or imperial units",
                )
            ]
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=True,
                message="OK",
            )
        ]


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
        (NegativeValues(), None),
        (UnrealisticRate(), None),
        (TotalMismatch(), None),
        (EmptyUnit(), None),
        (SectionWithoutItems(), None),
        (RateVsBenchmark(), None),
        (LumpSumRatio(), None),
        (CostConcentration(), None),
        (CurrencyConsistency(), None),
        (MeasurementConsistency(), None),
        # DIN 276 (DACH)
        (DIN276CostGroupRequired(), None),
        (DIN276ValidCostGroup(), None),
        (DIN276Hierarchy(), None),
        (DIN276Completeness(), None),
        # GAEB (DACH)
        (GAEBOrdinalFormat(), None),
        # NRM (UK)
        (NRMClassificationRequired(), None),
        (NRMValidElement(), None),
        (NRMCompleteness(), None),
        # MasterFormat (US)
        (MasterFormatClassificationRequired(), None),
        (MasterFormatValidDivision(), None),
        (MasterFormatCompleteness(), None),
        # SINAPI (Brazil)
        (SINAPICodeRequired(), None),
        (SINAPIValidCode(), None),
        # GESN (Russia/CIS)
        (GESNCodeRequired(), None),
        (GESNValidCode(), None),
        # DPGF (France)
        (DPGFLotRequired(), None),
        (DPGFPricingComplete(), None),
        # ÖNORM (Austria)
        (ONORMPositionFormat(), None),
        (ONORMDescriptionLength(), None),
        # GB/T 50500 (China)
        (GBT50500CodeRequired(), None),
        (GBT50500ValidCode(), None),
        # CPWD (India)
        (CPWDCodeRequired(), None),
        (CPWDMeasurementUnits(), None),
        # Birim Fiyat (Turkey)
        (BirimFiyatCodeRequired(), None),
        (BirimFiyatValidPoz(), None),
        # Sekisan (Japan)
        (SekisanCodeRequired(), None),
        (SekisanMetricUnits(), None),
    ]

    for rule, sets in rules:
        rule_registry.register(rule, sets)

    logger.info(
        "Registered %d built-in validation rules across %d rule sets",
        len(rules),
        len(rule_registry.list_rule_sets()),
    )
