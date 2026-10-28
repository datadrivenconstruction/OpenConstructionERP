# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rule set ``project_governance``.

The rules read one payload, built by ``GovernanceService.validation_payload``::

    {
      "areas":      [{"code", "owner_user_id", "applicable", "na_rationale"}],
      "gates":      [{"code", "status", "target_date", "sort_order", "historic"}],
      "documents":  [{"id", "doc_type", "area_code", "status", "required_at_gates",
                      "bound_revision_id", "current_revision_id"}],
      "conditions": [{"id", "status", "due_date"}],
      "decisions":  [{"gate_code", "decided_by", "four_eyes", "owner_ids"}],
      "today":      "YYYY-MM-DD"
    }

Most of these are enforced at write time too. They exist as rules because a
project's state also moves without a write here (a new CDE revision, a date
passing, an owner leaving), and the validation screen is where that shows.
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
from app.modules.project_governance.messages import translate

GOVERNANCE_RULE_SET = "project_governance"


def _locale(context: ValidationContext) -> str:
    meta = getattr(context, "metadata", None) or {}
    return str(meta.get("locale") or "en")


def _rows(context: ValidationContext, key: str) -> list[dict[str, Any]]:
    data = context.data if isinstance(context.data, dict) else {}
    raw = data.get(key) or []
    return [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []


def _today(context: ValidationContext) -> str:
    data = context.data if isinstance(context.data, dict) else {}
    return str(data.get("today") or "")[:10]


class _GovernanceRule(ValidationRule):
    standard = "governance"
    category = RuleCategory.COMPLETENESS
    severity = Severity.ERROR
    key = ""

    def _result(self, locale: str, passed: bool, ref: str, **params: Any) -> RuleResult:
        base = f"governance.rules.{self.key}"
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


class AreaHasOwner(_GovernanceRule):
    """Every applicable area has an owner."""

    key = "area_has_owner"
    rule_id = "project_governance.area_has_owner"
    name = "Area Has Owner"
    description = "An applicable management area without an owner cannot attest readiness and blocks its gate."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, bool(a.get("owner_user_id")), str(a.get("code")), area=a.get("code"))
            for a in _rows(context, "areas")
            if a.get("applicable", True)
        ]


class RequiredDocumentsDefined(_GovernanceRule):
    """Each undecided gate has at least one required document across its applicable areas."""

    key = "required_documents_defined"
    rule_id = "project_governance.required_documents_defined"
    name = "Required Documents Defined"
    severity = Severity.WARNING
    description = "A gate that requires no frame document approves nothing it can later hold the project to."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        applicable = {a.get("code") for a in _rows(context, "areas") if a.get("applicable", True)}
        docs = [d for d in _rows(context, "documents") if d.get("area_code") in applicable]
        out = []
        for g in _rows(context, "gates"):
            if g.get("historic") or g.get("status") == "decided":
                continue
            has = any(g.get("code") in (d.get("required_at_gates") or []) for d in docs)
            out.append(self._result(loc, has, str(g.get("code")), gate=g.get("code")))
        return out


class BindingDocumentUnchanged(_GovernanceRule):
    """A binding document's current CDE revision is the bound one."""

    key = "binding_document_unchanged"
    rule_id = "project_governance.binding_document_unchanged"
    name = "Binding Document Unchanged"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "A newer revision of a binding frame document is in use without an approved change request."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        out = []
        for d in _rows(context, "documents"):
            if d.get("status") != "binding":
                continue
            current, bound = d.get("current_revision_id"), d.get("bound_revision_id")
            passed = not current or current == bound
            out.append(self._result(loc, passed, str(d.get("id")), document=d.get("doc_type")))
        return out


class ConditionsNotOverdue(_GovernanceRule):
    """No open condition is past its due date."""

    key = "conditions_not_overdue"
    rule_id = "project_governance.conditions_not_overdue"
    name = "Conditions Not Overdue"
    category = RuleCategory.COMPLIANCE
    description = "An overdue gate condition blocks the next gate until it is cleared or waived."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc, today = _locale(context), _today(context)
        out = []
        for c in _rows(context, "conditions"):
            if c.get("status") not in ("open", "overdue"):
                continue
            due = str(c.get("due_date") or "")[:10]
            passed = not (due and today and due < today)
            out.append(self._result(loc, passed, str(c.get("id")), condition=c.get("id"), due=due))
        return out


class GateDateAfterPrevious(_GovernanceRule):
    """Planned gate dates follow the phase order."""

    key = "gate_date_after_previous"
    rule_id = "project_governance.gate_date_after_previous"
    name = "Gate Date After Previous"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "A gate planned before the gate that precedes it cannot be reached in that order."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        gates = sorted(
            (g for g in _rows(context, "gates") if not g.get("historic")), key=lambda g: g.get("sort_order") or 0
        )
        out, previous = [], None
        for g in gates:
            day = str(g.get("target_date") or "")[:10]
            if not day:
                continue
            if previous is not None:
                passed = day >= previous[1]
                out.append(
                    self._result(loc, passed, str(g.get("code")), gate=g.get("code"), date=day, previous=previous[1])
                )
            previous = (g.get("code"), day)
        return out


class DecisionByEntitledUser(_GovernanceRule):
    """Under four-eyes, no decision was taken by an owner of one of the gate's areas."""

    key = "decision_by_entitled_user"
    rule_id = "project_governance.decision_by_entitled_user"
    name = "Decision By Entitled User"
    category = RuleCategory.COMPLIANCE
    description = "Checks the recorded decisions against the four-eyes rule as it stood when each was taken."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        out = []
        for d in _rows(context, "decisions"):
            if not d.get("four_eyes"):
                continue
            passed = str(d.get("decided_by")) not in {str(x) for x in d.get("owner_ids") or []}
            out.append(self._result(loc, passed, str(d.get("gate_code")), gate=d.get("gate_code")))
        return out


class NotApplicableHasRationale(_GovernanceRule):
    """An area marked not applicable says why."""

    key = "not_applicable_has_rationale"
    rule_id = "project_governance.not_applicable_has_rationale"
    name = "Not Applicable Has Rationale"
    description = "An area left out of the gates without a written reason is indistinguishable from one forgotten."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, bool(str(a.get("na_rationale") or "").strip()), str(a.get("code")), area=a.get("code"))
            for a in _rows(context, "areas")
            if not a.get("applicable", True)
        ]


GOVERNANCE_RULES: tuple[type[ValidationRule], ...] = (
    AreaHasOwner,
    RequiredDocumentsDefined,
    BindingDocumentUnchanged,
    ConditionsNotOverdue,
    GateDateAfterPrevious,
    DecisionByEntitledUser,
    NotApplicableHasRationale,
)


def register_governance_rules() -> None:
    """Idempotently register the project governance rules."""
    for rule in GOVERNANCE_RULES:
        rule_registry.register(rule(), rule_sets=[GOVERNANCE_RULE_SET])


# Registered on import as well, like the platform rule modules: whoever imports the rules sees them,
# not only an app that ran the startup hook. Registration is idempotent.
register_governance_rules()
