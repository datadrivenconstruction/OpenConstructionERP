# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The i18n keys an action sends to the dock, with their English text.

Every key the backend puts on a proposal - its title, field labels, enum
option labels, notes, undo hints and error messages - is declared here once,
with the English the dock falls back to. The dock translates by key; the
English is only the fallback, so a key missing from a locale still reads.
``all_keys()`` is what the i18n phase adds to ``en.ts``, and a unit test holds
every key an action can emit to this table.
"""

from __future__ import annotations

TITLE_PREFIX = "erp_chat.action.type."
FIELD_PREFIX = "erp_chat.action.field."
OPTION_PREFIX = "erp_chat.action.option."
NOTE_PREFIX = "erp_chat.action.note."
REVERT_HINT_PREFIX = "erp_chat.action.revert_hint."
ERROR_PREFIX = "erp_chat.action.error."
FIELD_ERROR_PREFIX = "erp_chat.action.field_error."
BLOCKED_PREFIX = "erp_chat.action.blocked."

TITLES: dict[str, str] = {
    "boq.add_position": "Add BOQ position",
    "boq.update_position": "Change BOQ position",
    "task.create": "Create task",
    "rfi.create": "Create RFI",
}

FIELDS: dict[str, str] = {
    "description": "Description",
    "quantity": "Quantity",
    "unit": "Unit",
    "unit_rate": "Unit rate",
    "total": "Total",
    "ordinal": "Position number",
    "section": "Section",
    "title": "Title",
    "task_type": "Type",
    "priority": "Priority",
    "due_date": "Due date",
    "assignee": "Assignee",
    # rfi.create
    "subject": "Subject",
    "question": "Question",
    "discipline": "Discipline",
    "response_due_date": "Response due date",
    "cost_impact": "Cost impact",
    "cost_impact_value": "Cost exposure",
    "schedule_impact": "Schedule impact",
    "schedule_impact_days": "Schedule slip (days)",
}

OPTIONS: dict[str, dict[str, str]] = {
    "priority": {
        "low": "Low",
        "normal": "Normal",
        "high": "High",
        "urgent": "Urgent",
    },
    "task_type": {
        "task": "Task",
        "topic": "Topic",
        "information": "Information",
        "decision": "Decision",
        "personal": "Personal",
    },
    "yes_no": {
        "yes": "Yes",
        "no": "No",
    },
    # The RFI register's own scale: "critical" where tasks say "urgent".
    "rfi_priority": {
        "low": "Low",
        "normal": "Normal",
        "high": "High",
        "critical": "Critical",
    },
    "rfi_discipline": {
        "architectural": "Architectural",
        "structural": "Structural",
        "mep": "MEP",
        "electrical": "Electrical",
        "plumbing": "Plumbing",
        "civil": "Civil",
        "landscape": "Landscape",
    },
}

NOTES: dict[str, str] = {
    "assignee_unmatched": ('No project member matches "{{name}}", so the task will be created without an assignee.'),
    "assignee_ambiguous": (
        'Several project members match "{{name}}", so the task will be created without an assignee. '
        "Edit the assignee to pick one."
    ),
    # The same two cases for any other person field (an RFI's assignee, a risk owner, ...); the note
    # sits under the field it is about.
    "member_unmatched": 'No project member matches "{{name}}", so this field is left empty.',
    "member_ambiguous": 'Several project members match "{{name}}", so this field is left empty. Pick one from the list.',
    "linked_master": (
        "This line is the master of {{count}} linked lines. Changing its description, unit or rate "
        "changes those lines too."
    ),
    "linked_instance": (
        "This line is linked to a master line. Changing its description, unit or rate unlinks it, "
        "so it stops following the master."
    ),
    "top_level_position": "This bill has no sections, so the line is added at the top level.",
}

REVERT_HINTS: dict[str, str] = {
    "task_notifications": (
        "The assignee has already been notified. Undo deletes the task but cannot take that notification back."
    ),
    "position_unlinked": (
        "Applying this unlinked the line from its master. Undo restores the old values but does not link it again."
    ),
    # RFI numbers are the project's highest number plus one, so undoing the newest RFI hands its
    # number to the next one; the notification already sent names that number.
    "rfi_notifications": (
        "The assignee has already been notified. Undo deletes the RFI but cannot take that notification back, "
        "and the next RFI may be given the same number."
    ),
    "rfi_number": "Undo deletes the RFI, and the next RFI may be given the same number.",
}

ERRORS: dict[str, str] = {
    "validation_error": "Some values need fixing before this change can be applied.",
    "not_found": "This change is no longer available to you.",
    "project_required": "No project is selected. Open a project or name the project in your request.",
    "project_not_found": "The project was not found, or you do not have access to it.",
    "no_boq": "This project has no bill of quantities yet. Create one first.",
    "boq_not_found": "That bill of quantities was not found in this project.",
    "boq_ambiguous": "This project has several bills of quantities. Say which one to use.",
    "section_not_found": "That section was not found in the bill of quantities.",
    "section_ambiguous": "Several sections match. Say which one to use.",
    "position_not_found": "That position was not found.",
    "position_ambiguous": "Several positions match. Say which bill of quantities it is in.",
    "position_is_section": "That line is a section heading, not a priced position.",
    "no_change": "The proposed values are the same as the current ones, so there is nothing to change.",
    # Read by the person on the card and by the model at propose and undo time. Only an admin or a
    # manager may unlock a bill (``POST /boq/boqs/{id}/unlock/``), while anyone who can open the
    # bill may create a revision of it, so the text names both ways out.
    "locked": (
        "This bill of quantities is locked, so nothing was changed. Only an admin or a manager can unlock it. "
        "Ask one of them, or create a revision of the bill and make the change there."
    ),
    "target_changed": (
        "Someone changed this record after the assistant prepared the change, so nothing was applied. "
        "Ask the assistant again so it works from the current values."
    ),
    "changed_since_apply": (
        "This record was edited after the change was applied. Undoing it now would overwrite newer work, "
        "so open the record and adjust it by hand."
    ),
    "target_missing": "The record this change refers to no longer exists.",
    "not_pending": "This change has already been decided.",
    "not_editable": "This change can no longer be edited.",
    "not_applied": "Only an applied change can be undone.",
    "not_reversible": "This kind of change cannot be undone automatically.",
    "forbidden": "You do not have permission to make this change in this project.",
    "domain_error": "The change could not be saved.",
    "internal_error": "Something went wrong while saving the change.",
    "unknown_action": "This kind of change is not supported.",
    "module_unavailable": (
        "The part of the platform this change belongs to is switched off, so the change cannot be made now."
    ),
}

FIELD_ERRORS: dict[str, str] = {
    "required": "This field is required.",
    "not_a_number": "Enter a number.",
    "negative": "The value cannot be negative.",
    "too_long": "The text is too long.",
    "invalid_date": "Enter a date as YYYY-MM-DD.",
    "invalid_option": "Pick one of the listed options.",
    "not_editable": "This field cannot be edited.",
    "ordinal_taken": "This position number is already used in the bill.",
    "invalid_id": "This reference is not valid.",
    "not_whole_number": "Enter a whole number.",
    "percent_range": "Enter a percentage from 0 to 100.",
}

BLOCKED: dict[str, str] = {
    "permission": (
        "You do not have permission to make this change. Someone with the right role in this project can apply it."
    ),
    "module_unavailable": (
        "The part of the platform this change belongs to is switched off, so nobody can apply it until an "
        "administrator switches it on again."
    ),
}


def title_key(action_type: str) -> str:
    """i18n key of an action type's title, dots kept (``erp_chat.action.type.task.create``)."""
    return f"{TITLE_PREFIX}{action_type}"


def field_key(key: str) -> str:
    """i18n key of a field label."""
    return f"{FIELD_PREFIX}{key}"


def option_key(field: str, value: str) -> str:
    """i18n key of an enum option label."""
    return f"{OPTION_PREFIX}{field}.{value}"


def all_keys() -> dict[str, str]:
    """Every key an action can put on the wire, mapped to its English text."""
    keys: dict[str, str] = {}
    keys.update({title_key(k): v for k, v in TITLES.items()})
    keys.update({field_key(k): v for k, v in FIELDS.items()})
    for field, options in OPTIONS.items():
        keys.update({option_key(field, value): text for value, text in options.items()})
    keys.update({f"{NOTE_PREFIX}{k}": v for k, v in NOTES.items()})
    keys.update({f"{REVERT_HINT_PREFIX}{k}": v for k, v in REVERT_HINTS.items()})
    keys.update({f"{ERROR_PREFIX}{k}": v for k, v in ERRORS.items()})
    keys.update({f"{FIELD_ERROR_PREFIX}{k}": v for k, v in FIELD_ERRORS.items()})
    keys.update({f"{BLOCKED_PREFIX}{k}": v for k, v in BLOCKED.items()})
    return keys
