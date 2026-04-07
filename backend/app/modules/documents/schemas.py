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

    # Phase 17: CDE / revision-chain fields
    cde_state: str | None = Field(
        default=None,
        pattern=r"^(wip|shared|published|archived)$",
    )
    suitability_code: str | None = Field(default=None, max_length=10)
    revision_code: str | None = Field(default=None, max_length=20)
    drawing_number: str | None = Field(default=None, max_length=100)
    is_current_revision: bool | None = None
    parent_document_id: UUID | None = None
    security_classification: str | None = Field(default=None, max_length=50)
    discipline: str | None = Field(
        default=None,
        pattern=r"^(architectural|structural|mechanical|electrical|plumbing|civil)$",
    )


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

    # Phase 17: CDE / revision-chain fields
    cde_state: str | None = None
    suitability_code: str | None = None
    revision_code: str | None = None
    drawing_number: str | None = None
    is_current_revision: bool | None = True
    parent_document_id: UUID | None = None
    security_classification: str | None = None
    discipline: str | None = None


# ── Summary schema ───────────────────────────────────────────────────────


class DocumentSummary(BaseModel):
    """Aggregated document stats for a project."""

    total_documents: int = 0
    total_size_bytes: int = 0
    by_category: dict[str, int] = Field(default_factory=dict)


# ── Photo schemas ───────────────────────────────────────────────────────


class PhotoUpdate(BaseModel):
    """Partial update for a project photo."""

    model_config = ConfigDict(str_strip_whitespace=True)

    caption: str | None = None
    tags: list[str] | None = None
    category: str | None = Field(
        default=None,
        pattern=r"^(site|progress|defect|delivery|safety|other)$",
    )


class PhotoResponse(BaseModel):
    """Photo returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    document_id: str | None = None
    filename: str
    file_path: str = ""
    caption: str | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None
    tags: list[str] = Field(default_factory=list)
    taken_at: datetime | None = None
    category: str = "site"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_by: str = ""
    created_at: datetime
    updated_at: datetime


class PhotoTimelineGroup(BaseModel):
    """Photos grouped by date for timeline view."""

    date: str
    photos: list[PhotoResponse]


# ── Sheet schemas ──────────────────────────────────────────────────────


class SheetUpdate(BaseModel):
    """Partial update for a drawing sheet."""

    model_config = ConfigDict(str_strip_whitespace=True)

    sheet_number: str | None = Field(default=None, max_length=100)
    sheet_title: str | None = Field(default=None, max_length=500)
    discipline: str | None = Field(default=None, max_length=100)
    revision: str | None = Field(default=None, max_length=50)
    revision_date: datetime | None = None
    scale: str | None = Field(default=None, max_length=50)
    is_current: bool | None = None
    metadata: dict[str, Any] | None = None


class SheetResponse(BaseModel):
    """Sheet returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    document_id: str = ""
    page_number: int
    sheet_number: str | None = None
    sheet_title: str | None = None
    discipline: str | None = None
    revision: str | None = None
    revision_date: datetime | None = None
    scale: str | None = None
    is_current: bool = True
    previous_version_id: UUID | None = None
    thumbnail_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_by: str = ""
    created_at: datetime
    updated_at: datetime


class SheetVersionHistory(BaseModel):
    """Version history for a sheet — list of all revisions."""

    current: SheetResponse
    history: list[SheetResponse] = Field(default_factory=list)
