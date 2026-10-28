# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Resource-assignment validation rules.

An assignment can now name the schedule activity it staffs. That link is only
worth having if something reads it and objects, so these rules are that reader:

* ``resources.assignment_outside_activity_window`` - WARNING. The assignment
  names an activity but is booked partly or wholly outside that activity's own
  dates, so the histogram loads a bar the work does not sit on.
* ``resources.assignment_target_ambiguous`` - WARNING. The assignment names
  both a schedule activity and a to-do task. Those are two different objects
  in two different registers; an assignment that means both means neither.
* ``resources.assignment_activity_missing`` - WARNING. The assignment names an
  activity the caller looked for and did not find, which is what a deleted
  activity id looks like from here. Not a cross-project one: the lookup is not
  project-scoped, so an activity in another project resolves and this rule
  stays quiet about it.

The rules take a plain dict rather than ORM instances so they stay unit
testable without a session. The caller assembles it, because a rule has no
database of its own:

    {
        "assignment": Assignment,
        "activity": Activity | None,
        "activity_lookup_available": bool,
    }

``activity`` is None both when the assignment names no activity and when it
names one that could not be loaded. Those two cases are not the same and the
rules tell them apart by reading ``assignment.activity_id``, never by the
absence of the activity alone.

``activity_lookup_available`` separates a third case that otherwise hides
inside the second: on an install without the schedule module there is nothing
to look the activity up in, so every assignment carrying an ``activity_id``
would be accused of staffing a deleted bar. False means the caller could not
ask the question, and a rule that needs the answer stays quiet. It defaults to
True when absent, so a payload written before this key existed keeps its
meaning.

Registration follows the module convention: :func:`register_resources_rules`
is idempotent, is called from the module's ``on_startup`` hook, and is called
again by the tests because no test process runs application startup.
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import datetime
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

logger = logging.getLogger(__name__)

# The rule set every resources rule registers under.
RESOURCES_RULE_SET = "resources"


def _payload(context: ValidationContext) -> dict[str, Any]:
    """Read the rule payload out of the context, tolerating an empty run."""
    data = context.data
    return data if isinstance(data, dict) else {}


def _ok(rule: ValidationRule, message: str) -> RuleResult:
    """A single passing result, so a clean run still counts as checked."""
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=True,
        message=message,
    )


