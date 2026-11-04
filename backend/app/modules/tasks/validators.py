# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Task validation rules (rule set ``tasks``).

Rules judge the task as it will be after the write::

    {"task": {"id", "project_id", "task_type", "status", "due_date", "responsible_id",
              "assignee_name", "checklist": [{"text", "completed"}], "result"}}

* ``tasks.due_date_exists`` (ERROR): a due date is a real calendar day (2026-02-31 is not).
* ``tasks.checklist_closed`` (WARNING): a task is not completed with checklist items still open.
* ``tasks.decision_recorded`` (WARNING): a decision task states the decision when it is completed.
* ``tasks.owner_assigned`` (WARNING): work under way has someone responsible; drafts are exempt.
"""

from __future__ import annotations

from app.core.validation.control_rules import ControlRule, parse_day
from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section

TASKS_RULE_SET = "tasks"

#: Types that are notes or reminders, not work somebody owes.
_UNOWNED_TYPES = frozenset({"personal", "information", "topic"})


class DueDateExistsRule(ControlRule):
    rule_id = "tasks.due_date_exists"
    name = "Task due date is a real calendar day"
    standard = TASKS_RULE_SET
    description = "due_date must exist on the calendar; the schema only checks its shape"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        task = section(context, "task")
        ref = str(task.get("id", ""))
        due = task.get("due_date")
        if blank(due) or parse_day(due) is not None:
            return [self.ok(ref)]
        return [self.fail(context, "date_invalid", ref=ref, field="due_date", value=due)]


class ChecklistClosedRule(ControlRule):
    rule_id = "tasks.checklist_closed"
    name = "Task checklist closed before completion"
    standard = TASKS_RULE_SET
    severity = Severity.WARNING
    description = "A completed task should not leave checklist items open"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        task = section(context, "task")
        ref = str(task.get("id", ""))
        if task.get("status") != "completed":
            return [self.ok(ref)]
        items = [i for i in task.get("checklist") or [] if isinstance(i, dict)]
        open_count = sum(1 for i in items if not i.get("completed"))
        if not open_count:
            return [self.ok(ref)]
        return [self.fail(context, "checklist_open", ref=ref, count=open_count, total=len(items))]


class DecisionRecordedRule(ControlRule):
    rule_id = "tasks.decision_recorded"
    name = "Decision task states the decision"
    standard = TASKS_RULE_SET
    severity = Severity.WARNING
    description = "A completed decision task carries the decision in its result"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        task = section(context, "task")
        ref = str(task.get("id", ""))
        if task.get("task_type") == "decision" and task.get("status") == "completed" and blank(task.get("result")):
            return [self.fail(context, "decision_unrecorded", ref=ref)]
        return [self.ok(ref)]


class OwnerAssignedRule(ControlRule):
    rule_id = "tasks.owner_assigned"
    name = "Task under way has a responsible person"
    standard = TASKS_RULE_SET
    severity = Severity.WARNING
    description = "An open or in-progress task names who is responsible; drafts and notes are exempt"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        task = section(context, "task")
        ref = str(task.get("id", ""))
        if task.get("status") not in {"open", "in_progress"} or task.get("task_type") in _UNOWNED_TYPES:
            return [self.ok(ref)]
        if not blank(task.get("responsible_id")) or not blank(task.get("assignee_name")):
            return [self.ok(ref)]
        return [self.fail(context, "owner_missing", ref=ref)]


TASKS_RULES = (DueDateExistsRule, ChecklistClosedRule, DecisionRecordedRule, OwnerAssignedRule)


def register_tasks_validation_rules() -> None:
    """Register the task rules with the platform rule registry."""
    for rule_class in TASKS_RULES:
        rule_registry.register(rule_class(), [TASKS_RULE_SET])
