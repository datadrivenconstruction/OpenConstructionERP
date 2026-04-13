"""BIM Requirements Pydantic schemas -- request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Universal Requirement ──────────────────────────────────────────────────


class UniversalRequirementSchema(BaseModel):
    """A single normalized BIM requirement (5-column model)."""

    element_filter: dict[str, Any] = Field(default_factory=dict)
    property_group: str | None = None
    property_name: str
    constraint_def: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] | None = None


# ── Parse result ───────────────────────────────────────────────────────────


class ParseError(BaseModel):
    """Describes a single parse error or warning."""

    row: int | None = None
    field: str = ""
    msg: str = ""


class ParseResultSchema(BaseModel):
    """Result returned by any parser."""

    requirements: list[UniversalRequirementSchema] = Field(default_factory=list)
    errors: list[ParseError] = Field(default_factory=list)
    warnings: list[ParseError] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    format_detected: str = ""

    @property
    def success(self) -> bool:
        """True if at least one requirement was parsed."""
        return len(self.requirements) > 0

    @property
    def has_errors(self) -> bool:
        """True if there are parsing errors."""
        return len(self.errors) > 0


# ── Import request/response ───────────────────────────────────────────────


class BIMRequirementSetResponse(BaseModel):
    """Requirement set returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    description: str = ""
    source_format: str
    source_filename: str = ""
    created_by: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class BIMRequirementResponse(BaseModel):
    """Individual BIM requirement returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    requirement_set_id: UUID
    element_filter: dict[str, Any] = Field(default_factory=dict)
    property_group: str | None = None
    property_name: str
    constraint_def: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] | None = None
    source_format: str = ""
    source_ref: str = ""
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class BIMRequirementSetDetail(BaseModel):
    """Requirement set with nested requirements."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    description: str = ""
    source_format: str
    source_filename: str = ""
    created_by: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    requirements: list[BIMRequirementResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ImportResultResponse(BaseModel):
    """Response after importing a requirements file."""

    requirement_set_id: UUID
    name: str
    source_format: str
    total_requirements: int = 0
    errors: list[ParseError] = Field(default_factory=list)
    warnings: list[ParseError] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Validation (compliance check) ────────────────────────────────────────


class RequirementCheckResult(BaseModel):
    """Result of checking one requirement against a BIM model."""

    requirement_id: UUID
    property_group: str | None = None
    property_name: str
    element_filter: dict[str, Any] = Field(default_factory=dict)
    constraint_def: dict[str, Any] = Field(default_factory=dict)
    status: str  # "pass", "fail", "not_applicable"
    matched_elements: int = 0
    compliant_elements: int = 0
    non_compliant_elements: int = 0
    details: str = ""


class RequirementValidationResponse(BaseModel):
    """Compliance report for a requirement set against a BIM model."""

    requirement_set_id: UUID
    requirement_set_name: str
    model_id: UUID
    total_requirements: int = 0
    passed: int = 0
    failed: int = 0
    not_applicable: int = 0
    compliance_ratio: float = 0.0
    results: list[RequirementCheckResult] = Field(default_factory=list)
