# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠File Versioning Pydantic schemas - request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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


class FileVersionCreate(BaseModel):
    """Register a new version row for an existing file.

    The service supersedes the prior ``is_current`` row in the same
    ``(project_id, file_kind, canonical_name)`` chain, links it via
    ``previous_version_id``, and bumps ``version_number``.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    file_kind: FileKindLiteral
    file_id: str = Field(min_length=1, max_length=64)
    canonical_name: str = Field(min_length=1, max_length=255)
    previous_version_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=2000)
    file_size: int = Field(default=0, ge=0)
    checksum: str | None = Field(default=None, max_length=64)


class FileVersionResponse(BaseModel):
    """A single row in a version chain."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    file_kind: str
    file_id: str
    version_number: int
    canonical_name: str
    previous_version_id: UUID | None
    is_current: bool
    superseded_at: datetime | None
    superseded_by_id: UUID | None
    notes: str | None
    uploaded_by_id: UUID | None
    uploaded_at: datetime
    file_size: int
    checksum: str | None
    created_at: datetime
    updated_at: datetime
