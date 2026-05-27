"""‌⁠‍Code-defined built-in field-report templates.

These are intentionally NOT database rows: keeping them as constants
means a fresh install needs no seed migration (CLAUDE.md principle #1 —
lightweight), and they can never be accidentally deleted by a user.

The service layer merges these in alongside the project's own custom
templates. Built-ins carry a synthetic, stable string id of the form
``builtin:<slug>`` and are read-only (PATCH / DELETE are rejected).

Copy is generic on purpose — no country-specific standards, regulator
names, or city names (CLAUDE.md "global copy").
"""

from __future__ import annotations

from typing import Any

# Each template: id slug, name, report_type, ordered field definitions.
BUILTIN_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "builtin:daily-site-report",
        "name": "Daily Site Report",
        "description": "General-purpose end-of-day site diary covering progress, workforce, and conditions.",
        "report_type": "daily",
        "fields": [
            {
                "key": "work_summary",
                "label": "Summary of work performed",
                "type": "textarea",
                "required": True,
                "placeholder": "Describe the main activities completed on site today.",
            },
            {
                "key": "areas_worked",
                "label": "Areas / zones worked",
                "type": "text",
                "placeholder": "e.g. Zone A foundations, Level 2 fit-out",
            },
            {
                "key": "workforce_summary",
                "label": "Workforce on site",
                "type": "text",
                "placeholder": "Headcount and trades present",
            },
            {
                "key": "materials_received",
                "label": "Materials / deliveries received",
                "type": "textarea",
            },
            {
                "key": "delays_issues",
                "label": "Delays or issues encountered",
                "type": "textarea",
            },
            {
                "key": "next_day_plan",
                "label": "Plan for next working day",
                "type": "textarea",
            },
        ],
    },
    {
        "id": "builtin:safety-walk",
        "name": "Safety Walk",
        "description": "Structured safety observation walk — hazards, corrective actions, and sign-off.",
        "report_type": "safety",
        "fields": [
            {
                "key": "walk_area",
                "label": "Area inspected",
                "type": "text",
                "required": True,
            },
            {
                "key": "overall_rating",
                "label": "Overall safety rating",
                "type": "select",
                "required": True,
                "options": ["Good", "Acceptable", "Needs improvement", "Critical"],
            },
            {
                "key": "hazards_observed",
                "label": "Hazards observed",
                "type": "textarea",
                "required": True,
                "placeholder": "List each hazard with its location.",
            },
            {
                "key": "corrective_actions",
                "label": "Corrective actions taken / required",
                "type": "textarea",
            },
            {
                "key": "ppe_compliance",
                "label": "PPE compliance observed",
                "type": "checkbox",
            },
            {
                "key": "follow_up_required",
                "label": "Follow-up required",
                "type": "checkbox",
            },
            {
                "key": "responsible_person",
                "label": "Responsible person for follow-up",
                "type": "text",
            },
        ],
    },
    {
        "id": "builtin:progress-report",
        "name": "Progress Report",
        "description": "Periodic progress snapshot — percent complete, milestones, and forecast.",
        "report_type": "inspection",
        "fields": [
            {
                "key": "reporting_period",
                "label": "Reporting period",
                "type": "text",
                "required": True,
                "placeholder": "e.g. Week 14, or 2026-05-11 to 2026-05-17",
            },
            {
                "key": "overall_progress_pct",
                "label": "Overall progress (%)",
                "type": "number",
                "required": True,
            },
            {
                "key": "milestones_completed",
                "label": "Milestones completed this period",
                "type": "textarea",
            },
            {
                "key": "milestones_upcoming",
                "label": "Upcoming milestones",
                "type": "textarea",
            },
            {
                "key": "schedule_status",
                "label": "Schedule status",
                "type": "select",
                "options": ["On track", "Ahead", "Behind", "At risk"],
            },
            {
                "key": "risks_concerns",
                "label": "Key risks and concerns",
                "type": "textarea",
            },
        ],
    },
]

_BUILTIN_BY_ID = {tpl["id"]: tpl for tpl in BUILTIN_TEMPLATES}


def get_builtin(template_id: str) -> dict[str, Any] | None:
    """Return a built-in template dict by its synthetic id, or None."""
    return _BUILTIN_BY_ID.get(template_id)


def is_builtin_id(template_id: str) -> bool:
    """True when the id refers to a code-defined built-in template."""
    return isinstance(template_id, str) and template_id.startswith("builtin:")
