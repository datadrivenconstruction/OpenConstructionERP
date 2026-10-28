# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rule set ``hse_frame``.

The rules read one payload, built by ``HseFrameService.validation_payload``;
every finding in it already carries its code, so a rule here is the lens that
picks the findings of its code and turns them into ``RuleResult`` rows with
translated text. A rule with nothing to report returns one passing row, so the
report shows the rule was checked.
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
from app.modules.hse_frame.messages import translate

HSE_FRAME_RULE_SET = "hse_frame"


def _locale(context: ValidationContext) -> str:
    meta = getattr(context, "metadata", None) or {}
    return str(meta.get("locale") or "en")


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


class _HseRule(ValidationRule):
    standard = "hse_frame"
    category = RuleCategory.COMPLETENESS
    severity = Severity.ERROR
    key = ""
    # Finding codes the rule reports.
    codes: tuple[str, ...] = ()

    def _result(self, locale: str, passed: bool, ref: str, **params: Any) -> RuleResult:
        base = f"hse_frame.rules.{self.key}"
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message=translate("hse_frame.common.ok", locale=locale)
            if passed
            else translate(f"{base}.fail", locale=locale, ref=ref, **{k: str(v) for k, v in params.items()}),
            element_ref=ref or None,
            suggestion=None if passed else translate(f"{base}.suggestion", locale=locale),
        )

    def findings(self, context: ValidationContext) -> list[dict[str, Any]]:
        rows = _data(context).get("findings") or []
        return [r for r in rows if isinstance(r, dict) and r.get("code") in self.codes]

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        hits = self.findings(context)
        if not hits:
            return [self._result(loc, True, "")]
        return [self._result(loc, False, str(h.get("ref") or ""), **(h.get("params") or {})) for h in hits]


def _rule(key: str, name: str, codes: tuple[str, ...], severity: Severity = Severity.ERROR) -> type[_HseRule]:
    return type(
        "".join(p.capitalize() for p in key.split("_")),
        (_HseRule,),
        {
            "key": key,
            "rule_id": f"hse_frame.{key}",
            "name": name,
            "description": name,
            "severity": severity,
            "codes": codes,
        },
    )


CoordinatorAppointed = _rule(
    "coordinator_appointed", "Coordinator Appointed When Required", ("coordinator_missing", "required_role_missing")
)
AdvanceNoticeSent = _rule("advance_notice_sent", "Advance Notice Sent When Required", ("advance_notice_missing",))
PlanIssued = _rule("plan_issued", "Health And Safety Plan Issued When Required", ("plan_missing",))
LaterWorksFileComplete = _rule(
    "later_works_file_complete", "File For Later Works Complete", ("later_works_file_missing",), Severity.WARNING
)
ItemHasOwner = _rule("item_has_owner", "Mandatory Item Has An Owner", ("item_without_owner",), Severity.WARNING)
ItemNotOverdue = _rule("item_not_overdue", "Register Item Not Overdue", ("item_overdue",), Severity.WARNING)
RoleQualified = _rule(
    "role_qualified",
    "Appointed Role Is Qualified",
    ("role_without_qualification", "role_qualification_expired"),
    Severity.WARNING,
)
PermitConditionsConsolidated = _rule(
    "permit_conditions_consolidated",
    "Permit Conditions Merged Into The Register",
    ("permit_condition_unconsolidated",),
    Severity.WARNING,
)
SeriousIncidentLinked = _rule(
    "serious_incident_linked",
    "Serious Incident Linked To The Register",
    ("serious_incident_unlinked",),
    Severity.WARNING,
)

HSE_FRAME_RULES: tuple[type[ValidationRule], ...] = (
    CoordinatorAppointed,
    AdvanceNoticeSent,
    PlanIssued,
    LaterWorksFileComplete,
    ItemHasOwner,
    ItemNotOverdue,
    RoleQualified,
    PermitConditionsConsolidated,
    SeriousIncidentLinked,
)


def register_hse_frame_rules() -> None:
    """Idempotently register the HSE frame rules."""
    for rule in HSE_FRAME_RULES:
        rule_registry.register(rule(), rule_sets=[HSE_FRAME_RULE_SET])


# Registered on import as well, like the platform rule modules: whoever imports the rules sees them,
# not only an app that ran the startup hook. Registration is idempotent.
register_hse_frame_rules()
