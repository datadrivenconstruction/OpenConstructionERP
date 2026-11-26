# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Commercial control validation rules (rule set ``commercial_control``).

Thin wrappers: each rule runs one pure check from :mod:`app.core.commercial_checks`
on its payload block and translates the findings. A payload without the block a
rule reads makes that rule return nothing, so one rule set serves the commitment
grid, the CVR rollup, the approval route editor and both valuation screens.

:func:`evaluate` is what those services call; it returns the failed findings as
plain dicts ready for a response body.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.commercial_checks import CHECKS, Finding
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    validation_engine,
)
from app.core.validation.messages import translate

logger = logging.getLogger(__name__)

RULE_SET = "commercial_control"

#: The payload block each rule reads; a payload without it is not this rule's business.
_BLOCKS: dict[str, str] = {
    "cvr.target_rate_basis": "budget_positions",
    "cvr.unmapped_cost": "unmapped_sources",
    "cvr.wbs_rollup_reconciles": "wbs_rollup_nodes",
    "procurement.line_over_committed": "grid_rows",
    "approval_routes.bands_contiguous": "route_steps",
    "valuation.assessed_within_submitted": "valuation_lines",
    "valuation.certified_within_assessed": "valuation_lines",
    "valuation.cumulative_not_decreasing": "valuation_lines",
}


def _locale(context: ValidationContext) -> str:
    meta = getattr(context, "metadata", None) or {}
    locale = meta.get("locale") if isinstance(meta, dict) else None
    return locale if isinstance(locale, str) and locale else "en"


class _CommercialRule(ValidationRule):
    standard = "custom"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        if _BLOCKS[self.rule_id] not in data:
            return []
        locale = _locale(context)
        findings: list[Finding] = CHECKS[self.rule_id](data)
        if not findings:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message=translate("commercial_control.ok", locale=locale),
                )
            ]
        results: list[RuleResult] = []
        for finding in findings:
            kind = finding.params.get("kind")
            key = (
                f"{self.rule_id}.{kind}"
                if self.rule_id == "approval_routes.bands_contiguous" and kind
                else self.rule_id
            )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=Severity(finding.severity) if finding.severity else self.severity,
                    category=self.category,
                    passed=False,
                    message=translate(f"commercial_control.{key}.fail", locale=locale, **finding.params),
                    element_ref=finding.element_ref,
                    details={**finding.details, "params": dict(finding.params)},
                    suggestion=translate(f"commercial_control.{key}.suggestion", locale=locale),
                )
            )
        return results


class TargetRateBasisRule(_CommercialRule):
    rule_id = "cvr.target_rate_basis"
    name = "Budget At Target Cost"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags priced bill positions without a target rate, which are budgeted at their sale rate instead."


class UnmappedCostRule(_CommercialRule):
    rule_id = "cvr.unmapped_cost"
    name = "Cost Without WBS"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags a commitment or actual cost that carries no WBS or cost code, so the CVR cannot place it."


class WbsRollupReconcilesRule(_CommercialRule):
    rule_id = "cvr.wbs_rollup_reconciles"
    name = "WBS Rollup Reconciles"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "A WBS parent equals its own lines plus its children; the report equals its roots plus unallocated."


class LineOverCommittedRule(_CommercialRule):
    rule_id = "procurement.line_over_committed"
    name = "Bill Line Over-Committed"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags a bill line whose orders and subcontracts exceed its budget quantity or value."


class BandsContiguousRule(_CommercialRule):
    rule_id = "approval_routes.bands_contiguous"
    name = "Approval Bands Contiguous"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Approval amount bands leave no amount without an approver (error) and do not overlap (warning)."


class AssessedWithinSubmittedRule(_CommercialRule):
    rule_id = "valuation.assessed_within_submitted"
    name = "Assessed Within Submitted"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags a valuation line whose assessed quantity is above the quantity submitted."


class CertifiedWithinAssessedRule(_CommercialRule):
    rule_id = "valuation.certified_within_assessed"
    name = "Certified Within Assessed"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags a valuation line whose certified quantity is above the quantity assessed."


class CumulativeNotDecreasingRule(_CommercialRule):
    rule_id = "valuation.cumulative_not_decreasing"
    name = "Cumulative Not Decreasing"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags a valuation line whose running total falls below the previous document's with no note."


COMMERCIAL_CONTROL_RULES: tuple[ValidationRule, ...] = (
    TargetRateBasisRule(),
    UnmappedCostRule(),
    WbsRollupReconcilesRule(),
    LineOverCommittedRule(),
    BandsContiguousRule(),
    AssessedWithinSubmittedRule(),
    CertifiedWithinAssessedRule(),
    CumulativeNotDecreasingRule(),
)


async def evaluate(data: dict[str, Any], *, target_type: str, target_id: str = "") -> list[dict[str, Any]]:
    """Run the rule set and return the failed findings as response-ready dicts.

    A failure of the engine itself logs and returns nothing: findings add to a
    read, they never break it.
    """
    from app.core.i18n import get_locale

    try:
        report = await validation_engine.validate(
            data=data,
            rule_sets=[RULE_SET],
            target_type=target_type,
            target_id=target_id,
            metadata={"locale": get_locale()},
        )
    except Exception:  # noqa: BLE001 - findings augment a read
        logger.warning("commercial control validation failed for %s %s", target_type, target_id, exc_info=True)
        return []
    return [
        {
            "rule_id": r.rule_id,
            "severity": r.severity.value if hasattr(r.severity, "value") else str(r.severity),
            "element_ref": r.element_ref,
            "message": r.message,
            "suggestion": r.suggestion,
            "details": r.details,
        }
        for r in report.results
        if not r.passed and not r.is_engine_error
    ]
