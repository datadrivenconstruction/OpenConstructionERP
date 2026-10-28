# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rule set ``permits`` (SPEC section 7).

The rules read one payload, built by ``PermitService.validation_payload``::

    {"today", "catalogue", "requirements", "edges", "timeline", "applications",
     "decisions", "permits", "conditions", "discharges"}

Most are enforced at write time too; they exist as rules because the register
also moves without a write here: a date passes, a schedule activity moves, a
catalogue version is republished.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.permits.messages import translate

PERMIT_RULE_SET = "permits"
_OPEN = ("open", "evidence_submitted", "discharge_applied", "breach")
_SUBMITTED = ("submitted", "validated", "under_review", "info_requested", "decided")


def _locale(context: ValidationContext) -> str:
    meta = getattr(context, "metadata", None) or {}
    return str(meta.get("locale") or "en")


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _rows(context: ValidationContext, key: str) -> list[dict[str, Any]]:
    raw = _data(context).get(key) or []
    return [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []


def _today(context: ValidationContext) -> date:
    return date.fromisoformat(str(_data(context).get("today")))


def _conds(context: ValidationContext) -> list[dict[str, Any]]:
    return [c for c in _rows(context, "conditions") if c.get("confirmed") and c.get("state") != "superseded"]


class _PermitRule(ValidationRule):
    standard = "permits"
    category = RuleCategory.COMPLETENESS
    severity = Severity.ERROR
    key = ""

    def _result(self, locale: str, passed: bool, ref: str, **params: Any) -> RuleResult:
        base = f"permits.rules.{self.key}"
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message=translate("common.ok", locale=locale)
            if passed
            else translate(f"{base}.fail", locale=locale, **params),
            element_ref=ref,
            suggestion=None if passed else translate(f"{base}.suggestion", locale=locale),
        )


class RequirementHasApplicantAndOwner(_PermitRule):
    key = "requirement_has_applicant_and_owner"
    rule_id = "permits.requirement_has_applicant_and_owner"
    name = "Requirement Has Applicant And Owner"
    description = "Every applicable roadmap row names who applies and who owns it internally."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(
                loc, bool(r.get("applicant_role") and r.get("responsible_user_id")), r["id"], code=r["permit_type_code"]
            )
            for r in _rows(context, "requirements")
            if r.get("applicable")
        ]


class DependencyAcyclic(_PermitRule):
    key = "dependency_acyclic"
    rule_id = "permits.dependency_acyclic"
    name = "Dependency Acyclic"
    description = "Permit dependencies must not form a cycle."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        from app.modules.permits.roadmap import Edge, find_cycle

        edges = [Edge(e["requirement"], e["depends_on"], e.get("on", "granted")) for e in _rows(context, "edges")]
        cycle = find_cycle(edges)
        return [self._result(_locale(context), cycle is None, "roadmap", cycle=" -> ".join(cycle or []))]


class ForecastBeforeNeededBy(_PermitRule):
    key = "forecast_before_needed_by"
    rule_id = "permits.forecast_before_needed_by"
    name = "Forecast Before Needed By"
    severity = Severity.WARNING
    description = "The forecast decision arrives after the schedule needs the permit."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(
                loc,
                not t.get("schedule_conflict") or bool(t.get("conflict_accepted")),
                t["requirement_id"],
                days=t.get("conflict_days", 0),
            )
            for t in _rows(context, "timeline")
            if t.get("needed_by")
        ]


class ApplicationHasAuthorityReference(_PermitRule):
    key = "application_has_authority_reference"
    rule_id = "permits.application_has_authority_reference"
    name = "Application Has Authority Reference"
    severity = Severity.WARNING
    description = "A filed application carries the authority's reference."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, bool(a.get("authority_reference")), a["id"])
            for a in _rows(context, "applications")
            if a.get("state") in _SUBMITTED
        ]


class DecisionHasNoticeDocument(_PermitRule):
    key = "decision_has_notice_document"
    rule_id = "permits.decision_has_notice_document"
    name = "Decision Has Notice Document"
    severity = Severity.WARNING
    description = "A recorded decision links the notice itself (CDE revision)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, bool(d.get("document_revision_id")), d["id"])
            for d in _rows(context, "decisions")
            if d.get("outcome") != "withdrawn"
        ]


class ConditionalGrantHasConditions(_PermitRule):
    key = "conditional_grant_has_conditions"
    rule_id = "permits.conditional_grant_has_conditions"
    name = "Conditional Grant Has Conditions"
    description = "A grant with conditions has its conditions in the register."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        by_decision: dict[str, int] = {}
        permits = {p["id"]: p for p in _rows(context, "permits")}
        for c in _conds(context):
            p = permits.get(c["permit_id"])
            if p:
                by_decision[p["decision_id"]] = by_decision.get(p["decision_id"], 0) + 1
        return [
            self._result(loc, by_decision.get(d["id"], 0) > 0 and not d.get("conditions_pending"), d["id"])
            for d in _rows(context, "decisions")
            if d.get("outcome") == "granted_with_conditions"
        ]


