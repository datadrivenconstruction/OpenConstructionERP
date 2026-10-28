# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rule set ``stakeholders`` (SPEC section 7).

The rules read one payload, built by ``StakeholderService.validation_payload``::

    {
      "today": "YYYY-MM-DD",
      "framework": {...pinned stakeholder_framework body...},
      "stakeholders": [{"code", "category", "status", "review_due"}],
      "key_without_plan": [codes],
      "events": [{"id", "title", "feedback_not_reported"}],
      "commitments": [{"code", "status", "owner", "due_date", "overdue", "breach_rationale"}],
      "missing_deciders": [decision types],
      "conflicts": [{"decision_type", "user_id", "letters", "severity", "acknowledged"}],
      "vacant_required": [role codes],
      "bodies": [{"code", "needed", "present"}]
    }

Several are also enforced at write time (two deciders, self approval under
``forbid_self_approval``). They exist as rules because the register moves
without a write here: a date passes, a holder's validity ends, a framework
version is republished.
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
from app.modules.stakeholders.catalogue import StakeholderFramework, validate_framework
from app.modules.stakeholders.messages import translate

STAKEHOLDER_RULE_SET = "stakeholders"
_OPEN = ("proposed", "agreed", "in_progress", "breached")


def _locale(context: ValidationContext) -> str:
    meta = getattr(context, "metadata", None) or {}
    return str(meta.get("locale") or "en")


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _rows(context: ValidationContext, key: str) -> list[Any]:
    raw = _data(context).get(key) or []
    return list(raw) if isinstance(raw, list) else []


def _framework(context: ValidationContext) -> StakeholderFramework | None:
    body = _data(context).get("framework")
    try:
        return StakeholderFramework.model_validate(body) if isinstance(body, dict) else None
    except Exception:
        return None


class _StakeholderRule(ValidationRule):
    standard = "stakeholders"
    category = RuleCategory.COMPLETENESS
    severity = Severity.WARNING
    key = ""

    def _result(self, locale: str, passed: bool, ref: str) -> RuleResult:
        base = f"stakeholders.rules.{self.key}"
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message=translate("common.ok", locale=locale)
            if passed
            else translate(f"{base}.fail", locale=locale, ref=ref),
            element_ref=ref,
            suggestion=None if passed else translate(f"{base}.suggestion", locale=locale),
        )


class StakeholderHasCategory(_StakeholderRule):
    key = "stakeholder_has_category"
    rule_id = "stakeholders.stakeholder_has_category"
    name = "Stakeholder Has Category"
    severity = Severity.ERROR
    description = "Every stakeholder carries a category of the pinned framework (rule 1)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        fw = _framework(context)
        if fw is None:
            return []
        loc = _locale(context)
        return [
            self._result(loc, fw.category(s.get("category") or "") is not None, s["code"])
            for s in _rows(context, "stakeholders")
            if s.get("status") != "archived"
        ]


class AssessmentCurrent(_StakeholderRule):
    key = "assessment_current"
    rule_id = "stakeholders.assessment_current"
    name = "Assessment Current"
    description = "A stakeholder's latest assessment is within the review interval (rule 4)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, not s.get("review_due"), s["code"])
            for s in _rows(context, "stakeholders")
            if s.get("status") == "active"
        ]


class KeyStakeholderHasPlan(_StakeholderRule):
    key = "key_stakeholder_has_plan"
    rule_id = "stakeholders.key_stakeholder_has_plan"
    name = "Key Stakeholder Has Plan"
    description = "A manage-closely stakeholder with an engagement gap has a live plan item (rule 5)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [self._result(loc, False, code) for code in _rows(context, "key_without_plan")]


class FeedbackReported(_StakeholderRule):
    key = "feedback_reported"
    rule_id = "stakeholders.feedback_reported"
    name = "Feedback Reported"
    description = "An event at consult level or higher reports feedback within the framework's days (rule 8)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, not e.get("feedback_not_reported"), e.get("title") or e.get("id") or "")
            for e in _rows(context, "events")
        ]


