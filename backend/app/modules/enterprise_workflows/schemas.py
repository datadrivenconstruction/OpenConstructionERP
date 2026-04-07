"""Enterprise Workflows Pydantic schemas — request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Workflow ────────────────────────────────────────────────────────────────


class WorkflowCreate(BaseModel):
    """Create a new approval workflow."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None
    entity_type: str = Field(..., max_length=100)
    name: str = Field(..., max_length=255)
    description: str | None = None
    steps: list[dict[str, Any]] = Field(default_factory=list)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowUpdate(BaseModel):
    """Partial update for a workflow."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None
    entity_type: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    steps: list[dict[str, Any]] | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


class WorkflowResponse(BaseModel):
    """Workflow returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID | None = None
    entity_type: str
    name: str
    description: str | None = None
    steps: list[dict[str, Any]] = Field(default_factory=list)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class WorkflowListResponse(BaseModel):
    """Paginated list of workflows."""

    items: list[WorkflowResponse]
    total: int
    offset: int
    limit: int


# ── Approval Request ────────────────────────────────────────────────────────


class ApprovalRequestCreate(BaseModel):
    """Submit an entity for approval."""

    model_config = ConfigDict(str_strip_whitespace=True)

    workflow_id: UUID
    entity_type: str = Field(..., max_length=100)
    entity_id: str = Field(..., max_length=36)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecision(BaseModel):
    """Approve or reject an approval request."""

    model_config = ConfigDict(str_strip_whitespace=True)

    decision_notes: str | None = None


class ApprovalRequestResponse(BaseModel):
    """Approval request returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workflow_id: UUID
    entity_type: str
    entity_id: str
    current_step: int = 1
    status: str = "pending"
    requested_by: UUID
    decided_by: UUID | None = None
    decided_at: str | None = None
    decision_notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class ApprovalRequestListResponse(BaseModel):
    """Paginated list of approval requests."""

    items: list[ApprovalRequestResponse]
    total: int
    offset: int
    limit: int
