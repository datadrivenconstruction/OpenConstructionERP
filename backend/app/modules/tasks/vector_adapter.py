"""Tasks vector adapter — feeds the ``oe_tasks`` collection.

Each :class:`~app.modules.tasks.models.Task` row is embedded as the
title plus description, task metadata and any checklist item texts.
The result is upserted into the multi-collection vector store via the
helpers in :mod:`app.core.vector_index`.

The adapter is intentionally narrow — it knows nothing about the event
bus or HTTP routing.  Wiring lives in :mod:`app.modules.tasks.events`
and ``router.py`` respectively.
"""

from __future__ import annotations

from typing import Any

from app.core.vector_index import COLLECTION_TASKS
from app.modules.tasks.models import Task


class TaskVectorAdapter:
    """Embed task rows into the unified vector store."""

    collection_name: str = COLLECTION_TASKS
    module_name: str = "tasks"

    def to_text(self, row: Task) -> str:
        """Build the canonical text that gets embedded.

        Concatenates the title, description, task_type, status, priority
        and any checklist item texts so semantic queries like
        *"review structural drawings"* match tasks regardless of which
        status/type they are in.
        """
        parts: list[str] = []
        if row.title:
            parts.append(row.title.strip())
        if row.description:
            parts.append(row.description.strip())
        task_type = getattr(row, "task_type", None)
        if task_type:
            parts.append(str(task_type))
        status = getattr(row, "status", None)
        if status:
            parts.append(str(status))
        priority = getattr(row, "priority", None)
        if priority:
            parts.append(str(priority))
        checklist = getattr(row, "checklist", None) or []
        if isinstance(checklist, list):
            for item in checklist:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        parts.append(str(text).strip())
        return " | ".join(p for p in parts if p)

    def to_payload(self, row: Task) -> dict[str, Any]:
        """Light metadata returned with every search hit so the UI can
        render a row card without an extra Postgres roundtrip."""
        return {
            "title": (row.title or "")[:160],
            "status": row.status or "",
            "task_type": getattr(row, "task_type", "") or "",
            "priority": getattr(row, "priority", "") or "",
            "due_date": str(row.due_date) if getattr(row, "due_date", None) else "",
        }

    def project_id_of(self, row: Task) -> str | None:
        """Resolve the owning project id directly from the row."""
        project_id = getattr(row, "project_id", None)
        if project_id is None:
            return None
        return str(project_id)


# Singleton instance — adapters are stateless so one shared object is fine.
task_vector_adapter = TaskVectorAdapter()
