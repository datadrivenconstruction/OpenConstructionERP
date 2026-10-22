# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rule set ``procurement_concept`` (SPEC section 7).

The rules read one payload, ``{"findings": [...]}``, built by
:meth:`ProcurementConceptService.findings` from the pure evaluator. Each rule
owns a set of finding codes: a finding of its codes is a failed result for its
ref; no finding is one passed result. The same findings refuse approval, so
the rule set and the approval gate cannot disagree.
"""

from __future__ import annotations

from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.procurement_concept.messages import translate

PROCUREMENT_RULE_SET = "procurement_concept"


def _locale(context: ValidationContext) -> str:
    meta = getattr(context, "metadata", None) or {}
    return str(meta.get("locale") or "en")


def _findings(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data if isinstance(context.data, dict) else {}
    raw = data.get("findings") or []
    return [f for f in raw if isinstance(f, dict)]


class _ProcurementRule(ValidationRule):
    standard = "procurement"
    category = RuleCategory.COMPLETENESS
    severity = Severity.ERROR
    key = ""
    codes: tuple[str, ...] = ()

    def _result(self, locale: str, passed: bool, ref: str, severity: Severity | None = None) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=severity or self.severity,
            category=self.category,
            passed=passed,
            message=translate(f"procurement_concept.rules.{self.key}", locale=locale, ref=ref),
            element_ref=ref,
            suggestion=None
            if passed
            else translate(f"procurement_concept.rules.{self.key}_fix", locale=locale, ref=ref),
        )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        mine = [f for f in _findings(context) if f.get("code") in self.codes]
        if not mine:
            return [self._result(loc, True, "project")]
        return [
            self._result(
                loc,
                False,
                str(f.get("ref") or ""),
                Severity.WARNING if f.get("severity") == "warning" else Severity.ERROR,
            )
            for f in mine
        ]


def _rule(key: str, name: str, description: str, codes: tuple[str, ...], severity: Severity = Severity.ERROR) -> type:
    return type(
        f"Procurement_{key}",
        (_ProcurementRule,),
        {
            "key": key,
            "rule_id": f"{PROCUREMENT_RULE_SET}.{key}",
            "name": name,
            "description": description,
            "codes": codes,
            "severity": severity,
        },
    )


PROCUREMENT_RULES: tuple[type[ValidationRule], ...] = (
    _rule(
        "package_has_procedure_plan",
        "Package Has Procedure Plan",
        "Every contract package has an award package with a procedure.",
        ("package_without_procedure_plan", "procedure_unknown"),
    ),
    _rule(
        "procedure_allowed_for_value",
        "Procedure Allowed For Value",
        "The procedure is allowed for the jurisdiction, client type, contract kind and value.",
        (
            "procedure_not_allowed_above_threshold",
            "procedure_not_allowed_for_client",
            "tender_basis_not_allowed",
            "threshold_currency_unresolved",
            "threshold_not_available_for_date",
            "vat_rate_missing_for_gross_threshold",
        ),
    ),
    _rule(
        "lots_aggregated_for_threshold",
        "Lots Aggregated For Threshold",
        "The threshold test uses the aggregated value of all lots.",
        ("lot_splitting_avoids_threshold",),
    ),
    _rule(
        "threshold_source_confirmed",
        "Threshold Source Confirmed",
        "The applied threshold is not yet confirmed on its primary source.",
        ("threshold_source_unconfirmed",),
        Severity.WARNING,
    ),
    _rule(
        "procedure_consistent_with_delivery_form",
        "Procedure Consistent With Delivery Form",
        "Procedure and tender basis fit the chosen delivery form.",
        ("procedure_inconsistent_with_delivery_form", "split_form_without_trade_packages"),
    ),
    _rule(
        "design_package_uses_services_rules",
        "Design Package Uses Services Rules",
        "Design packages use services thresholds and carry a fee estimate.",
        ("design_package_uses_works_rules", "design_fee_estimate_missing"),
    ),
    _rule(
        "shortlist_min_bidders",
        "Shortlist Minimum Bidders",
        "The short list reaches the procedure's minimum and every short-listed company passes prequalification.",
        ("shortlist_below_min_bidders", "shortlisted_candidate_fails_prequal", "candidate_not_registered"),
    ),
    _rule(
        "excluded_candidate_has_rationale",
        "Excluded Candidate Has Rationale",
        "Every excluded candidate has a rationale.",
        ("excluded_candidate_without_rationale",),
    ),
    _rule(
        "capacity_risk_mitigated",
        "Capacity Risk Mitigated",
        "Tight or insufficient market capacity has a mitigation or a re-split.",
        ("capacity_unmitigated",),
    ),
    _rule(
        "prequal_evidence_valid",
        "Prequalification Evidence Valid",
        "Prequalification evidence is valid on the planned award date.",
        ("prequal_evidence_expires_before_award",),
        Severity.WARNING,
    ),
    _rule(
        "award_schedule_feasible",
        "Award Schedule Feasible",
        "The procurement start is not in the past and not before the releasing gate.",
        ("award_schedule_infeasible", "need_date_missing", "release_gate_unresolved"),
    ),
    _rule(
        "advance_package_released",
        "Advance Package Released",
        "An advance package has a reason and is released by a governance decision or condition.",
        ("advance_without_reason", "advance_package_not_released"),
    ),
    _rule(
        "advance_flag_has_release_gate",
        "Advance Flag Has Release Gate",
        "A package is marked as advance only where a gate releases procurement.",
        ("advance_flag_not_applicable",),
        Severity.WARNING,
    ),
    _rule(
        "rule_override_has_reason",
        "Rule Override Has Reason",
        "A manual override of a rule outcome carries a reason.",
        ("rule_override_without_reason",),
    ),
    _rule(
        "concept_asked_at_a_gate",
        "Concept Asked At A Gate",
        "The phase model asks for the procurement concept at one gate at least.",
        ("concept_required_at_no_gate",),
        Severity.WARNING,
    ),
    _rule(
        "framework_call_off_valid",
        "Framework Call-Off Valid",
        "A call-off uses an active framework covering the package, running past award, with value left.",
        (
            "framework_missing",
            "framework_not_active",
            "framework_scope_mismatch",
            "framework_expired",
            "framework_exhausted",
            "framework_currency_mismatch",
            "framework_remaining_unknown",
            "framework_procedure_mismatch",
        ),
    ),
)

RULE_CODES: dict[str, tuple[str, ...]] = {r.key: r.codes for r in PROCUREMENT_RULES}  # type: ignore[attr-defined]


def register_procurement_concept_rules() -> None:
    """Idempotently register the procurement concept rules."""
    for rule in PROCUREMENT_RULES:
        rule_registry.register(rule(), rule_sets=[PROCUREMENT_RULE_SET])


# Registered on import as well, like the platform rule modules: whoever imports the rules sees them,
# not only an app that ran the startup hook. Registration is idempotent.
register_procurement_concept_rules()
