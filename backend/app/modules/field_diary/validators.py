# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Field diary validation rules (rule set ``field_diary``).

Rules run over a plain dict context built by the caller::

    {"entry": {"id", "entry_date", "status", "headcount",
               "activities": [{"id", "activity_type", "description", "hours", "started_at", "ended_at"}]}}

``metadata["today"]`` (ISO date) overrides the reference day. The offline-capture age check
lives in its own set (``field_diary_capture``) and is not repeated here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section, to_dec
from app.core.validation.quality_rules import QualityRule, parse_day, today_of

FIELD_DIARY_RULE_SET = "field_diary"

HOURS_PER_DAY = Decimal("24")
#: Work hours are labour; a visit or an incident carries no payable time.
LABOUR_TYPES = frozenset({"work", "inspection"})
#: A phone in the next time zone writes the following date for a few hours.
DATE_GRACE = timedelta(days=1)


def _activities(context: ValidationContext) -> list[dict[str, Any]]:
    value = section(context, "entry").get("activities")
    return [a for a in value if isinstance(a, dict)] if isinstance(value, list) else []


def _instant(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


class _DiaryRule(QualityRule):
    message_section = "site_records"
    standard = FIELD_DIARY_RULE_SET


class EntryDateNotFutureRule(_DiaryRule):
    """A diary entry records a day that has happened."""

    rule_id = "field_diary.entry_date_not_future"
    name = "Diary entry date is not in the future"
    description = "entry_date more than a day ahead is a typo, not a record of work"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        entry = section(context, "entry")
        ref = str(entry.get("id", ""))
        day = parse_day(entry.get("entry_date"))
        if day is not None and day > today_of(context) + DATE_GRACE:
            return [self.fail(context, "date_in_future", ref=ref, date=day.isoformat())]
        return [self.ok(ref)]


class WorkHoursMatchCrewRule(_DiaryRule):
    """Logged work hours fit the crew stated for the day."""

    rule_id = "field_diary.work_hours_match_crew"
    name = "Work hours fit the stated crew"
    description = "Work hours per person cannot exceed 24; work hours with no crew count are suspect"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        entry = section(context, "entry")
        ref = str(entry.get("id", ""))
        total = Decimal("0")
        for act in _activities(context):
            if act.get("activity_type") in LABOUR_TYPES:
                total += to_dec(act.get("hours")) or Decimal("0")
        if total <= 0:
            return [self.ok(ref)]
        crew = to_dec(entry.get("headcount")) or Decimal("0")
        if crew <= 0:
            return [self.fail(context, "hours_without_crew", ref=ref, severity=Severity.WARNING, hours=round(total, 1))]
        if total / crew > HOURS_PER_DAY:
            item = str(entry.get("entry_date") or "-")
            return [self.fail(context, "hours_exceed_day", ref=ref, item=item, hours=round(total / crew, 1))]
        return [self.ok(ref)]


class IncidentDescribedRule(_DiaryRule):
    """An incident is described; a delay should say why."""

    rule_id = "field_diary.incident_described"
    name = "Incidents and delays are described"
    description = "An incident without a description is an error; a delay without one is a warning"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = str(section(context, "entry").get("id", ""))
        out: list[RuleResult] = []
        for act in _activities(context):
            if not blank(act.get("description")):
                continue
            kind, aref = act.get("activity_type"), str(act.get("id") or ref)
            if kind == "incident":
                out.append(self.fail(context, "incident_undescribed", ref=aref))
            elif kind == "delay":
                hours = to_dec(act.get("hours")) or Decimal("0")
                out.append(self.fail(context, "delay_undescribed", ref=aref, severity=Severity.WARNING, hours=hours))
        return out or [self.ok(ref)]


class ActivityTimesConsistentRule(_DiaryRule):
    """An activity ends after it starts and its hours fit the window."""

    rule_id = "field_diary.activity_times_consistent"
    name = "Activity times are ordered and match its hours"
    description = "ended_at must come after started_at; logged hours should fit between them"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = str(section(context, "entry").get("id", ""))
        out: list[RuleResult] = []
        for act in _activities(context):
            start, end = _instant(act.get("started_at")), _instant(act.get("ended_at"))
            if start is None or end is None:
                continue
            aref = str(act.get("id") or ref)
            if end <= start:
                out.append(
                    self.fail(context, "dates_not_ordered", ref=aref, start=start.isoformat(), end=end.isoformat())
                )
                continue
            span = Decimal(str((end - start).total_seconds())) / Decimal("3600")
            hours = to_dec(act.get("hours"))
            if hours is not None and hours > span + Decimal("0.01"):
                out.append(
                    self.fail(
                        context,
                        "hours_exceed_window",
                        ref=aref,
                        severity=Severity.WARNING,
                        hours=round(hours, 1),
                        span=round(span, 1),
                    )
                )
        return out or [self.ok(ref)]


class CrewHasRecordRule(_DiaryRule):
    """A submitted day with a crew on site records what the crew did."""

    rule_id = "field_diary.crew_has_record"
    name = "Crew on site has work or delay recorded"
    severity = Severity.WARNING
    description = "headcount above zero with no work, inspection or delay activity on a submitted entry"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        entry = section(context, "entry")
        ref = str(entry.get("id", ""))
        if str(entry.get("status") or "draft") == "draft":
            return [self.ok(ref)]
        crew = to_dec(entry.get("headcount")) or Decimal("0")
        recorded = any(a.get("activity_type") in {*LABOUR_TYPES, "delay"} for a in _activities(context))
        if crew > 0 and not recorded:
            return [self.fail(context, "crew_without_record", ref=ref, headcount=crew)]
        return [self.ok(ref)]


FIELD_DIARY_RULES = (
    EntryDateNotFutureRule,
    WorkHoursMatchCrewRule,
    IncidentDescribedRule,
    ActivityTimesConsistentRule,
    CrewHasRecordRule,
)


def register_field_diary_validation_rules() -> None:
    """Register the field diary rules with the platform rule registry."""
    for rule_class in FIELD_DIARY_RULES:
        rule_registry.register(rule_class(), [FIELD_DIARY_RULE_SET])


__all__ = ["FIELD_DIARY_RULES", "FIELD_DIARY_RULE_SET", "register_field_diary_validation_rules"]
