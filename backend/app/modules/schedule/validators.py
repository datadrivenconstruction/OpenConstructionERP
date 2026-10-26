# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules the schedule module owns.

One rule so far, and it exists because of one defect. ``compute_duration`` took
a region from March 2026 and no caller passed one until September, so every
duration the module recounted on create, on update, on the Gantt fallback and
on the two schedule imports was counted on the DEFAULT Monday-to-Friday week,
while BOQ schedule generation in the same module drew its dates on the
project's regional week. The fix threads the project's region through one
helper, ``ScheduleService.resolve_project_region``, and rewrites nothing that
was already stored: a row keeps the count it was given until its dates are next
saved. This rule is how those rows are found.

* ``schedule_quality.duration_on_project_week`` - an activity whose stored
  working-day duration is the Monday-to-Friday count of its own dates while the
  project's week counts them differently. It fires only where the two weeks
  disagree, so a German or American schedule can never be flagged by it, and
  only where the stored number is exactly the old count, so an explicit
  duration that matches neither week is not its concern.

The rule is a WARNING and rejects nothing. It is registered under the
``schedule_quality`` set, beside the DCMA-style network checks in
:mod:`app.core.validation.rules`, so it runs whenever that pack is requested and
reads the same ``{"activities": [...]}`` payload. The project's region is read
from ``ValidationContext.region``, the field the engine fills from its
``region`` argument, with ``metadata["region"]`` and ``data["project_region"]``
accepted for callers that carry it there. A payload that names no region is
judged on the DEFAULT week, where the rule cannot fire and says nothing.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.core.validation.messages import DEFAULT_LOCALE, translate
from app.modules.schedule.service import compute_duration, get_work_calendar

logger = logging.getLogger(__name__)

#: The rule set the schedule rules register under: the programme quality pack
#: in the core rules, so one request for it runs the network checks and this
#: rule together.
SCHEDULE_RULE_SET = "schedule_quality"

#: Activity types that carry no duration by design, so there is no count to
#: judge. The same family the core pack exempts from its missing-duration check.
_ZERO_DURATION_TYPES: frozenset[str] = frozenset(
    {"milestone", "start_milestone", "finish_milestone", "hammock", "wbs", "summary", "level_of_effort"},
)


def _activities(context: ValidationContext) -> list[dict[str, Any]]:
    """The activity rows of the payload, or nothing when it carries none."""
    data = context.data
    if isinstance(data, dict):
        rows = data.get("activities")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        return []
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _region(context: ValidationContext) -> str | None:
    """The project's region, wherever the caller carried it.

    ``ValidationContext.region`` is the engine's own field and wins. The
    metadata and payload spellings are accepted so a caller that already
    threads the region alongside the locale, or inside the rows it validates,
    does not have to learn a third place to put it.
    """
    region = getattr(context, "region", None)
    if isinstance(region, str) and region.strip():
        return region
    metadata = getattr(context, "metadata", None)
    if isinstance(metadata, dict):
        region = metadata.get("region")
        if isinstance(region, str) and region.strip():
            return region
    data = context.data
    if isinstance(data, dict):
        region = data.get("project_region")
        if isinstance(region, str) and region.strip():
            return region
    return None


def _locale(context: ValidationContext) -> str:
    """The caller's locale, defaulting to English exactly like the core rules."""
    metadata = getattr(context, "metadata", None)
    if isinstance(metadata, dict):
        locale = metadata.get("locale")
        if isinstance(locale, str) and locale.strip():
            return locale.strip()
    return DEFAULT_LOCALE


def _stored_duration(activity: dict[str, Any]) -> int | None:
    """The stored working-day count as an integer, or None when it is not one."""
    value = activity.get("duration_days")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _label(activity: dict[str, Any]) -> str:
    """The name a planner knows the row by, for the message."""
    for key in ("activity_code", "wbs_code", "name", "id"):
        value = activity.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return "?"


