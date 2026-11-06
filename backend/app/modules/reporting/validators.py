# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Reporting validation rules (rule set ``reporting``).

Rules run over a plain dict built by the service. A KPI snapshot is checked as::

    {"kpi": {"id", "snapshot_date", "cpi", "spi", "risk_score_avg", "budget_consumed_pct",
             "schedule_progress_pct", "open_defects", "open_observations", "open_rfis", "open_submittals"}}

and the schedule of a report template as ``{"schedule": {"id", "is_scheduled", "schedule_cron", "recipients"}}``.
Indices and percentages arrive as text, as the snapshot stores them; an absent figure passes.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, blank, section, to_dec
from app.core.validation.quality_rules import latest_local_day, parse_day

REPORTING_RULE_SET = "reporting"

KPI_FIELDS = (
    "snapshot_date",
    "cpi",
    "spi",
    "risk_score_avg",
    "budget_consumed_pct",
    "schedule_progress_pct",
    "open_defects",
    "open_observations",
    "open_rfis",
    "open_submittals",
)
SCHEDULE_FIELDS = ("is_scheduled", "schedule_cron", "recipients")

# Figures are named by their field, which is what the client sent and will correct.
_INDEX_FIELDS = ("cpi", "spi", "risk_score_avg")
_COUNT_FIELDS = ("open_defects", "open_observations", "open_rfis", "open_submittals")
_HUNDRED = Decimal(100)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class _ReportingRule(MoneyRule):
    standard = REPORTING_RULE_SET
    message_section = "reporting"


class SnapshotDateRule(_ReportingRule):
    """A KPI snapshot is dated with a real day that has already begun."""

    rule_id = "reporting.snapshot_date"
    name = "KPI snapshot date is a real, past day"
    description = "snapshot_date must be a calendar date, not in the future"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        kpi = section(context, "kpi")
        ref = str(kpi.get("id", ""))
        raw = kpi.get("snapshot_date")
        if blank(raw):
            return [self.ok(ref)]
        text = str(raw).strip()
        try:
            day = date.fromisoformat(text)
        except ValueError:
            return [self.fail(context, "snapshot_date_invalid", ref=ref, date=text)]
        if day > latest_local_day(context):
            return [self.fail(context, "snapshot_date_future", ref=ref, date=parse_day(text).isoformat())]
        return [self.ok(ref)]


class IndexValuesRule(_ReportingRule):
    """Cost and schedule performance indices and the risk score are numbers of zero or more."""

    rule_id = "reporting.index_values"
    name = "Performance indices are non-negative numbers"
    description = "cpi, spi and risk_score_avg must be numbers of zero or more"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        kpi = section(context, "kpi")
        ref = str(kpi.get("id", ""))
        found = []
        for name in _INDEX_FIELDS:
            raw = kpi.get(name)
            value = to_dec(raw)
            if not blank(raw) and (value is None or value < 0):
                found.append(self.fail(context, "index_invalid", ref=ref, field=name, value=raw))
        return found or [self.ok(ref)]


class PercentValuesRule(_ReportingRule):
    """Progress is a percentage; a budget consumed beyond 100% is flagged, not refused."""

    rule_id = "reporting.percent_values"
    name = "Progress and budget percentages are in range"
    description = "schedule_progress_pct is 0 to 100, budget_consumed_pct is 0 or more (over 100 warns)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        kpi = section(context, "kpi")
        ref = str(kpi.get("id", ""))
        found = []
        progress, spent = kpi.get("schedule_progress_pct"), kpi.get("budget_consumed_pct")
        value = to_dec(progress)
        if not blank(progress) and (value is None or value < 0 or value > _HUNDRED):
            found.append(
                self.fail(context, "percent_out_of_range", ref=ref, field="schedule_progress_pct", value=progress)
            )
        value = to_dec(spent)
        if not blank(spent) and (value is None or value < 0):
            found.append(self.fail(context, "percent_out_of_range", ref=ref, field="budget_consumed_pct", value=spent))
        elif value is not None and value > _HUNDRED:
            found.append(self.fail(context, "budget_overrun", ref=ref, severity=Severity.WARNING, value=spent))
        return found or [self.ok(ref)]


class OpenCountsRule(_ReportingRule):
    """A count of open items cannot be below zero."""

    rule_id = "reporting.open_counts"
    name = "Open-item counts are not negative"
    description = "open defects, observations, RFIs and submittals must be zero or more"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        kpi = section(context, "kpi")
        ref = str(kpi.get("id", ""))
        found = []
        for name in _COUNT_FIELDS:
            value = to_dec(kpi.get(name))
            if value is not None and value < 0:
                found.append(self.fail(context, "count_negative", ref=ref, field=name, value=kpi.get(name)))
        return found or [self.ok(ref)]


class ScheduleRecipientsRule(_ReportingRule):
    """A scheduled report goes to real mailboxes, and to at least one of them."""

    rule_id = "reporting.schedule_recipients"
    name = "Scheduled report has valid recipients"
    description = "an active schedule needs at least one recipient, and email recipients must be well formed"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        schedule = section(context, "schedule")
        ref = str(schedule.get("id", ""))
        recipients = [str(r).strip() for r in (schedule.get("recipients") or []) if not blank(r)]
        found = [
            # A user id has no "@"; only something shaped like an address is held to the address shape.
            self.fail(context, "recipient_invalid", ref=ref, recipient=r)
            for r in recipients
            if "@" in r and not _EMAIL.match(r)
        ]
        if schedule.get("is_scheduled") and not blank(schedule.get("schedule_cron")) and not recipients:
            found.append(self.fail(context, "schedule_without_recipients", ref=ref))
        return found or [self.ok(ref)]


REPORTING_RULES = (
    SnapshotDateRule,
    IndexValuesRule,
    PercentValuesRule,
    OpenCountsRule,
    ScheduleRecipientsRule,
)


def register_reporting_validation_rules() -> None:
    """Register the reporting rules with the platform rule registry."""
    for rule_class in REPORTING_RULES:
        rule_registry.register(rule_class(), [REPORTING_RULE_SET])


__all__ = [
    "KPI_FIELDS",
    "REPORTING_RULES",
    "REPORTING_RULE_SET",
    "SCHEDULE_FIELDS",
    "register_reporting_validation_rules",
]
