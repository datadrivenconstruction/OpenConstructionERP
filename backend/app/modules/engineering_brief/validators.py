# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rule set ``engineering_brief``.

The rules read one payload, built by ``EngineeringBriefService.validation_payload``::

    {
      "catalogue": EngineeringBriefCatalogue,
      "brief": {"status", "operation_proof_date"},
      "requirements": [...], "concepts": [...], "programme": [...], "milestones": [...],
      "gates": [...], "operation_proof_date": date | None,
      "permit_states": {requirement_id: state | None}, "activities": {activity_id: {...} | None},
      "requirements_changed": bool
    }

Every rule calls the same pure function the service uses (``rules.py``) and keeps the findings of its
own codes, so a check has one implementation.
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
from app.modules.engineering_brief import rules
from app.modules.engineering_brief.messages import translate

BRIEF_RULE_SET = "engineering_brief"


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _locale(context: ValidationContext) -> str:
    return str((getattr(context, "metadata", None) or {}).get("locale") or "en")


def _all_findings(context: ValidationContext) -> list[rules.Finding]:
    data = _data(context)
    catalogue = data.get("catalogue")
    if catalogue is None:
        return []
    return rules.submission_findings(
        catalogue,
        requirements=data.get("requirements") or [],
        concepts=data.get("concepts") or [],
        programme=data.get("programme") or [],
        milestones=data.get("milestones") or [],
        gates=data.get("gates") or [],
        operation_proof_date=data.get("operation_proof_date"),
        permit_states=data.get("permit_states") or {},
        activities=data.get("activities") or {},
    )


class _BriefRule(ValidationRule):
    standard = "engineering_brief"
    category = RuleCategory.CONSISTENCY
    severity = Severity.ERROR
    key = ""
    codes: tuple[str, ...] = ()

    @property
    def _base(self) -> str:
        return f"engineering_brief.rules.{self.key}"

    def _result(self, locale: str, passed: bool, ref: str, severity: Severity | None = None, **params: Any):
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=severity or self.severity,
            category=self.category,
            passed=passed,
            message=translate("engineering_brief.rules.ok", locale=locale)
            if passed
            else translate(f"{self._base}.fail", locale=locale, ref=ref, **params),
            element_ref=ref,
            suggestion=None if passed else translate(f"{self._base}.suggestion", locale=locale),
        )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        found = [f for f in _all_findings(context) if f.code in self.codes]
        if not found:
            return [self._result(loc, True, "project")]
        return [
            self._result(loc, False, f.ref, Severity.WARNING if f.severity == rules.WARNING else Severity.ERROR)
            for f in found
        ]


class RequirementsPresent(_BriefRule):
    key = "requirements_present"
    rule_id = "engineering_brief.requirements_present"
    name = "Requirements Present"
    description = "The brief holds at least one structured requirement."
    codes = ("no_requirements",)


class CategoriesCovered(_BriefRule):
    key = "categories_covered"
    rule_id = "engineering_brief.categories_covered"
    name = "Categories Covered"
    description = "Every requirement category the catalogue asks for has at least one requirement."
    codes = ("category_uncovered",)


class RequirementsVerifiable(_BriefRule):
    key = "requirements_verifiable"
    rule_id = "engineering_brief.requirements_verifiable"
    name = "Requirements Verifiable"
    severity = Severity.WARNING
    description = "A must requirement names how it is verified; every requirement says where it comes from."
    codes = ("requirement_unverifiable", "requirement_without_origin", "requirement_category_unknown")


class ConceptCoversTopics(_BriefRule):
    key = "concept_covers_topics"
    rule_id = "engineering_brief.concept_covers_topics"
    name = "Concept Covers Topics"
    description = "Every topic of the technical concept the catalogue requires is present and decided."
    codes = ("topic_missing", "topic_undecided", "concept_topic_unknown")


