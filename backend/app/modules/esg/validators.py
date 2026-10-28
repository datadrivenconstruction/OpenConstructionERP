# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ESG module validation rules.

A module-local rule registered against the global ``rule_registry`` at import
time (the module loader imports ``validators`` for autodiscovery). It runs over a
batch of ESG readings - for example an imported period sheet - and flags range
violations and missing targets, so a bulk import gets the same first-class
data-quality check the write path already enforces per entry.

Standard: ESG operational site metrics (this module's catalogue).
"""

from __future__ import annotations

import logging
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
from app.modules.esg.catalogue import PERCENT_UNIT, get_metric, is_percent_metric

logger = logging.getLogger(__name__)


def _readings(data: Any) -> list[dict[str, Any]] | None:
    """Extract a list of reading dicts from ``data``, or ``None`` if absent.

    Accepts a dict carrying ``esg_entries`` (or ``entries``) as a list of
    ``{metric_key, value, target}`` mappings. Returns ``None`` when the data
    does not describe ESG readings, so the rule simply does not apply.
    """
    if not isinstance(data, dict):
        return None
    raw = data.get("esg_entries")
    if raw is None:
        raw = data.get("entries")
    if not isinstance(raw, list):
        return None
    return [row for row in raw if isinstance(row, dict)]


def _to_decimal(value: object) -> Decimal | None:
    """Best-effort parse to a finite Decimal, else ``None``."""
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


class EsgReadingQualityRule(ValidationRule):
    """Batch data-quality check for a set of ESG readings.

    Flags readings whose metric is not in the catalogue, whose value is negative
    or non-numeric, or whose percentage metric falls outside 0..100 (WARNING),
    and notes how many readings carry no target so their KPI cannot be judged
    on-track (INFO). Advisory only - never an ERROR - since the write path
    already blocks bad single entries; this catches problems in bulk data.
    """

    rule_id = "esg.reading_quality"
    name = "ESG reading quality"
    standard = "esg_site"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = (
        "Flags ESG readings with an unknown metric, a negative or non-numeric value, "
        "or a percentage outside 0..100, and notes readings that carry no target."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        readings = _readings(context.data)
        if readings is None or not readings:
            return []

        issues: list[str] = []
        missing_target = 0
        for index, row in enumerate(readings):
            metric_key = str(row.get("metric_key") or "").strip()
            label = f"row {index + 1} ('{metric_key or '?'}')"
            if not metric_key or get_metric(metric_key) is None:
                issues.append(f"{label}: unknown metric")
                continue
            number = _to_decimal(row.get("value"))
            if number is None:
                issues.append(f"{label}: value is not a number")
            elif number < 0:
                issues.append(f"{label}: value {number} is negative")
            elif is_percent_metric(metric_key) and number > Decimal(100):
                issues.append(f"{label}: {number} is above 100 ({PERCENT_UNIT})")
            if row.get("target") in (None, ""):
                missing_target += 1

        results: list[RuleResult] = []
        if issues:
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=Severity.WARNING,
                    category=self.category,
                    passed=False,
                    message=f"{len(issues)} ESG reading(s) failed a range/vocabulary check.",
                    details={"issues": issues[:20], "issue_count": len(issues)},
                    suggestion="Correct the flagged readings; values must be >= 0 and percentages 0..100.",
                ),
            )
        if missing_target:
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=Severity.INFO,
                    category=RuleCategory.COMPLETENESS,
                    passed=False,
                    message=(
                        f"{missing_target} of {len(readings)} readings have no target, so on-track cannot be judged."
                    ),
                    details={"missing_target": missing_target, "total": len(readings)},
                    suggestion="Set a target on each metric to enable direction-aware KPI colouring.",
                ),
            )
        if not results:
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=Severity.INFO,
                    category=self.category,
                    passed=True,
                    message=f"All {len(readings)} ESG readings are in range and carry a target.",
                    details={"total": len(readings)},
                ),
            )
        return results


def register_esg_validation_rules() -> None:
    """Register the ESG module's validation rules with the global registry."""
    rule_registry.register(EsgReadingQualityRule(), ["esg_site", "boq_quality"])
    logger.debug("Registered ESG validation rules")


# Side-effect registration on import (module-loader autodiscovery contract).
register_esg_validation_rules()