class DurationCountedOnProjectWeek(ValidationRule):
    """Flags a duration that is the Monday-to-Friday count of dates the project counts differently.

    For every task with dates and an integer duration, the dates are counted on
    the project's working week and on the DEFAULT week. A duration equal to the
    project's count passes. A duration equal to the DEFAULT count, where that
    differs, is the old recompute and fails. A duration equal to neither was
    entered on purpose, or carries another unit, and is not judged here. When
    the project's week is the DEFAULT week the two counts can never differ, so
    the rule returns nothing rather than a pass it did not earn.
    """

    rule_id = "schedule_quality.duration_on_project_week"
    name = "Duration counted on the project's working week"
    standard = SCHEDULE_RULE_SET
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "Flags an activity whose stored working-day duration was counted on the default "
        "Monday-to-Friday week while the project's regional week counts its dates differently."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        region = _region(context)
        calendar = get_work_calendar(region)
        if calendar["work_days"] == get_work_calendar(None)["work_days"]:
            return []

        locale = _locale(context)
        results: list[RuleResult] = []
        for activity in _activities(context):
            if str(activity.get("activity_type") or "").strip().lower() in _ZERO_DURATION_TYPES:
                continue
            stored = _stored_duration(activity)
            start, end = activity.get("start_date"), activity.get("end_date")
            if stored is None or not start or not end:
                continue
            start_iso, end_iso = str(start)[:10], str(end)[:10]
            on_project_week = compute_duration(start_iso, end_iso, region)
            on_default_week = compute_duration(start_iso, end_iso, None)
            if on_project_week == 0 and on_default_week == 0:
                continue
            if stored == on_project_week:
                passed = True
            elif stored == on_default_week:
                passed = False
            else:
                continue

            element_ref = str(activity.get("id")) if activity.get("id") else None
            if passed:
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=self.severity,
                        category=self.category,
                        passed=True,
                        message=translate("common.ok", locale=locale),
                        element_ref=element_ref,
                    )
                )
                continue
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=translate(
                        f"{self.rule_id}.fail",
                        locale=locale,
                        activity=_label(activity),
                        stored=stored,
                        start=start_iso,
                        end=end_iso,
                        calendar=calendar["label"],
                        expected=on_project_week,
                    ),
                    element_ref=element_ref,
                    details={
                        "stored_duration_days": stored,
                        "on_project_week": on_project_week,
                        "on_default_week": on_default_week,
                        "calendar": calendar["label"],
                    },
                    suggestion=translate(f"{self.rule_id}.suggestion", locale=locale),
                )
            )
        return results


class DatesMatchImportSource(ValidationRule):
    """Flags an imported activity whose dates moved away from its source file.

    Reads ``source_dates`` (``{"start", "finish"}``) from each activity row, or
    from its ``metadata``, and fails where the current finish differs from the
    source finish. Rows without source dates, and a payload whose
    ``import_source_status`` is ``accepted``, are not judged.
    """

    rule_id = "schedule_quality.dates_match_source"
    name = "Dates match the imported source"
    standard = SCHEDULE_RULE_SET
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags an imported activity whose recalculated finish differs from the finish in its source file."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data
        if isinstance(data, dict) and data.get("import_source_status") == "accepted":
            return []
        from app.modules.schedule.import_source import deviation_days

        locale = _locale(context)
        results: list[RuleResult] = []
        for activity in _activities(context):
            source = activity.get("source_dates")
            if not isinstance(source, dict):
                meta = activity.get("metadata")
                source = meta.get("source_dates") if isinstance(meta, dict) else None
            if not isinstance(source, dict) or not source.get("finish"):
                continue
            days = deviation_days(source.get("finish"), activity.get("end_date"))
            if days is None:
                continue
            passed = days == 0
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message=translate("common.ok", locale=locale)
                    if passed
                    else translate(
                        f"{self.rule_id}.fail",
                        locale=locale,
                        activity=_label(activity),
                        days=days,
                        source=str(source.get("finish"))[:10],
                    ),
                    element_ref=str(activity.get("id")) if activity.get("id") else None,
                    details={"finish_deviation_days": days},
                    suggestion=None if passed else translate(f"{self.rule_id}.suggestion", locale=locale),
                )
            )
        return results


