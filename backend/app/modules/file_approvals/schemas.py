# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠File Approvals (W8) Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

WorkflowStatus = Literal["in_review", "approved", "rejected", "withdrawn"]
StepDecision = Literal["pending", "approved", "rejected", "delegated"]

FileKindLiteral = Literal[
    "document",
    "photo",
    "sheet",
    "bim_model",
    "dwg_drawing",
    "takeoff",
    "report",
    "markup",
]

# ── Stamp templates ──────────────────────────────────────────────────────


class StampTemplateCreate(BaseModel):
    """Create / update a stamp template."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None
    name: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=255)
    color: str = Field(default="#16a34a", pattern=r"^#[0-9A-Fa-f]{6}$")
    svg_template: str = Field(min_length=1)
    is_active: bool = True


class StampTemplateResponse(BaseModel):
    """A stamp template row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None
    name: str
    text: str
    color: str
    svg_template: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ── Workflows ────────────────────────────────────────────────────────────


class ApprovalStepCreate(BaseModel):
    """One step inside a submit-for-approval payload."""

    model_config = ConfigDict(str_strip_whitespace=True)

    approver_id: UUID
    role_label: str | None = Field(default=None, max_length=64)


class ApprovalStepResponse(BaseModel):
    """One ordered step inside a workflow."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_id: UUID
    sort_order: int
    approver_id: UUID
    role_label: str | None
    decision: str
    decision_at: datetime | None
    decision_note: str | None


class ApprovalWorkflowCreate(BaseModel):
    """Submit a file for approval - creates the workflow + steps."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    file_kind: FileKindLiteral
    file_id: str = Field(min_length=1, max_length=64)
    file_version_snapshot: str | None = Field(default=None, max_length=32)
    stamp_template_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=4000)
    steps: list[ApprovalStepCreate] = Field(min_length=1)


class ApprovalStepDecide(BaseModel):
    """Record a decision on a step (approve / reject / delegate)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    decision: Literal["approved", "rejected", "delegated"]
    decision_note: str | None = Field(default=None, max_length=4000)


class ApprovalWorkflowResponse(BaseModel):
    """Workflow header + ordered steps."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    file_kind: str
    file_id: str
    file_version_snapshot: str | None
    submitted_by_id: UUID | None
    submitted_at: datetime
    status: str
    final_decision_at: datetime | None
    final_decision_by_id: UUID | None
    stamp_template_id: UUID | None
    stamped_artifact_path: str | None
    notes: str | None
    steps: list[ApprovalStepResponse]
    created_at: datetime
    updated_at: datetime
