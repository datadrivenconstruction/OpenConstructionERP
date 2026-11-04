# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Safety incident validation rules (rule set ``safety``).

Rules run over a plain dict built by the service from the merged incident::

    {"incident": {"id", "project_id", "incident_date", "incident_type", "severity",
                  "treatment_type", "days_lost", "root_cause", "reported_to_regulator", "status"}}

A partial record is judged on the fields it has: a rule whose inputs are absent passes.
"""

from __future__ import annotations

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section, to_dec
from app.core.validation.site_rules import SiteRule

SAFETY_RULE_SET = "safety"

_SEVERITY_ORDER = ("minor", "moderate", "major", "severe", "critical")
#: Incident types in which nobody is hurt by definition, so no working days are lost.
_NO_PERSON_TYPES = frozenset({"near_miss", "property_damage", "environmental"})


def _rank(severity: object) -> int:
    return _SEVERITY_ORDER.index(str(severity)) if str(severity) in _SEVERITY_ORDER else -1


class IncidentDateNotFutureRule(SiteRule):
    """An incident cannot have happened tomorrow."""

    rule_id = "safety.incident_date_not_future"
    name = "Incident date is not in the future"
    standard = SAFETY_RULE_SET
    description = "incident_date must not be later than today (one day of timezone slack)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        inc = section(context, "incident")
        ref = str(inc.get("id", ""))
        bad = self.future_date(context, ref, "incident_date", inc.get("incident_date"))
        return [bad] if bad else [self.ok(ref)]


class FatalitySeverityRule(SiteRule):
    """A fatality is never recorded as a minor or moderate incident."""

    rule_id = "safety.fatality_severity"
    name = "Fatality carries a major or higher severity"
    standard = SAFETY_RULE_SET
    description = "treatment_type fatality requires severity major, severe or critical"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        inc = section(context, "incident")
        ref = str(inc.get("id", ""))
        if inc.get("treatment_type") == "fatality" and 0 <= _rank(inc.get("severity")) < _rank("major"):
            return [
                self.site_fail(
                    context,
                    "contradiction",
                    ref=ref,
                    field="severity",
                    value=inc.get("severity"),
                    other_field="treatment_type",
                    other_value="fatality",
                )
            ]
        return [self.ok(ref)]


class LostDaysNeedInjuryRule(SiteRule):
    """Working days are lost by people, so an incident that hurt nobody loses none."""

    rule_id = "safety.lost_days_need_injury"
    name = "Lost days only on incidents that involve a person"
    standard = SAFETY_RULE_SET
    description = "days_lost above zero contradicts near_miss, property_damage and environmental incident types"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        inc = section(context, "incident")
        ref = str(inc.get("id", ""))
        days = to_dec(inc.get("days_lost"))
        if days is not None and days > 0 and inc.get("incident_type") in _NO_PERSON_TYPES:
            return [
                self.site_fail(
                    context,
                    "contradiction",
                    ref=ref,
                    field="days_lost",
                    value=days,
                    other_field="incident_type",
                    other_value=inc.get("incident_type"),
                )
            ]
        return [self.ok(ref)]


class RegulatorReportRule(SiteRule):
    """Serious injuries and fatalities are notifiable; say whether the regulator was told."""

    rule_id = "safety.regulator_report_expected"
    name = "Serious incident reported to the regulator"
    standard = SAFETY_RULE_SET
    severity = Severity.WARNING
    description = "Fatality, hospital treatment or critical severity should have reported_to_regulator set"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        inc = section(context, "incident")
        ref = str(inc.get("id", ""))
        if inc.get("reported_to_regulator") in (True, 1):
            return [self.ok(ref)]
        for field in ("treatment_type", "severity"):
            if inc.get(field) in {"treatment_type": ("fatality", "hospital"), "severity": ("critical",)}[field]:
                return [
                    self.site_fail(
                        context,
                        "required_when",
                        ref=ref,
                        field="reported_to_regulator",
                        other_field=field,
                        other_value=inc.get(field),
                    )
                ]
        return [self.ok(ref)]


class ClosedNeedsRootCauseRule(SiteRule):
    """A serious incident is not closed until its root cause is on record."""

    rule_id = "safety.closed_needs_root_cause"
    name = "Closed serious incident has a root cause"
    standard = SAFETY_RULE_SET
    severity = Severity.WARNING
    description = "status closed with severity major or higher requires root_cause"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        inc = section(context, "incident")
        ref = str(inc.get("id", ""))
        if (
            inc.get("status") == "closed"
            and _rank(inc.get("severity")) >= _rank("major")
            and blank(inc.get("root_cause"))
        ):
            return [
                self.site_fail(
                    context,
                    "required_when",
                    ref=ref,
                    field="root_cause",
                    other_field="status",
                    other_value="closed",
                )
            ]
        return [self.ok(ref)]


SAFETY_RULES = (
    IncidentDateNotFutureRule,
    FatalitySeverityRule,
    LostDaysNeedInjuryRule,
    RegulatorReportRule,
    ClosedNeedsRootCauseRule,
)


def register_safety_validation_rules() -> None:
    """Register the safety incident rules with the platform rule registry."""
    for rule_class in SAFETY_RULES:
        rule_registry.register(rule_class(), [SAFETY_RULE_SET])


__all__ = ["SAFETY_RULES", "SAFETY_RULE_SET", "register_safety_validation_rules"]