# ── Progress sheet rules ────────────────────────────────────────────────────
# An uploaded progress sheet is validated through the engine before anything
# is applied. Payload ``{"rows": [...]}``, one dict per sheet row (built in
# ``progress_sheet_service``); a failing row is one result whose
# ``element_ref`` is the sheet row number and ``details["code"]`` the problem.

PROGRESS_SHEET_RULE_SET = "schedule_progress_sheet"


def _sheet_rows(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data
    rows = data.get("rows") if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


class _SheetRule(ValidationRule):
    standard = PROGRESS_SHEET_RULE_SET
    category = RuleCategory.CONSISTENCY

    def _fail(self, context: ValidationContext, row: dict[str, Any], code: str, **params: object) -> RuleResult:
        locale = _locale(context)
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=False,
            message=translate(f"{self.rule_id}.{code}", locale=locale, row=row.get("row_number"), **params),
            element_ref=str(row.get("row_number")),
            details={"code": code, "row_number": row.get("row_number"), **{k: str(v) for k, v in params.items()}},
            suggestion=translate(f"{self.rule_id}.suggestion", locale=locale),
        )

    def _pass(self, context: ValidationContext, row: dict[str, Any]) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=True,
            message=translate("common.ok", locale=_locale(context)),
            element_ref=str(row.get("row_number")),
        )

    def check(self, context: ValidationContext, row: dict[str, Any]) -> list[RuleResult]:
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for row in _sheet_rows(context):
            found = self.check(context, row)
            results.extend(found or [self._pass(context, row)])
        return results


class ProgressSheetKnownActivity(_SheetRule):
    """Every row names one activity of the schedule, once."""

    rule_id = "schedule_progress_sheet.known_activity"
    name = "Row names an activity of the schedule"
    severity = Severity.ERROR
    description = "A progress sheet row whose activity is not in the schedule, or that repeats another row."

    def check(self, context: ValidationContext, row: dict[str, Any]) -> list[RuleResult]:
        if not row.get("activity_id"):
            return [self._fail(context, row, "fail", ref=row.get("activity_ref") or row.get("row_key") or "?")]
        if row.get("duplicate"):
            return [self._fail(context, row, "duplicate", ref=row.get("activity_ref") or "?")]
        return []


class ProgressSheetValuesInRange(_SheetRule):
    """Percent 0..100, real dates, a whole non-negative remaining duration."""

    rule_id = "schedule_progress_sheet.values_in_range"
    name = "Progress values are in range"
    severity = Severity.ERROR
    description = "Percent complete outside 0-100, a date that is not a date, or a negative remaining duration."

    def check(self, context: ValidationContext, row: dict[str, Any]) -> list[RuleResult]:
        out = [self._fail(context, row, code) for code in row.get("parse_errors") or []]
        pct = row.get("percent_complete")
        if isinstance(pct, (int, float)) and not 0.0 <= float(pct) <= 100.0:
            out.append(self._fail(context, row, "percent_out_of_range", value=pct))
        remaining = row.get("remaining_duration")
        if isinstance(remaining, int) and remaining < 0:
            out.append(self._fail(context, row, "remaining_negative", value=remaining))
        return out


