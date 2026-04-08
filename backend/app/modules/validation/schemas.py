"""Validation Pydantic schemas — request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

# ── Result item (single rule check) ────────────────────────────────


class ValidationResultItem(BaseModel):
    """A single validation rule result within a report."""

    rule_id: str
    status: str = Field(description="pass, warning, error")
    message: str
    element_ref: str | None = None
    details: dict[str, Any] | None = None
    suggestion: str | None = None


# ── Report ────────────────────────────────────────────────────────────────


class ValidationReportCreate(BaseModel):
    """Schema for creating a validation report manually (rare — prefer /run)."""

    project_id: UUID
    target_type: str = Field(description="boq, document, cad_import, tender")
    target_id: str
    rule_set: str = Field(description="e.g. 'din276+gaeb+boq_quality'")


class ValidationReportResponse(BaseModel):
    """Full validation report returned by the API."""

    id: UUID
    project_id: UUID
    target_type: str
    target_id: str
    rule_set: str
    status: str
    score: str | None = None
    total_rules: int = 0
    passed_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    results: list[dict[str, Any]] = Field(default_factory=list)
    created_by: UUID | None = None
    created_at: datetime | None = None
    metadata_: dict[str, Any] = Field(default_factory=dict, alias="metadata")

    model_config = {"from_attributes": True, "populate_by_name": True}


# ── Run validation ────────────────────────────────────────────────────────


class RunValidationRequest(BaseModel):
    """Request body for POST /validation/run."""

    project_id: UUID
    boq_id: UUID
    rule_sets: list[str] = Field(
        default=["boq_quality"],
        description="Rule set names to apply, e.g. ['boq_quality', 'din276']",
    )


class RunValidationResponse(BaseModel):
    """Response from POST /validation/run — report summary + full results."""

    report_id: UUID
    status: str
    score: float
    total_rules: int
    passed_count: int
    warning_count: int
    error_count: int
    info_count: int
    rule_sets: list[str]
    duration_ms: float
    results: list[ValidationResultItem]


# ── Rule sets ─────────────────────────────────────────────────────────────


class RuleSetInfo(BaseModel):
    """Information about an available rule set."""

    name: str
    description: str
    rule_count: int
    rules: list[dict[str, Any]] = Field(default_factory=list)