class ConditionHasTriggerAndOwner(_PermitRule):
    key = "condition_has_trigger_and_owner"
    rule_id = "permits.condition_has_trigger_and_owner"
    name = "Condition Has Trigger And Owner"
    description = "Every open condition says when it bites and who answers for it."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, bool(c.get("trigger") and c.get("owner_user_id")), c["id"], number=c["number"])
            for c in _conds(context)
            if c.get("state") in _OPEN
        ]


class ConditionDueNotPassed(_PermitRule):
    key = "condition_due_not_passed"
    rule_id = "permits.condition_due_not_passed"
    name = "Condition Due Not Passed"
    description = "An open condition whose due date has passed."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, not c.get("overdue"), c["id"], number=c["number"], due=c.get("due_date"))
            for c in _conds(context)
            if c.get("due_date")
        ]


class SuspensiveConditionBlocksStart(_PermitRule):
    key = "suspensive_condition_blocks_start"
    rule_id = "permits.suspensive_condition_blocks_start"
    name = "Suspensive Condition Blocks Start"
    description = "An open before-start suspensive condition keeps the permit from taking effect for site start."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, c.get("state") not in _OPEN, c["id"], number=c["number"])
            for c in _conds(context)
            if c.get("kind") == "suspensive" and c.get("trigger") == "before_start"
        ]


class DischargeHasEvidenceAndVerifier(_PermitRule):
    key = "discharge_has_evidence_and_verifier"
    rule_id = "permits.discharge_has_evidence_and_verifier"
    name = "Discharge Has Evidence And Verifier"
    description = "A self-certified discharge relied on evidence and a verifier other than the owner."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(
                loc,
                bool(d.get("evidence_snapshot"))
                and bool(d.get("verifier_user_id"))
                and d.get("verifier_user_id") != d.get("decided_by"),
                d["id"],
            )
            for d in _rows(context, "discharges")
            if d.get("mode") == "self_certified"
        ]


class PermitNotLapsing(_PermitRule):
    key = "permit_not_lapsing"
    rule_id = "permits.permit_not_lapsing"
    name = "Permit Not Lapsing"
    severity = Severity.WARNING
    description = "A permit not started lapses within 90 days."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, p.get("lapse_warning") is None, p["id"], until=p.get("valid_until"))
            for p in _rows(context, "permits")
            if p.get("state") in ("in_force", "lapsed") and p.get("valid_until")
        ]


class CatalogueFiguresHaveSource(_PermitRule):
    key = "catalogue_figures_have_source"
    rule_id = "permits.catalogue_figures_have_source"
    name = "Catalogue Figures Have Source"
    description = "Every statutory period in the pinned catalogue cites its source."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        cat = _data(context).get("catalogue")
        if not isinstance(cat, dict):
            return []
        loc = _locale(context)
        out = []
        for t in cat.get("permit_types") or []:
            clock = t.get("clock") or {}
            if clock.get("period") is not None:
                out.append(self._result(loc, bool(clock.get("source_url")), t["code"], code=t["code"]))
        return out


class UnconfirmedFigureUsed(_PermitRule):
    key = "unconfirmed_figure_used"
    rule_id = "permits.unconfirmed_figure_used"
    name = "Unconfirmed Figure Used"
    severity = Severity.WARNING
    description = "A roadmap row relies on a statutory figure not yet checked on its source."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        cat = _data(context).get("catalogue")
        if not isinstance(cat, dict):
            return []
        types = {t["code"]: t for t in cat.get("permit_types") or []}
        loc = _locale(context)
        out = []
        for r in _rows(context, "requirements"):
            t = types.get(r["permit_type_code"]) or {}
            figures = [t.get("clock") or {}, t.get("validity") or {}]
            unconfirmed = any(
                f.get("review_status") == "unconfirmed" and (f.get("period") or f.get("lapse_if_not_started"))
                for f in figures
            )
            out.append(self._result(loc, not unconfirmed, r["id"], code=r["permit_type_code"]))
        return out


PERMIT_RULES: tuple[type[ValidationRule], ...] = (
    RequirementHasApplicantAndOwner,
    DependencyAcyclic,
    ForecastBeforeNeededBy,
    ApplicationHasAuthorityReference,
    DecisionHasNoticeDocument,
    ConditionalGrantHasConditions,
    ConditionHasTriggerAndOwner,
    ConditionDueNotPassed,
    SuspensiveConditionBlocksStart,
    DischargeHasEvidenceAndVerifier,
    PermitNotLapsing,
    CatalogueFiguresHaveSource,
    UnconfirmedFigureUsed,
)


def register_permit_rules() -> None:
    """Idempotently register the permits rules."""
    for rule in PERMIT_RULES:
        rule_registry.register(rule(), rule_sets=[PERMIT_RULE_SET])


# Registered on import as well, like the platform rule modules: whoever imports the rules sees them,
# not only an app that ran the startup hook. Registration is idempotent.
register_permit_rules()
