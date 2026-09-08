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


# ── Registration ────────────────────────────────────────────────────────────

_SCHEDULE_RULES: tuple[ValidationRule, ...] = (DurationCountedOnProjectWeek(),)


def register_schedule_rules() -> None:
    """Register the schedule module's rules with the core registry.

    Idempotent, since the registry overwrites by rule id. Called at import time
    below and again from the module's ``on_startup`` hook, because the platform
    has two ways of bringing a module up and a rule that takes only one of them
    is dormant in the other deployment.
    """
    for rule in _SCHEDULE_RULES:
        rule_registry.register(rule, [SCHEDULE_RULE_SET])
    logger.debug("Registered %d schedule validation rules", len(_SCHEDULE_RULES))


register_schedule_rules()
