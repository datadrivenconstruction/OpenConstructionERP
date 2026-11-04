# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Risk register validation rules (rule set ``risk``).

Rules judge the risk as it will be after the write::

    {"risk": {"id", "status", "previous_status", "impact_severity", "impact_cost", "response_cost",
              "mitigation_strategy", "mitigation_actions", "owner_name", "owner_user_id",
              "written": [field names being written, absent on create]}}

* ``risk.mitigation_defined`` (ERROR): a risk being mitigated, or marked mitigated, says how.
* ``risk.owner_named`` (WARNING): an assessed high or critical risk has an owner.
* ``risk.response_within_exposure`` (WARNING): the response does not cost more than the loss it prevents.
* ``risk.closed_with_cause`` (WARNING): a high risk is closed after mitigation or occurrence, not unexamined.
"""

from __future__ import annotations

from app.core.validation.control_rules import ControlRule
from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section, to_dec

RISK_RULE_SET = "risk"

_HIGH = frozenset({"high", "critical", "major", "catastrophic"})
_ASSESSED = frozenset({"assessed", "mitigating", "monitoring", "mitigated"})
_UNEXAMINED = frozenset({"identified", "assessed", "open"})


class MitigationDefinedRule(ControlRule):
    rule_id = "risk.mitigation_defined"
    name = "Mitigated risk has a mitigation"
    standard = RISK_RULE_SET
    description = "Status mitigating or mitigated needs a mitigation strategy or at least one mitigation action"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        risk = section(context, "risk")
        ref = str(risk.get("id", ""))
        written = risk.get("written")
        if written is not None and not {"status", "mitigation_strategy"} & set(written):
            return [self.ok(ref)]  # an unrelated edit never blocks on a legacy record
        if risk.get("status") not in {"mitigating", "mitigated"}:
            return [self.ok(ref)]
        if not blank(risk.get("mitigation_strategy")) or risk.get("mitigation_actions"):
            return [self.ok(ref)]
        return [self.fail(context, "mitigation_missing", ref=ref, status=risk.get("status"))]


class OwnerNamedRule(ControlRule):
    rule_id = "risk.owner_named"
    name = "Assessed high risk has an owner"
    standard = RISK_RULE_SET
    severity = Severity.WARNING
    description = "A high or critical risk that has been assessed names the person who owns it"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        risk = section(context, "risk")
        ref = str(risk.get("id", ""))
        if risk.get("status") not in _ASSESSED or risk.get("impact_severity") not in _HIGH:
            return [self.ok(ref)]
        if not blank(risk.get("owner_name")) or not blank(risk.get("owner_user_id")):
            return [self.ok(ref)]
        return [self.fail(context, "owner_missing", ref=ref)]


class ResponseWithinExposureRule(ControlRule):
    rule_id = "risk.response_within_exposure"
    name = "Risk response costs less than the loss"
    standard = RISK_RULE_SET
    severity = Severity.WARNING
    description = "response_cost above the full impact_cost means the response is dearer than the risk"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        risk = section(context, "risk")
        ref = str(risk.get("id", ""))
        impact, response = to_dec(risk.get("impact_cost")), to_dec(risk.get("response_cost"))
        if impact is None or response is None or impact <= 0 or response <= impact:
            return [self.ok(ref)]
        return [self.fail(context, "response_exceeds_exposure", ref=ref, response=response, impact=impact)]


class ClosedWithCauseRule(ControlRule):
    rule_id = "risk.closed_with_cause"
    name = "High risk closed after mitigation or occurrence"
    standard = RISK_RULE_SET
    severity = Severity.WARNING
    description = "Closing a high risk straight from identified or assessed skips mitigation"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        risk = section(context, "risk")
        ref = str(risk.get("id", ""))
        closing = risk.get("status") == "closed" and risk.get("previous_status") in _UNEXAMINED
        if closing and risk.get("impact_severity") in _HIGH:
            return [self.fail(context, "closed_unaddressed", ref=ref, level=risk.get("impact_severity"))]
        return [self.ok(ref)]


RISK_RULES = (MitigationDefinedRule, OwnerNamedRule, ResponseWithinExposureRule, ClosedWithCauseRule)


def register_risk_validation_rules() -> None:
    """Register the risk register rules with the platform rule registry."""
    for rule_class in RISK_RULES:
        rule_registry.register(rule_class(), [RISK_RULE_SET])
