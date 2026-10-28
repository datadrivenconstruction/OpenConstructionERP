# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠File Trash Pydantic schemas - request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TrashKindLiteral = Literal[
    "document",
    "photo",
    "sheet",
    "bim_model",
    "dwg_drawing",
    "takeoff",
    "report",
    "markup",
]


class TrashSoftDeleteRequest(BaseModel):
    """Soft-delete an existing file by kind + id."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    kind: TrashKindLiteral
    original_id: str = Field(min_length=1, max_length=64)
    canonical_name: str = Field(default="", max_length=255)
    payload: dict[str, Any] | None = None
    retention_days: int = Field(default=30, ge=1, le=365)


class TrashRestoreRequest(BaseModel):
    """Restore a trashed row (token is optional - restore is auth-gated)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    restore_token: str | None = None


class TrashPurgeRequest(BaseModel):
    """Hard-purge a trashed row. Requires the matching restore token."""

    model_config = ConfigDict(str_strip_whitespace=True)

    confirm_token: str = Field(min_length=1, max_length=64)


class TrashItemResponse(BaseModel):
    """One row in the recycle bin."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    original_kind: str
    original_id: str
    canonical_name: str
    payload_json: dict[str, Any]
    trashed_at: datetime
    trashed_by_id: UUID | None
    retention_days: int
    restored_at: datetime | None
    restored_by_id: UUID | None
    purged_at: datetime | None
    restore_token: str
    file_size: int
    created_at: datetime
    updated_at: datetime


class TrashListResponse(BaseModel):
    """Paginated trash list."""

    items: list[TrashItemResponse]
    total: int
    limit: int
    offset: int


class TrashStatsResponse(BaseModel):
    """Aggregated counts + bytes in the trash for a project."""

    project_id: UUID
    count: int
    total_bytes: int
    oldest_trashed_at: datetime | None
    newest_trashed_at: datetime | None
