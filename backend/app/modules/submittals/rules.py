# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The register rules of the ``submittal`` rule set.

The checks themselves are the pure functions in
:mod:`app.modules.submittals.validators`; each class here only turns a
``Finding`` into a ``RuleResult`` with a translated message, the same thin
wrapper the seven submission-gate rules use in ``app.core.validation.rules``.
They are registered into the same ``submittal`` set, from this module's
startup hook, so one call to the engine reports both groups.

Messages are in :mod:`app.modules.submittals.messages` (English and Turkish;
any other language reads the English).
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
from app.core.validation.messages import translate as translate_shared
from app.modules.submittals import validators as checks
from app.modules.submittals.messages import translate

logger = logging.getLogger(__name__)

#: The set these rules join. The same name as ``service.SUBMITTAL_RULE_SET``,
#: restated here so this file does not import the service.
SUBMITTAL_RULE_SET = "submittal"


def _locale(context: ValidationContext) -> str:
    meta = getattr(context, "metadata", None) or {}
    return str(meta.get("locale") or "en")


def _status_word(code: str, locale: str) -> str:
    """A status or outcome code as the word the register prints for it."""
    from app.modules.submittals.pdf_translations import CATALOGUE

    return CATALOGUE.label("status", code, locale)


class _RegisterRule(ValidationRule):
    """Shared body: run one pure check in ``submittals.validators``."""

    standard = SUBMITTAL_RULE_SET

    #: Name of the ``submittals.validators`` function this rule delegates to.
    check_name: str = ""
    #: Message parameters that hold a status code and are printed as a word.
    status_params: tuple[str, ...] = ()

    def _key(self, suffix: str) -> str:
        return f"{self.rule_id}.{suffix}"

    def _params(self, params: dict[str, str], locale: str) -> dict[str, Any]:
        return {
            name: _status_word(value, locale) if name in self.status_params else value for name, value in params.items()
        }

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _locale(context)
        payload = context.data if isinstance(context.data, dict) else {}
        if not payload:
            return []
        findings = getattr(checks, self.check_name)(payload)
        if not findings:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message=translate_shared("common.ok", locale=locale),
                )
            ]
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=translate(self._key("fail"), locale=locale, **self._params(finding.params, locale)),
                element_ref=finding.element_ref,
                details=dict(finding.details),
                suggestion=translate(self._key("suggestion"), locale=locale),
            )
            for finding in findings
        ]


class SubmittalResubmissionLinked(_RegisterRule):
    """A resubmission must be traceable to the revision it replaces."""

    rule_id = "submittal.resubmission_linked"
    name = "Submittal Resubmission Linked"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags a submittal at revision 2 or later with no recorded review of the revision before it."
    check_name = "check_resubmission_linked"


class SubmittalOutcomeMatchesStatus(_RegisterRule):
    """The reviewer's stamp and the workflow status must agree."""

    rule_id = "submittal.outcome_matches_status"
    name = "Submittal Outcome Matches Status"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags a submittal whose stamped review outcome contradicts its workflow status."
    check_name = "check_outcome_matches_status"
    status_params = ("outcome", "status")


class SubmittalRequiredOnSiteAfterSubmitted(_RegisterRule):
    """An item cannot be needed on site before its submittal was filed."""

    rule_id = "submittal.required_on_site_after_submitted"
    name = "Submittal Required On Site After Submitted"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags a required on site date earlier than the submission date."
    check_name = "check_required_on_site_after_submitted"


class SubmittalLongLeadHasLeadTime(_RegisterRule):
    """A long-lead item must say how long the lead is."""

    rule_id = "submittal.long_lead_has_lead_time"
    name = "Submittal Long Lead Has Lead Time"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Flags a long-lead submittal with no lead time, whose approval needed-by date cannot be computed."
    check_name = "check_long_lead_has_lead_time"


class SubmittalApprovalNeededByNotPassed(_RegisterRule):
    """Past required on site less lead time, an unapproved item is already late."""

    rule_id = "submittal.approval_needed_by_not_passed"
    name = "Submittal Approval Needed-By Not Passed"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags a submittal still not approved after the date its approval was needed by, with the days late."
    check_name = "check_approval_needed_by_not_passed"


class SubmittalMaterialHasManufacturer(_RegisterRule):
    """A material submittal should name who makes the product."""

    rule_id = "submittal.material_has_manufacturer"
    name = "Submittal Material Has Manufacturer"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags a product data or sample submittal with no manufacturer."
    check_name = "check_material_has_manufacturer"


SUBMITTAL_REGISTER_RULES: tuple[type[_RegisterRule], ...] = (
    SubmittalResubmissionLinked,
    SubmittalOutcomeMatchesStatus,
    SubmittalRequiredOnSiteAfterSubmitted,
    SubmittalLongLeadHasLeadTime,
    SubmittalApprovalNeededByNotPassed,
    SubmittalMaterialHasManufacturer,
)


def register_submittal_register_rules() -> None:
    """Register the register rules into the ``submittal`` set. Safe to call twice."""
    for rule_class in SUBMITTAL_REGISTER_RULES:
        rule_registry.register(rule_class(), [SUBMITTAL_RULE_SET])
    logger.debug("submittals: registered %d register rules", len(SUBMITTAL_REGISTER_RULES))


__all__ = [
    "SUBMITTAL_REGISTER_RULES",
    "SUBMITTAL_RULE_SET",
    "register_submittal_register_rules",
]
