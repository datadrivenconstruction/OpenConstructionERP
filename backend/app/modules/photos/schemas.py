# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Photos API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TargetKind = Literal[
    "boq_position",
    "schedule_activity",
    "location",
    "punch_item",
    "inspection",
    "diary",
    "field_report",
    "safety_obs",
]
AIKind = Literal["caption", "tags", "progress", "hazard"]


class PhotoLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    photo_id: uuid.UUID
    target_kind: str
    target_id: str
    created_by: str | None = None
    created_at: datetime | None = None


class PhotoOut(BaseModel):
    """One photo of the archive. ``file_url``/``thumb_url`` go through this module's auth-checked routes."""

    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    caption: str | None = None
    category: str
    tags: list[str] = Field(default_factory=list)
    taken_at: datetime | None = None
    created_at: datetime | None = None
    created_by: str = ""
    gps_lat: float | None = None
    gps_lon: float | None = None
    gps_accuracy_m: float | None = None
    width: int | None = None
    height: int | None = None
    sha256: str | None = None
    source_module: str = "documents"
    source_id: str | None = None
    category_suggestion: dict[str, Any] | None = None
    thumb_status: str = "pending"
    location_id: uuid.UUID | None = None
    zone: str | None = None
    is_archived: bool = False
    evidence_grade: str = "none"
    taken_at_source: str | None = None
    file_url: str
    thumb_url: str
    links: list[PhotoLinkOut] = Field(default_factory=list)


class PhotoPage(BaseModel):
    items: list[PhotoOut]
    next_cursor: str | None = None
    total: int


class UploadResult(BaseModel):
    items: list[PhotoOut]
    errors: list[dict[str, str]] = Field(default_factory=list)


class TimelineDay(BaseModel):
    date: str
    count: int
    undated: int
    photos: list[PhotoOut]


class TimelineListResponse(BaseModel):
    items: list[TimelineDay]
    total: int
    offset: int = 0
    limit: int = 500


class PhotoListResponse(BaseModel):
    items: list[PhotoOut]
    total: int
    offset: int = 0
    limit: int = 200


class PhotoPatch(BaseModel):
    caption: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=100)
    tags: list[str] | None = None
    taken_at: datetime | None = None
    gps_lat: float | None = Field(default=None, ge=-90, le=90)
    gps_lon: float | None = Field(default=None, ge=-180, le=180)
    zone: str | None = Field(default=None, max_length=128)
    location_id: uuid.UUID | None = None


class AlbumIn(BaseModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    sort_order: int = 0


class AlbumPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    cover_photo_id: uuid.UUID | None = None
    sort_order: int | None = None


class AlbumOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None = None
    cover_photo_id: uuid.UUID | None = None
    sort_order: int = 0
    photo_count: int = 0
    created_at: datetime | None = None


class AlbumListResponse(BaseModel):
    items: list[AlbumOut]
    total: int
    offset: int = 0
    limit: int = 200


class AlbumItemsIn(BaseModel):
    photo_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class LinkIn(BaseModel):
    target_kind: TargetKind
    target_id: str = Field(min_length=1, max_length=64)


class PinIn(BaseModel):
    document_id: str = Field(min_length=1, max_length=255)
    page: int = Field(default=1, ge=1)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    note: str | None = Field(default=None, max_length=2000)


class PinOut(BaseModel):
    id: uuid.UUID
    document_id: str
    page: int
    x: float
    y: float
    note: str | None = None
    photo_ref: str | None = None


class PinListResponse(BaseModel):
    items: list[PinOut]
    total: int
    offset: int = 0
    limit: int = 200


class CompareIn(BaseModel):
    project_id: uuid.UUID
    before_photo_id: uuid.UUID
    after_photo_id: uuid.UUID
    title: str = Field(default="", max_length=200)


class CompareOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    before: PhotoOut
    after: PhotoOut
    created_at: datetime | None = None


class CompareListResponse(BaseModel):
    items: list[CompareOut]
    total: int
    offset: int = 0
    limit: int = 100


class SuggestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    photo_id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    confidence: float
    provider: str | None = None
    model: str | None = None
    status: str
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime | None = None


class SuggestionListResponse(BaseModel):
    items: list[SuggestionOut]
    total: int
    offset: int = 0
    limit: int = 100


class AcceptIn(BaseModel):
    """Optional edited payload; when given the suggestion is stored as ``edited``."""

    payload: dict[str, Any] | None = None


class JobOut(BaseModel):
    job_id: uuid.UUID
    status: str
    kind: str


class ExportIn(BaseModel):
    project_id: uuid.UUID
    photo_ids: list[uuid.UUID] | None = Field(default=None, max_length=5000)
    album_id: uuid.UUID | None = None


class ExportStatus(BaseModel):
    job_id: uuid.UUID
    status: str
    progress_percent: int = 0
    photo_count: int | None = None
    size_bytes: int | None = None
    ready: bool = False
