# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Asset register validation rules (rule set ``assets``).

Rules run over a plain dict built by the service, one record under one key::

    {"service": {"id", "date", "cost", "kind"}}

The register itself is derived from BIM elements; the one thing a user writes to it is a service
log entry, and that is what the rules judge. Health and warranty figures are computed from these
entries, so a date that is not a date or a cost that is not a number would silently skew them.
"""

from __future__ import annotations

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section, to_dec
from app.core.validation.quality_rules import QualityRule, latest_local_day, parse_day

ASSETS_RULE_SET = "assets"

SERVICE_FIELDS = ("date", "cost", "kind")


class _AssetRule(QualityRule):
    standard = ASSETS_RULE_SET
    message_section = "assets"


class ServiceDateRule(_AssetRule):
    """The service date is a real calendar day."""

    rule_id = "assets.service_date_valid"
    name = "Service date is a real date"
    description = "date must be a real date such as 2026-11-04"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        entry = section(context, "service")
        ref = str(entry.get("id", ""))
        raw = entry.get("date")
        if not blank(raw) and parse_day(raw) is None:
            return [self.fail(context, "service_date_invalid", ref=ref, value=str(raw).strip())]
        return [self.ok(ref)]


class ServiceCostRule(_AssetRule):
    """The cost of a service is a number that is not negative."""

    rule_id = "assets.service_cost_valid"
    name = "Service cost is a non-negative number"
    description = "cost, when given, must be a number of zero or more"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        entry = section(context, "service")
        ref = str(entry.get("id", ""))
        raw = entry.get("cost")
        if not blank(raw):
            value = to_dec(raw)
            if value is None or value < 0:
                return [self.fail(context, "service_cost_invalid", ref=ref, value=str(raw).strip())]
        return [self.ok(ref)]


class ServiceDateNotFutureRule(_AssetRule):
    """A logged service has already been carried out."""

    rule_id = "assets.service_not_in_future"
    name = "Service date is not in the future"
    severity = Severity.WARNING
    description = "a service log entry should not be dated after today"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        entry = section(context, "service")
        ref = str(entry.get("id", ""))
        day = parse_day(entry.get("date"))
        if day is not None and day > latest_local_day(context):
            return [self.fail(context, "service_in_future", ref=ref, date=day.isoformat())]
        return [self.ok(ref)]


ASSETS_RULES = (
    ServiceDateRule,
    ServiceCostRule,
    ServiceDateNotFutureRule,
)


def register_assets_validation_rules() -> None:
    """Register the asset register rules with the platform rule registry."""
    for rule_class in ASSETS_RULES:
        rule_registry.register(rule_class(), [ASSETS_RULE_SET])


__all__ = ["ASSETS_RULES", "ASSETS_RULE_SET", "SERVICE_FIELDS", "register_assets_validation_rules"]
