# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""NCR validation rules (rule set ``ncr``).

Rules run over a plain dict context built by the caller::

    {"ncr": {"id", "status", "severity", "description", "root_cause", "corrective_action",
             "verified_by", "cost_impact", "due_date"}}

``metadata["today"]`` (ISO date) overrides the reference day for the overdue check.
"""

from __future__ import annotations

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section, to_dec
from app.core.validation.quality_rules import QualityRule, parse_day, today_of

NCR_RULE_SET = "ncr"

#: Statuses in which an NCR is still open and someone owes work on it.
OPEN_STATUSES = frozenset({"identified", "under_review", "corrective_action", "verification"})


class NcrClosureDocumentedRule(QualityRule):
    """A closed NCR records its root cause and corrective action."""

    rule_id = "ncr.closure_documented"
    name = "Closed NCR has root cause and corrective action"
    standard = NCR_RULE_SET
    description = "status closed requires root_cause and corrective_action"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ncr = section(context, "ncr")
        ref = str(ncr.get("id", ""))
        if ncr.get("status") != "closed":
            return [self.ok(ref)]
        out = [
            self.fail(context, "field_required_for_state", ref=ref, state="closed", field=field)
            for field in ("root_cause", "corrective_action")
            if blank(ncr.get(field))
        ]
        return out or [self.ok(ref)]


class NcrClosureVerifiedRule(QualityRule):
    """A closed NCR names who verified the fix."""

    rule_id = "ncr.closure_verified"
    name = "Closed NCR names its verifier"
    standard = NCR_RULE_SET
    severity = Severity.WARNING
    description = "status closed requires verified_by"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ncr = section(context, "ncr")
        ref = str(ncr.get("id", ""))
        if ncr.get("status") == "closed" and blank(ncr.get("verified_by")):
            return [self.fail(context, "field_required_for_state", ref=ref, state="closed", field="verified_by")]
        return [self.ok(ref)]


class NcrNotOverdueRule(QualityRule):
    """An open NCR is not past its due date."""

    rule_id = "ncr.not_overdue"
    name = "Open NCR is not overdue"
    standard = NCR_RULE_SET
    severity = Severity.WARNING
    description = "an NCR still open after its due_date is overdue"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ncr = section(context, "ncr")
        ref = str(ncr.get("id", ""))
        due = parse_day(ncr.get("due_date"))
        status = str(ncr.get("status", ""))
        if due is not None and status in OPEN_STATUSES and due < today_of(context):
            return [self.fail(context, "overdue", ref=ref, status=status, date=due.isoformat())]
        return [self.ok(ref)]


class NcrCostImpactDescribedRule(QualityRule):
    """A cost impact comes with a description of what it pays for."""

    rule_id = "ncr.cost_impact_described"
    name = "NCR cost impact is described"
    standard = NCR_RULE_SET
    description = "a non-zero cost_impact requires a description"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ncr = section(context, "ncr")
        ref = str(ncr.get("id", ""))
        impact = to_dec(ncr.get("cost_impact"))
        if impact is not None and impact != 0 and blank(ncr.get("description")):
            return [self.fail(context, "field_required_for_state", ref=ref, state="costed", field="description")]
        return [self.ok(ref)]


NCR_RULES = (NcrClosureDocumentedRule, NcrClosureVerifiedRule, NcrNotOverdueRule, NcrCostImpactDescribedRule)


def register_ncr_validation_rules() -> None:
    """Register the NCR rules with the platform rule registry."""
    for rule_class in NCR_RULES:
        rule_registry.register(rule_class(), [NCR_RULE_SET])


__all__ = ["NCR_RULES", "NCR_RULE_SET", "register_ncr_validation_rules"]
