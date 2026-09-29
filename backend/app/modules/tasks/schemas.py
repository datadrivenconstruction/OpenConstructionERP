# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tasks Pydantic schemas - request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChecklistItemEntry(BaseModel):
    """A single checklist item within a task."""

    id: str | None = None
    text: str = Field(..., min_length=1, max_length=500)
    completed: bool = False


class TaskCreate(BaseModel):
    """Create a new task."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    task_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description=(
            "Built-in types: task, topic, information, decision, personal. Custom category strings are also accepted."
        ),
    )
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    checklist: list[ChecklistItemEntry] = Field(default_factory=list)
    responsible_id: str | None = Field(default=None, max_length=36)
    persons_involved: list[str] = Field(default_factory=list)
    due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    milestone_id: str | None = Field(default=None, max_length=36)
    meeting_id: str | None = Field(default=None, max_length=36)
    status: str = Field(
        default="draft",
        min_length=1,
        max_length=50,
    )
    priority: str = Field(
        default="normal",
        pattern=r"^(low|normal|high|urgent)$",
    )
    result: str | None = Field(default=None, max_length=5000)
    is_private: bool = False
    depends_on: UUID | None = Field(
        default=None,
        description="Task UUID this task depends on. Cannot be completed until predecessor is completed.",
    )
    bim_element_ids: list[str] = Field(
        default_factory=list,
        description="BIM element UUIDs spatially linked to this task (defects, inspections).",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    assignee_contact_id: UUID | None = Field(
        default=None,
        description=(
            "Assign a contact. A contact linked to a platform user becomes the "
            "task's responsible_id; any other contact is kept by name. Stored as "
            "metadata.assignee_contact_id and metadata.assignee_name."
        ),
    )


class TaskUpdate(BaseModel):
    """Partial update for a task."""

    model_config = ConfigDict(str_strip_whitespace=True)

    task_type: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        description=(
            "Built-in types: task, topic, information, decision, personal. Custom category strings are also accepted."
        ),
    )
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    checklist: list[ChecklistItemEntry] | None = None
    responsible_id: str | None = Field(default=None, max_length=36)
    persons_involved: list[str] | None = None
    due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    milestone_id: str | None = Field(default=None, max_length=36)
    meeting_id: str | None = Field(default=None, max_length=36)
    status: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
    )
    priority: str | None = Field(
        default=None,
        pattern=r"^(low|normal|high|urgent)$",
    )
    result: str | None = Field(default=None, max_length=5000)
    is_private: bool | None = None
    depends_on: UUID | None = None
    metadata: dict[str, Any] | None = None
    # See TaskCreate. An explicit null drops the contact link and its name.
    assignee_contact_id: UUID | None = None


class TaskCompleteRequest(BaseModel):
    """Request body for completing a task."""

    result: str | None = Field(default=None, max_length=2000)


class TaskResponse(BaseModel):
    """Task returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    task_type: str
    title: str
    description: str | None = None
    checklist: list[dict[str, Any]] = Field(default_factory=list)
    checklist_progress: float = Field(
        default=0.0,
        description="Completion percentage of checklist items (0.0 - 100.0)",
    )
    responsible_id: str | None = None
    persons_involved: list[str] = Field(default_factory=list)
    due_date: str | None = None
    milestone_id: str | None = None
    meeting_id: str | None = None
    status: str = "draft"
    priority: str = "normal"
    result: str | None = None
    is_private: bool = False
    created_by: str | None = None
    assigned_to: str | None = Field(
        default=None,
        description="Alias for responsible_id - the UUID of the assigned user.",
    )
    assigned_to_name: str | None = Field(
        default=None,
        description="Display name of the assigned user (resolved from responsible_id).",
    )
    depends_on: UUID | None = None
    bim_element_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
    completed_at: str | None = Field(
        default=None,
        description="ISO timestamp when the task was completed (null if not yet completed).",
    )

    # Computed fields
    is_overdue: bool = Field(
        default=False,
        description="True when status is not completed and due_date is past today",
    )
    blocked_by_count: int = Field(
        default=0,
        description="Number of incomplete predecessor tasks (computed from depends_on chain).",
    )


class TaskBimLinkRequest(BaseModel):
    """Replace the set of BIM elements linked to a task (idempotent set)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    bim_element_ids: list[str] = Field(
        default_factory=list,
        description="Full replacement list of BIM element UUIDs for this task.",
    )


class TaskBrief(BaseModel):
    """Lightweight task summary embedded in BIM element responses.

    Contains just enough data for the viewer to render a task badge and
    navigate to the linked task without a second round trip.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    title: str
    status: str
    task_type: str
    due_date: str | None = None


class TaskListResponse(BaseModel):
    """One page of tasks plus the size of the matching set.

    ``total`` counts the rows the query matched, not the length of ``items``.
    Every filter the route accepts - type, status, priority, responsible,
    meeting, free-text search and the project itself - is applied before the
    count is taken, so a zero here means this question found nothing rather than
    the project holding nothing.

    Privacy is inside the count too, not applied after it: a private task
    belonging to someone else is excluded from both ``items`` and ``total``, so
    the number never reveals the existence of a task the caller may not read.
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[TaskResponse]
    total: int
    offset: int
    limit: int


class TaskStatsResponse(BaseModel):
    """Summary statistics for tasks in a project."""

    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)
    by_priority: dict[str, int] = Field(default_factory=dict)
    overdue_count: int = 0
    completed_count: int = 0
    avg_checklist_progress: float | None = Field(
        default=None,
        description="Average checklist completion across all non-completed tasks",
    )
