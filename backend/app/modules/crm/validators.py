# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CRM opportunity validation rules (rule set ``crm``).

Rules run over a plain dict context built by the caller::

    {"opportunity": {"id", "title", "status", "estimated_value", "currency",
                     "expected_close_date", "owner_user_id"}}

``metadata["today"]`` (ISO date) overrides the reference day for the close-date check.
"""

from __future__ import annotations

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section, to_dec
from app.core.validation.quality_rules import QualityRule, parse_day, today_of

CRM_RULE_SET = "crm"


class _CrmRule(QualityRule):
    standard = CRM_RULE_SET
    message_section = "crm"


class OpportunityCurrencyRule(_CrmRule):
    """A deal with a value states the currency of that value."""

    rule_id = "crm.value_requires_currency"
    name = "Opportunity value has a currency"
    description = "a non-zero estimated_value requires a currency"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        opp = section(context, "opportunity")
        ref = str(opp.get("id", ""))
        value = to_dec(opp.get("estimated_value"))
        if value is not None and value != 0 and blank(opp.get("currency")):
            return [self.fail(context, "currency_required", ref=ref, value=value)]
        return [self.ok(ref)]


class OpportunityCloseDateRule(_CrmRule):
    """The expected close date is a real calendar day (the form only checks its shape)."""

    rule_id = "crm.close_date_valid"
    name = "Opportunity close date is a real date"
    description = "expected_close_date, when given, must be a real date such as 2027-03-31"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        opp = section(context, "opportunity")
        ref = str(opp.get("id", ""))
        value = opp.get("expected_close_date")
        if not blank(value) and parse_day(value) is None:
            return [self.fail(context, "date_invalid", ref=ref, value=value)]
        return [self.ok(ref)]


class OpportunityCloseDateNotPassedRule(_CrmRule):
    """An open deal is not past its expected close date."""

    rule_id = "crm.close_date_not_passed"
    name = "Open opportunity is not past its close date"
    severity = Severity.WARNING
    description = "an open opportunity after its expected_close_date is stale"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        opp = section(context, "opportunity")
        ref = str(opp.get("id", ""))
        due = parse_day(opp.get("expected_close_date"))
        if opp.get("status") == "open" and due is not None and due < today_of(context):
            return [self.fail(context, "close_date_passed", ref=ref, date=due.isoformat())]
        return [self.ok(ref)]


class OpportunityWonHasValueRule(_CrmRule):
    """A won deal carries the value the project budget will start from."""

    rule_id = "crm.won_has_value"
    name = "Won opportunity has a value"
    severity = Severity.WARNING
    description = "status won with a zero estimated_value starts the project with no budget"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        opp = section(context, "opportunity")
        ref = str(opp.get("id", ""))
        value = to_dec(opp.get("estimated_value"))
        if opp.get("status") == "won" and (value is None or value <= 0):
            return [self.fail(context, "won_without_value", ref=ref)]
        return [self.ok(ref)]


class OpportunityOwnerRule(_CrmRule):
    """An open deal has someone accountable for the bid."""

    rule_id = "crm.open_deal_has_owner"
    name = "Open opportunity has an owner"
    severity = Severity.WARNING
    description = "an open opportunity needs an owner_user_id"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        opp = section(context, "opportunity")
        ref = str(opp.get("id", ""))
        if opp.get("status") == "open" and blank(opp.get("owner_user_id")):
            return [self.fail(context, "owner_missing", ref=ref)]
        return [self.ok(ref)]


CRM_RULES = (
    OpportunityCurrencyRule,
    OpportunityCloseDateRule,
    OpportunityCloseDateNotPassedRule,
    OpportunityWonHasValueRule,
    OpportunityOwnerRule,
)


def register_crm_validation_rules() -> None:
    """Register the CRM rules with the platform rule registry."""
    for rule_class in CRM_RULES:
        rule_registry.register(rule_class(), [CRM_RULE_SET])


__all__ = ["CRM_RULES", "CRM_RULE_SET", "register_crm_validation_rules"]
