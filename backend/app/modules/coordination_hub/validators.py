# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Coordination hub validation rules (rule set ``coordination_hub``).

Rules run over a plain dict built by the service, one record under one key::

    {"threshold": {"id", "metric", "warn_value", "error_value", "enabled"}}

Defaults seeded by the hub itself are system-created and never gated.
"""

from __future__ import annotations

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import section, to_dec
from app.core.validation.quality_rules import QualityRule

COORDINATION_HUB_RULE_SET = "coordination_hub"

THRESHOLD_FIELDS = ("metric", "warn_value", "error_value", "enabled")

#: Metrics that count things; a fraction of a clash or of a day is meaningless as a limit.
_WHOLE_NUMBER_METRICS = frozenset({"open_clashes_total", "high_severity_clashes", "model_age_days_max"})


class _HubRule(QualityRule):
    standard = COORDINATION_HUB_RULE_SET
    message_section = "coordination_hub"


class ThresholdOrderRule(_HubRule):
    """The warning level sits at or below the error level, or the error tier can never be reached."""

    rule_id = "coordination_hub.threshold_order"
    name = "Warn level is not above the error level"
    description = "warn_value must be less than or equal to error_value"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        t = section(context, "threshold")
        ref = str(t.get("metric", ""))
        warn, error = to_dec(t.get("warn_value")), to_dec(t.get("error_value"))
        if warn is not None and error is not None and warn > error:
            return [self.fail(context, "threshold_inverted", ref=ref, metric=ref, warn=warn, error=error)]
        return [self.ok(ref)]


class ThresholdValueRule(_HubRule):
    """Limits are not negative, and a count limit is a whole number."""

    rule_id = "coordination_hub.threshold_value"
    name = "Threshold values are usable limits"
    description = "values must be at least zero; clash and day counts must be whole numbers"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        t = section(context, "threshold")
        ref = str(t.get("metric", ""))
        out: list[RuleResult] = []
        for field in ("warn_value", "error_value"):
            value = to_dec(t.get(field))
            if value is None:
                continue
            if value < 0 or (ref in _WHOLE_NUMBER_METRICS and value != value.to_integral_value()):
                out.append(self.fail(context, "threshold_value_invalid", ref=ref, metric=ref, value=value))
        return out or [self.ok(ref)]


class ThresholdEnabledRule(_HubRule):
    """Switching a threshold off silences its alarm on the dashboard."""

    rule_id = "coordination_hub.threshold_enabled"
    name = "Threshold alarm is on"
    severity = Severity.WARNING
    description = "a disabled threshold no longer raises warnings or errors"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        t = section(context, "threshold")
        ref = str(t.get("metric", ""))
        if t.get("enabled") is False:
            return [self.fail(context, "threshold_disabled", ref=ref, metric=ref)]
        return [self.ok(ref)]


COORDINATION_HUB_RULES = (ThresholdOrderRule, ThresholdValueRule, ThresholdEnabledRule)


def register_coordination_hub_validation_rules() -> None:
    """Register the coordination hub rules with the platform rule registry."""
    for rule_class in COORDINATION_HUB_RULES:
        rule_registry.register(rule_class(), [COORDINATION_HUB_RULE_SET])


__all__ = [
    "COORDINATION_HUB_RULES",
    "COORDINATION_HUB_RULE_SET",
    "THRESHOLD_FIELDS",
    "register_coordination_hub_validation_rules",
]
