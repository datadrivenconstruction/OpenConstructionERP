"""Document Management Pydantic schemas — request/response models.

Defines create, update, and response schemas for documents.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── Document schemas ─────────────────────────────────────────────────────


class DocumentUpdate(BaseModel):
    """Partial update for a document."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    category: str | None = Field(
        default=None,
        pattern=r"^(drawing|contract|specification|photo|correspondence|other)$",
    )
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


class DocumentResponse(BaseModel):
    """Document returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    description: str
    category: str
    file_size: int = 0
    mime_type: str = ""
    version: int = 1
    uploaded_by: str = ""
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Summary schema ───────────────────────────────────────────────────────


class DocumentSummary(BaseModel):
    """Aggregated document stats for a project."""

    total_documents: int = 0
    total_size_bytes: int = 0
    by_category: dict[str, int] = Field(default_factory=dict)
