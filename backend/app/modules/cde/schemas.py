"""CDE Pydantic schemas — request/response models.

Defines create, update, and response schemas for document containers
and revisions following ISO 19650.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Container Create ──────────────────────────────────────────────────────


class ContainerCreate(BaseModel):
    """Create a new document container."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    container_code: str = Field(..., min_length=1, max_length=255)
    originator_code: str | None = Field(default=None, max_length=50)
    functional_breakdown: str | None = Field(default=None, max_length=50)
    spatial_breakdown: str | None = Field(default=None, max_length=50)
    form_code: str | None = Field(default=None, max_length=50)
    discipline_code: str | None = Field(default=None, max_length=50)
    sequence_number: str | None = Field(default=None, max_length=20)
    classification_system: str | None = Field(
        default=None,
        pattern=r"^(uniclass|din276|csi)$",
    )
    classification_code: str | None = Field(default=None, max_length=50)
    cde_state: str = Field(
        default="wip",
        pattern=r"^(wip|shared|published|archived)$",
    )
    suitability_code: str | None = Field(default=None, max_length=10)
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    security_classification: str | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Container Update ──────────────────────────────────────────────────────


class ContainerUpdate(BaseModel):
    """Partial update for a document container."""

    model_config = ConfigDict(str_strip_whitespace=True)

    container_code: str | None = Field(default=None, min_length=1, max_length=255)
    originator_code: str | None = Field(default=None, max_length=50)
    functional_breakdown: str | None = Field(default=None, max_length=50)
    spatial_breakdown: str | None = Field(default=None, max_length=50)
    form_code: str | None = Field(default=None, max_length=50)
    discipline_code: str | None = Field(default=None, max_length=50)
    sequence_number: str | None = Field(default=None, max_length=20)
    classification_system: str | None = Field(
        default=None,
        pattern=r"^(uniclass|din276|csi)$",
    )
    classification_code: str | None = Field(default=None, max_length=50)
    suitability_code: str | None = Field(default=None, max_length=10)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    security_classification: str | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None


# ── Container Response ────────────────────────────────────────────────────


class ContainerResponse(BaseModel):
    """Document container returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    container_code: str
    originator_code: str | None = None
    functional_breakdown: str | None = None
    spatial_breakdown: str | None = None
    form_code: str | None = None
    discipline_code: str | None = None
    sequence_number: str | None = None
    classification_system: str | None = None
    classification_code: str | None = None
    cde_state: str = "wip"
    suitability_code: str | None = None
    current_revision_id: str | None = None
    title: str
    description: str | None = None
    security_classification: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── State Transition ──────────────────────────────────────────────────────


class StateTransitionRequest(BaseModel):
    """Request to transition a container's CDE state."""

    model_config = ConfigDict(str_strip_whitespace=True)

    target_state: str = Field(
        ...,
        pattern=r"^(wip|shared|published|archived)$",
    )
    reason: str | None = Field(default=None, max_length=500)


# ── Revision Create ──────────────────────────────────────────────────────


class RevisionCreate(BaseModel):
    """Create a new revision within a container."""

    model_config = ConfigDict(str_strip_whitespace=True)

    file_name: str = Field(..., min_length=1, max_length=500)
    file_size: str | None = Field(default=None, max_length=20)
    mime_type: str | None = Field(default=None, max_length=100)
    storage_key: str | None = Field(default=None, max_length=500)
    content_hash: str | None = Field(default=None, max_length=64)
    is_preliminary: bool = True
    change_summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Revision Response ────────────────────────────────────────────────────


class RevisionResponse(BaseModel):
    """Document revision returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    container_id: UUID
    revision_code: str
    revision_number: int
    is_preliminary: bool = True
    content_hash: str | None = None
    file_name: str
    file_size: str | None = None
    mime_type: str | None = None
    storage_key: str | None = None
    status: str = "draft"
    approved_by: str | None = None
    change_summary: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
