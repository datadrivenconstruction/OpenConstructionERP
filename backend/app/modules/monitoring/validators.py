# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Monitoring validation rules (rule set ``monitoring``).

Rules run over a plain dict context built by the service from each point's
newest reading::

    {"points": [{"code", "level", "displacement_mm", "rate_mm_day", "acknowledged"}]}

MON-001: a point whose newest reading crossed alert (warning), action or alarm
(error). Thresholds come from the project's profile; core has no defaults, and
without a profile the rule stays silent.

SRV-120 warning: the linear trend of the last epochs reaches the next threshold
within ``FORECAST_HORIZON_DAYS`` (``forecast_level``, ``forecast_days``).
"""

from __future__ import annotations

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.messages import translate
from app.core.validation.money_rules import MoneyRule, locale_of, rows

MONITORING_RULE_SET = "monitoring"

_SEVERITY = {"alert": Severity.WARNING, "action": Severity.ERROR, "alarm": Severity.ERROR}


def _num(value: object, places: int) -> str:
    try:
        return f"{float(value):.{places}f}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "-"


class PointLevelRule(MoneyRule):
    """MON-001: no monitoring point sits at alert, action or alarm."""

    rule_id = "MON-001"
    name = "Monitoring levels"
    standard = MONITORING_RULE_SET
    message_section = "monitoring"
    category = RuleCategory.CONSISTENCY
    severity = Severity.WARNING
    description = "Displacement from the baseline and rate per day against the project's threshold profile"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = locale_of(context)
        out = []
        for p in rows(context, "points"):
            level = str(p.get("level") or "ok")
            if level not in _SEVERITY:
                continue
            code = str(p.get("code") or "")
            out.append(
                self.fail(
                    context,
                    "crossed",
                    ref=code,
                    severity=_SEVERITY[level],
                    id=code,
                    d=_num(p.get("displacement_mm"), 1),
                    r=_num(p.get("rate_mm_day"), 2),
                    level=translate(f"monitoring.level.{level}", locale=locale),
                )
            )
        return out or [self.ok()]


#: A forecast further out than this is a trend to watch, not a finding.
FORECAST_HORIZON_DAYS = 30.0


class ForecastRule(MoneyRule):
    """SRV-120: no point is forecast to reach its next threshold within the horizon."""

    rule_id = "SRV-120"
    name = "Monitoring forecast"
    standard = MONITORING_RULE_SET
    message_section = "monitoring"
    category = RuleCategory.QUALITY
    severity = Severity.WARNING
    description = "Linear fit over the last epochs against the next threshold of the profile"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = locale_of(context)
        out = []
        for p in rows(context, "points"):
            level, days = str(p.get("forecast_level") or ""), p.get("forecast_days")
            if level not in _SEVERITY or days is None or float(days) > FORECAST_HORIZON_DAYS:
                continue
            code = str(p.get("code") or "")
            out.append(
                self.fail(
                    context,
                    "forecast",
                    ref=code,
                    id=code,
                    level=translate(f"monitoring.level.{level}", locale=locale),
                    d=_num(days, 1),
                )
            )
        return out or [self.ok()]


MONITORING_RULES = (PointLevelRule, ForecastRule)


def register_monitoring_validation_rules() -> None:
    """Register the monitoring rules with the platform rule registry."""
    for rule_class in MONITORING_RULES:
        rule_registry.register(rule_class(), [MONITORING_RULE_SET])


__all__ = ["MONITORING_RULES", "MONITORING_RULE_SET", "register_monitoring_validation_rules"]


# Registered at import so a process that only loads this module still knows the rule set.
register_monitoring_validation_rules()