def _as_date(value: Any) -> _date | None:
    """Coerce a schedule date to a ``date``, or None when it is unreadable.

    Schedule activities store their dates as ISO strings rather than as date
    columns, and the strings in the wild carry a time part about as often as
    not. Anything that does not parse is treated as absent: a rule must not
    invent a window out of a value it could not read.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, _date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return _date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _activity_label(activity: Any) -> str:
    """Best-effort human name for an activity, for the finding message."""
    for attr in ("activity_code", "wbs_code", "name"):
        value = getattr(activity, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(getattr(activity, "id", "?"))


class AssignmentOutsideActivityWindow(ValidationRule):
    """A booking sits outside the dates of the activity it claims to staff."""

    rule_id = "resources.assignment_outside_activity_window"
    name = "Assignment outside its activity window"
    standard = "resources"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "An assignment that names a schedule activity is booked outside that activity's own dates."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        assignment = payload.get("assignment")
        activity = payload.get("activity")
        if assignment is None:
            return [_ok(self, "No assignment supplied; nothing to check.")]
        if assignment.activity_id is None or activity is None:
            return [_ok(self, "The assignment names no resolvable schedule activity.")]

        window_start = _as_date(getattr(activity, "start_date", None))
        window_end = _as_date(getattr(activity, "end_date", None))
        if window_start is None or window_end is None:
            # An activity without readable dates bounds nothing. Saying so is
            # honest; flagging the assignment would blame the wrong record.
            return [_ok(self, "The activity carries no readable date window.")]

        booked_start = assignment.start_at.date()
        booked_end = assignment.end_at.date()
        before = (window_start - booked_start).days
        after = (booked_end - window_end).days
        if before <= 0 and after <= 0:
            return [_ok(self, "The assignment sits inside its activity's window.")]

        label = _activity_label(activity)
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=(
                    f"The assignment runs {booked_start.isoformat()} to {booked_end.isoformat()}, "
                    f"outside activity {label} ({window_start.isoformat()} to {window_end.isoformat()})."
                ),
                element_ref=str(assignment.id) if assignment.id else None,
                suggestion=(
                    "Move the assignment inside the activity's dates, or reschedule the activity to cover the work."
                ),
                details={
                    "activity_id": str(assignment.activity_id),
                    "activity_label": label,
                    "activity_start": window_start.isoformat(),
                    "activity_end": window_end.isoformat(),
                    "assignment_start": booked_start.isoformat(),
                    "assignment_end": booked_end.isoformat(),
                    "days_early": max(before, 0),
                    "days_late": max(after, 0),
                },
            )
        ]


class AssignmentTargetAmbiguous(ValidationRule):
    """A booking names both a schedule activity and a to-do task."""

    rule_id = "resources.assignment_target_ambiguous"
    name = "Assignment names two different targets"
    standard = "resources"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "An assignment names both a schedule activity and a to-do task, which are two different objects."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        assignment = payload.get("assignment")
        if assignment is None:
            return [_ok(self, "No assignment supplied; nothing to check.")]
        if assignment.activity_id is None or assignment.task_id is None:
            return [_ok(self, "The assignment names at most one target.")]

        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=(
                    "The assignment names a schedule activity and a to-do task at once, "
                    "so neither register can be trusted to hold the whole booking."
                ),
                element_ref=str(assignment.id) if assignment.id else None,
                suggestion="Clear whichever of the activity or the task the booking does not actually staff.",
                details={
                    "activity_id": str(assignment.activity_id),
                    "task_id": str(assignment.task_id),
                },
            )
        ]


class AssignmentActivityMissing(ValidationRule):
    """A booking names an activity nobody can resolve."""

    rule_id = "resources.assignment_activity_missing"
    name = "Assignment names an unresolvable activity"
    standard = "resources"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "An assignment carries an activity id that resolves to no schedule activity."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        assignment = payload.get("assignment")
        if assignment is None:
            return [_ok(self, "No assignment supplied; nothing to check.")]
        if assignment.activity_id is None:
            return [_ok(self, "The assignment names no schedule activity.")]
        if not payload.get("activity_lookup_available", True):
            # No schedule module to look in. An activity that cannot be sought
            # is not an activity that is gone, and only one of those is a fault
            # of the assignment.
            return [_ok(self, "The schedule register is not installed, so the link cannot be checked.")]
        if payload.get("activity") is not None:
            return [_ok(self, "The assignment's activity resolves.")]

        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=f"Activity {assignment.activity_id} does not exist, so this booking staffs nothing.",
                element_ref=str(assignment.id) if assignment.id else None,
                suggestion="Point the assignment at a live activity, or clear the link.",
                details={"activity_id": str(assignment.activity_id)},
            )
        ]


RESOURCES_RULES: tuple[type[ValidationRule], ...] = (
    AssignmentOutsideActivityWindow,
    AssignmentTargetAmbiguous,
    AssignmentActivityMissing,
)


def register_resources_rules() -> None:
    """Register every resources rule under the ``resources`` rule set.

    Idempotent: the registry keys on ``rule_id``, so calling this twice (module
    startup plus a test fixture) leaves one copy of each rule.
    """
    for rule_cls in RESOURCES_RULES:
        rule_registry.register(rule_cls(), [RESOURCES_RULE_SET])
    logger.debug("Registered %d resources validation rules", len(RESOURCES_RULES))


__all__ = [
    "RESOURCES_RULES",
    "RESOURCES_RULE_SET",
    "AssignmentActivityMissing",
    "AssignmentOutsideActivityWindow",
    "AssignmentTargetAmbiguous",
    "register_resources_rules",
]