class CommitmentHasOwnerAndDue(_StakeholderRule):
    key = "commitment_has_owner_and_due"
    rule_id = "stakeholders.commitment_has_owner_and_due"
    name = "Commitment Has Owner And Due"
    description = "An open commitment names who keeps it and by when."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, bool(c.get("owner")) and bool(c.get("due_date")), c["code"])
            for c in _rows(context, "commitments")
            if c.get("status") in _OPEN
        ]


class CommitmentNotBreached(_StakeholderRule):
    key = "commitment_not_breached"
    rule_id = "stakeholders.commitment_not_breached"
    name = "Commitment Not Breached"
    severity = Severity.ERROR
    description = "No open commitment is overdue and no breach stands without a rationale (rule 18)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        out = []
        for c in _rows(context, "commitments"):
            if c.get("status") not in _OPEN:
                continue
            unexplained = c.get("status") == "breached" and not (c.get("breach_rationale") or "").strip()
            out.append(self._result(loc, not (c.get("overdue") or unexplained), c["code"]))
        return out


class MandateOneDecider(_StakeholderRule):
    key = "mandate_one_decider"
    rule_id = "stakeholders.mandate_one_decider"
    name = "Mandate One Decider"
    severity = Severity.ERROR
    description = "Every required decision type has exactly one deciding role or body (rule 13)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        fw = _framework(context)
        if fw is None:
            return []
        loc = _locale(context)
        missing = set(_rows(context, "missing_deciders"))
        return [self._result(loc, d.code not in missing, d.code) for d in fw.decision_types if d.required]


class MandateNoSelfApproval(_StakeholderRule):
    key = "mandate_no_self_approval"
    rule_id = "stakeholders.mandate_no_self_approval"
    name = "Mandate No Self Approval"
    description = "No person proposes and decides, or decides and co-signs, one decision type unacknowledged (rule 12)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        out = []
        for c in _rows(context, "conflicts"):
            ok = c.get("severity") == "warning" and bool(c.get("acknowledged"))
            out.append(self._result(loc, ok, c.get("decision_type") or ""))
        return out


class RoleNotVacant(_StakeholderRule):
    key = "role_not_vacant"
    rule_id = "stakeholders.role_not_vacant"
    name = "Role Not Vacant"
    description = "Every required role has a holder valid today (rule 14)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        fw = _framework(context)
        if fw is None:
            return []
        loc = _locale(context)
        vacant = set(_rows(context, "vacant_required"))
        return [self._result(loc, r.code not in vacant, r.code) for r in fw.roles if r.required]


class BodyQuorate(_StakeholderRule):
    key = "body_quorate"
    rule_id = "stakeholders.body_quorate"
    name = "Body Quorate"
    description = "A governance body has at least its quorum of valid voting members today (rule 15)."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [
            self._result(loc, int(b.get("present") or 0) >= int(b.get("needed") or 0), b["code"])
            for b in _rows(context, "bodies")
        ]


class FrameworkScalesValid(_StakeholderRule):
    key = "framework_scales_valid"
    rule_id = "stakeholders.framework_scales_valid"
    name = "Framework Scales Valid"
    severity = Severity.ERROR
    description = "The pinned framework's scales, classifications and template are consistent."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        fw = _framework(context)
        if fw is None:
            return []
        return [self._result(_locale(context), not validate_framework(fw, "tenant"), fw.id)]


STAKEHOLDER_RULES: tuple[type[ValidationRule], ...] = (
    StakeholderHasCategory,
    AssessmentCurrent,
    KeyStakeholderHasPlan,
    FeedbackReported,
    CommitmentHasOwnerAndDue,
    CommitmentNotBreached,
    MandateOneDecider,
    MandateNoSelfApproval,
    RoleNotVacant,
    BodyQuorate,
    FrameworkScalesValid,
)


def register_stakeholder_rules() -> None:
    """Idempotently register the stakeholders rules."""
    for rule in STAKEHOLDER_RULES:
        rule_registry.register(rule(), rule_sets=[STAKEHOLDER_RULE_SET])


# Registered on import as well, like the platform rule modules: whoever imports the rules sees them,
# not only an app that ran the startup hook. Registration is idempotent.
register_stakeholder_rules()