class ConceptTraceable(_BriefRule):
    key = "concept_traceable"
    rule_id = "engineering_brief.concept_traceable"
    name = "Concept Traceable"
    description = "A concept item answers requirements that exist, and every must requirement is answered."
    codes = ("concept_requirement_missing", "requirement_unanswered")


class ProgrammeComplete(_BriefRule):
    key = "programme_complete"
    rule_id = "engineering_brief.programme_complete"
    name = "Programme Complete"
    description = "The area and quantity programme has lines of a known kind with a unit and a positive quantity."
    codes = ("programme_missing", "programme_kind_unknown", "programme_unit_missing", "programme_quantity_invalid")


class ScheduleAnchored(_BriefRule):
    key = "schedule_anchored"
    rule_id = "engineering_brief.schedule_anchored"
    name = "Schedule Anchored"
    description = "The framework schedule has an operating proof date and one anchor milestone that carries it."
    codes = ("operation_proof_missing", "anchor_milestone_missing", "anchor_date_differs")


class ScheduleBackwardConsistent(_BriefRule):
    key = "schedule_backward_consistent"
    rule_id = "engineering_brief.schedule_backward_consistent"
    name = "Schedule Backward Consistent"
    description = "Every milestone is dated, chained to a successor and early enough for its lead time."
    codes = (
        "milestone_date_missing",
        "milestone_kind_unknown",
        "milestone_too_late",
        "milestone_unchained",
        "successor_cycle",
        "successor_unknown",
    )


class GatesBound(_BriefRule):
    key = "gates_bound"
    rule_id = "engineering_brief.gates_bound"
    name = "Gates Bound"
    description = "Every gate of the project has exactly one milestone, in the gates' order and on the gate's date."
    codes = (
        "gate_without_milestone",
        "gate_milestone_duplicate",
        "gate_unknown",
        "gate_code_on_wrong_kind",
        "gate_milestone_without_gate",
        "gates_out_of_order",
        "gate_date_differs",
        "gate_not_bound_to_schedule",
    )


class SchedulePublishedInSync(_BriefRule):
    key = "schedule_published_in_sync"
    rule_id = "engineering_brief.schedule_published_in_sync"
    name = "Schedule Published In Sync"
    severity = Severity.WARNING
    description = "A published milestone still exists in the schedule and sits on the planned date."
    codes = ("activity_missing", "schedule_out_of_sync")


class PermitLinkResolves(_BriefRule):
    key = "permit_link_resolves"
    rule_id = "engineering_brief.permit_link_resolves"
    name = "Permit Link Resolves"
    description = "A milestone linked to a permit requirement points at one that exists in this project."
    codes = ("permit_requirement_unknown",)


class RequirementsUnchangedSinceBound(_BriefRule):
    key = "requirements_unchanged_since_bound"
    rule_id = "engineering_brief.requirements_unchanged_since_bound"
    name = "Requirements Unchanged Since Bound"
    severity = Severity.WARNING
    description = "The requirements were not edited in the requirements register after the brief was bound."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [self._result(loc, not _data(context).get("requirements_changed"), "requirements")]


BRIEF_RULES: tuple[type[ValidationRule], ...] = (
    RequirementsPresent,
    CategoriesCovered,
    RequirementsVerifiable,
    ConceptCoversTopics,
    ConceptTraceable,
    ProgrammeComplete,
    ScheduleAnchored,
    ScheduleBackwardConsistent,
    GatesBound,
    SchedulePublishedInSync,
    PermitLinkResolves,
    RequirementsUnchangedSinceBound,
)


def register_engineering_brief_rules() -> None:
    """Idempotently register the engineering brief rules."""
    for rule in BRIEF_RULES:
        rule_registry.register(rule(), rule_sets=[BRIEF_RULE_SET])


# Registered on import as well, like the platform rule modules: whoever imports the rules sees them,
# not only an app that ran the startup hook. Registration is idempotent.
register_engineering_brief_rules()
