# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Field report validation rules (rule set ``fieldreports``).

Rules run over a plain dict context built by the caller::

    {
        "report": {"id", "status", "report_date", "work_performed", "notes", "delays", "delay_hours",
                   "workforce": [{"trade", "count", "hours"}]},
        "workforce_log": [{"id", "item", "count", "hours"}],
        "equipment_log": [{"id", "item", "hours_operational", "hours_standby", "hours_breakdown"}],
    }

``workforce[].hours`` is per person; ``workforce_log[].hours`` is the crew total (regular plus
overtime). ``metadata["today"]`` (ISO date) overrides the reference day.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, rows, section, to_dec
from app.core.validation.quality_rules import QualityRule, parse_day, today_of

FIELDREPORTS_RULE_SET = "fieldreports"

#: A person or a machine cannot log more than a calendar day in one day.
HOURS_PER_DAY = Decimal("24")
#: A site in the next time zone writes the following date for a few hours.
DATE_GRACE = timedelta(days=1)


def _locked(report: dict) -> bool:
    """True once the report has left draft: gaps are errors there, hints while drafting."""
    return str(report.get("status") or "draft") != "draft"


class _ReportRule(QualityRule):
    message_section = "site_records"
    standard = FIELDREPORTS_RULE_SET


class ReportHasContentRule(_ReportRule):
    """A submitted report records something: work, delays, notes or a crew."""

    rule_id = "fieldreports.content_recorded"
    name = "Submitted report records the day"
    description = "A submitted or approved report needs work performed, delays, notes or a workforce"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        report = section(context, "report")
        ref = str(report.get("id", ""))
        if not _locked(report):
            return [self.ok(ref)]
        has_crew = bool(report.get("workforce")) or bool(rows(context, "workforce_log"))
        if any(not blank(report.get(k)) for k in ("work_performed", "delays", "notes")) or has_crew:
            return [self.ok(ref)]
        return [self.fail(context, "nothing_recorded", ref=ref, state=report.get("status"))]


class DelayExplainedRule(_ReportRule):
    """Delay hours come with a reason, or the claim for time has no basis."""

    rule_id = "fieldreports.delay_explained"
    name = "Delay hours have a stated cause"
    description = "delay_hours above zero need a delays description"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        report = section(context, "report")
        ref = str(report.get("id", ""))
        hours = to_dec(report.get("delay_hours"))
        if hours is not None and hours > 0 and blank(report.get("delays")):
            severity = Severity.ERROR if _locked(report) else Severity.WARNING
            return [self.fail(context, "delay_unexplained", ref=ref, severity=severity, hours=hours)]
        return [self.ok(ref)]


class ReportDateNotFutureRule(_ReportRule):
    """A report records a day that has happened."""

    rule_id = "fieldreports.date_not_future"
    name = "Report date is not in the future"
    description = "report_date more than a day ahead is a typo or a pre-filled report"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        report = section(context, "report")
        ref = str(report.get("id", ""))
        day = parse_day(report.get("report_date"))
        if day is not None and day > today_of(context) + DATE_GRACE:
            severity = Severity.ERROR if _locked(report) else Severity.WARNING
            return [self.fail(context, "date_in_future", ref=ref, severity=severity, date=day.isoformat())]
        return [self.ok(ref)]


class WorkforceHoursPlausibleRule(_ReportRule):
    """No person works more than 24 hours in a day."""

    rule_id = "fieldreports.workforce_hours_plausible"
    name = "Workforce hours per person fit in a day"
    description = "Hours per person above 24 are a unit slip or a crew total typed as per-person hours"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        report = section(context, "report")
        ref = str(report.get("id", ""))
        out: list[RuleResult] = []
        for entry in report.get("workforce") or []:
            if not isinstance(entry, dict):
                continue
            per_person = to_dec(entry.get("hours"))
            if per_person is not None and per_person > HOURS_PER_DAY:
                out.append(
                    self.fail(
                        context, "hours_exceed_day", ref=ref, item=entry.get("trade") or "-", hours=round(per_person, 1)
                    )
                )
        for entry in rows(context, "workforce_log"):
            count, total = to_dec(entry.get("count")), to_dec(entry.get("hours"))
            if count and total is not None and total / count > HOURS_PER_DAY:
                out.append(
                    self.fail(
                        context,
                        "hours_exceed_day",
                        ref=str(entry.get("id", ref)),
                        item=entry.get("item") or "-",
                        hours=round(total / count, 1),
                    )
                )
        return out or [self.ok(ref)]


class EquipmentHoursPlausibleRule(_ReportRule):
    """Operating, standby and breakdown hours of one machine fit in a day."""

    rule_id = "fieldreports.equipment_hours_plausible"
    name = "Equipment hours fit in a day"
    description = "hours_operational + hours_standby + hours_breakdown must not exceed 24 per machine"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for entry in rows(context, "equipment_log"):
            parts = [
                to_dec(entry.get(k)) or Decimal("0") for k in ("hours_operational", "hours_standby", "hours_breakdown")
            ]
            total = sum(parts, Decimal("0"))
            if total > HOURS_PER_DAY:
                out.append(
                    self.fail(
                        context,
                        "hours_exceed_day",
                        ref=str(entry.get("id", "")),
                        item=entry.get("item") or "-",
                        hours=round(total, 1),
                    )
                )
        return out or [self.ok(str(section(context, "report").get("id", "")))]


FIELDREPORTS_RULES = (
    ReportHasContentRule,
    DelayExplainedRule,
    ReportDateNotFutureRule,
    WorkforceHoursPlausibleRule,
    EquipmentHoursPlausibleRule,
)


def register_fieldreports_validation_rules() -> None:
    """Register the field report rules with the platform rule registry."""
    for rule_class in FIELDREPORTS_RULES:
        rule_registry.register(rule_class(), [FIELDREPORTS_RULE_SET])


__all__ = ["FIELDREPORTS_RULES", "FIELDREPORTS_RULE_SET", "register_fieldreports_validation_rules"]
