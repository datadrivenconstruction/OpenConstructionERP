# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Carbon module validation rules.

Module-local rules registered against the global ``rule_registry`` at import
time (the module loader imports ``validators`` for autodiscovery). Keeping the
rule here, rather than in ``core/validation/rules``, keeps the 6D carbon
concern inside the carbon module.

Standard: EN 15978 (embodied carbon life-cycle stages).
"""

from __future__ import annotations

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


def _coverage_counts(data: Any) -> tuple[int, int] | None:
    """Extract ``(bim_element_count, linked_carbon_element_count)`` from data.

    Accepts either explicit counts (``bim_element_count`` /
    ``linked_carbon_element_count``) or the raw lists (``bim_elements`` /
    ``embodied_entries``, the latter counted by distinct ``element_id``).
    Returns ``None`` when the data does not carry enough to judge coverage, so
    the rule simply does not apply.
    """
    if not isinstance(data, dict):
        return None
    bim = data.get("bim_element_count")
    if bim is None and isinstance(data.get("bim_elements"), list):
        bim = len(data["bim_elements"])
    if bim is None:
        return None
    linked = data.get("linked_carbon_element_count")
    if linked is None:
        entries = data.get("embodied_entries")
        if isinstance(entries, list):
            linked = len(
                {str(e.get("element_id")) for e in entries if isinstance(e, dict) and e.get("element_id")},
            )
        else:
            linked = 0
    try:
        return int(bim), int(linked)
    except (TypeError, ValueError):
        return None


class Carbon6DCoverageRule(ValidationRule):
    """6D completeness - how much of the BIM is covered by embodied carbon.

    Flags a project that has BIM elements but few or none carry a linked
    embodied-carbon entry. INFO when partially covered, WARNING when coverage
    is very low or zero. Never an ERROR - 6D enrichment is advisory, and the
    rule is silent (returns nothing) when the data does not describe both BIM
    elements and carbon entries.
    """

    rule_id = "carbon.6d_coverage"
    name = "6D carbon coverage of BIM elements"
    standard = "carbon_6d"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = (
        "Warns when a project has BIM elements but few or none carry a linked embodied-carbon entry (EN 15978 A1-A3)."
    )

    # Coverage at/above which the project reads as adequately enriched.
    _ok_threshold = 0.8
    # Coverage below which low coverage is a WARNING rather than INFO.
    _low_threshold = 0.5

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        counts = _coverage_counts(context.data)
        if counts is None:
            return []
        bim_count, linked = counts

        if bim_count <= 0:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=Severity.INFO,
                    category=self.category,
                    passed=True,
                    message="No BIM elements present; 6D carbon coverage not applicable.",
                    details={"bim_element_count": 0, "linked_carbon_element_count": linked},
                ),
            ]

        coverage = linked / bim_count
        pct = round(coverage * 100, 1)
        details: dict[str, Any] = {
            "bim_element_count": bim_count,
            "linked_carbon_element_count": linked,
            "coverage_pct": pct,
            "ok_threshold_pct": round(self._ok_threshold * 100, 1),
        }
        suggestion = (
            "Run carbon auto-enrichment (POST /carbon/inventories/{id}/auto-enrich-bim) "
            "to link embodied-carbon entries to the remaining BIM elements."
        )

        if linked == 0:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=Severity.WARNING,
                    category=self.category,
                    passed=False,
                    message=(f"None of {bim_count} BIM elements have a linked embodied-carbon entry."),
                    details=details,
                    suggestion=suggestion,
                ),
            ]
        if coverage < self._low_threshold:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=Severity.WARNING,
                    category=self.category,
                    passed=False,
                    message=(
                        f"Only {linked} of {bim_count} BIM elements ({pct}%) have a linked embodied-carbon entry."
                    ),
                    details=details,
                    suggestion=suggestion,
                ),
            ]
        if coverage < self._ok_threshold:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=Severity.INFO,
                    category=self.category,
                    passed=False,
                    message=(
                        f"{linked} of {bim_count} BIM elements ({pct}%) carry embodied carbon; "
                        f"{bim_count - linked} remain unlinked."
                    ),
                    details=details,
                    suggestion=suggestion,
                ),
            ]
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=Severity.INFO,
                category=self.category,
                passed=True,
                message=f"{linked} of {bim_count} BIM elements ({pct}%) carry embodied carbon.",
                details=details,
            ),
        ]


def register_carbon_validation_rules() -> None:
    """Register the carbon module's validation rules with the global registry.

    ``carbon_6d`` and nothing else. This rule used to be registered into
    ``project_completeness`` as well, which is a set no rule implements and
    twenty two demo templates ask for. One rule was enough to make the set
    resolve, so ``resolve_rule_sets`` bucketed it as supported, it left
    ``unsupported_rule_sets``, and the dashboard stopped listing it under "not
    implemented (did not run)". What it showed instead was a completeness check
    that ran and found nothing, because this rule returns no results at all
    unless the data carries BIM element counts and a BOQ demo never does.

    ``RuleRegistry.has_rules`` states the invariant that broke: a set that
    resolves to nothing must never read as "ran and passed", it simply did not
    run. A rule registers into the set it is about, so a set nobody has written
    stays visibly empty instead of being answered by a rule from another
    concern.
    """
    rule_registry.register(Carbon6DCoverageRule(), ["carbon_6d"])
    logger.debug("Registered carbon validation rules")


# Side-effect registration on import (module-loader autodiscovery contract).
register_carbon_validation_rules()