class ProgressSheetDateLogic(_SheetRule):
    """Actual dates in order, not after the status date, a finish only at 100%."""

    rule_id = "schedule_progress_sheet.date_logic"
    name = "Actual dates are consistent"
    severity = Severity.ERROR
    description = "An actual finish before the start, an actual date after the status date, or a finish below 100%."

    def check(self, context: ValidationContext, row: dict[str, Any]) -> list[RuleResult]:
        out: list[RuleResult] = []
        start = row.get("actual_start") or row.get("recorded_actual_start")
        finish = row.get("actual_finish")
        status_date = row.get("status_date")
        if start and finish and str(finish) < str(start):
            out.append(self._fail(context, row, "finish_before_start", start=start, finish=finish))
        if finish and not start:
            out.append(self._fail(context, row, "finish_without_start", finish=finish))
        for value in (row.get("actual_start"), finish):
            if value and status_date and str(value) > str(status_date):
                out.append(self._fail(context, row, "after_status_date", value=value, status_date=status_date))
        pct = row.get("percent_complete")
        if pct is None:
            pct = row.get("current_percent")
        if finish and isinstance(pct, (int, float)) and float(pct) < 100.0:
            out.append(self._fail(context, row, "finish_needs_complete", percent=round(float(pct), 1)))
        return out


class ProgressSheetUnchangedSinceExport(_SheetRule):
    """The activity was not changed in the app after the sheet was exported."""

    rule_id = "schedule_progress_sheet.unchanged_since_export"
    name = "Activity unchanged since export"
    severity = Severity.WARNING
    description = "The activity's dates or progress were changed in the app after the sheet was exported."

    def check(self, context: ValidationContext, row: dict[str, Any]) -> list[RuleResult]:
        if row.get("activity_id") and row.get("stale"):
            return [self._fail(context, row, "fail", activity=row.get("activity_ref") or row.get("name") or "?")]
        return []


class ProgressSheetPlausibility(_SheetRule):
    """Progress that goes backwards or lacks the dates that should come with it."""

    rule_id = "schedule_progress_sheet.plausibility"
    name = "Progress is plausible"
    severity = Severity.WARNING
    description = "Progress that decreases, 100% without an actual finish, or progress without an actual start."

    def check(self, context: ValidationContext, row: dict[str, Any]) -> list[RuleResult]:
        out: list[RuleResult] = []
        pct = row.get("percent_complete")
        current = row.get("current_percent")
        if not isinstance(pct, (int, float)) or not row.get("activity_id"):
            return out
        if isinstance(current, (int, float)) and float(pct) < float(current):
            out.append(
                self._fail(context, row, "progress_decreased", old=round(float(current), 1), new=round(float(pct), 1))
            )
        if float(pct) >= 100.0 and not row.get("actual_finish") and not row.get("recorded_actual_finish"):
            out.append(self._fail(context, row, "complete_without_finish"))
        if float(pct) > 0.0 and not row.get("actual_start") and not row.get("recorded_actual_start"):
            out.append(self._fail(context, row, "started_without_start"))
        return out


# ── Registration ────────────────────────────────────────────────────────────

_SCHEDULE_RULES: tuple[ValidationRule, ...] = (DurationCountedOnProjectWeek(), DatesMatchImportSource())
_PROGRESS_SHEET_RULES: tuple[ValidationRule, ...] = (
    ProgressSheetKnownActivity(),
    ProgressSheetValuesInRange(),
    ProgressSheetDateLogic(),
    ProgressSheetUnchangedSinceExport(),
    ProgressSheetPlausibility(),
)


def register_schedule_rules() -> None:
    """Register the schedule module's rules with the core registry.

    Idempotent, since the registry overwrites by rule id. Called at import time
    below and again from the module's ``on_startup`` hook, because the platform
    has two ways of bringing a module up and a rule that takes only one of them
    is dormant in the other deployment.
    """
    for rule in _SCHEDULE_RULES:
        rule_registry.register(rule, [SCHEDULE_RULE_SET])
    for rule in _PROGRESS_SHEET_RULES:
        rule_registry.register(rule, [PROGRESS_SHEET_RULE_SET])
    logger.debug("Registered %d schedule validation rules", len(_SCHEDULE_RULES) + len(_PROGRESS_SHEET_RULES))


register_schedule_rules()
