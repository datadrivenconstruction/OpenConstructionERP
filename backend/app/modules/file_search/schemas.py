# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠File search Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Allowed file_kind values mirror the file-manager surface so callers
# cannot inject novel kinds that the indexer doesn't know how to fetch.
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

SearchMode = Literal["content", "filename"]


class IndexFileRequest(BaseModel):
    """Trigger indexing of a single file."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    file_kind: FileKindLiteral
    file_id: str = Field(min_length=1, max_length=64)


class IndexFileResponse(BaseModel):
    """Result of an indexing run for a single file."""

    file_kind: str
    file_id: str
    indexed: bool
    ocr_engine: str
    page_count: int | None = None
    chars_extracted: int = 0


class SearchHit(BaseModel):
    """A single file matching a content/filename search."""

    file_id: str
    kind: str
    canonical_name: str
    snippet: str
    score: float
    page_count: int | None = None


class SearchResponse(BaseModel):
    """Paged result for ``GET /api/v1/file-search/``."""

    project_id: UUID
    q: str
    mode: SearchMode
    total: int
    hits: list[SearchHit] = Field(default_factory=list)


class ReindexResponse(BaseModel):
    """Result summary for ``POST /file-search/reindex/``."""

    project_id: UUID
    started_at: datetime
    queued: int
    indexed: int
    skipped: int
    errors: int


class IndexedFile(BaseModel):
    """Row-level metadata about an indexed file (used by reindex / debug)."""

    model_config = ConfigDict(from_attributes=True)

    file_kind: str
    file_id: str
    ocr_engine: str | None
    page_count: int | None
    indexed_at: datetime
    chars: int
