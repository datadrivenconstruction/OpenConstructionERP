# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Resumable Uploads Pydantic schemas - request/response models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Bounds shared by the schema validation and the service. Kept here so the
# request layer rejects nonsense before the service ever runs, and the
# service can re-assert the same limits as defence in depth.
MAX_TOTAL_SIZE: int = 10 * 1024 * 1024 * 1024  # 10 GiB hard ceiling
MIN_CHUNK_SIZE: int = 256 * 1024  # 256 KiB
MAX_CHUNK_SIZE: int = 256 * 1024 * 1024  # 256 MiB
MAX_TOTAL_CHUNKS: int = 100_000  # guards against a tiny chunk_size DoS
DEFAULT_CHUNK_SIZE: int = 8 * 1024 * 1024  # 8 MiB


class CreateSessionRequest(BaseModel):
    """Open a new resumable upload session.

    ``chunk_size`` is advisory: the client may request one, otherwise the
    server picks :data:`DEFAULT_CHUNK_SIZE`. The returned ``chunk_size``
    is authoritative and every chunk except the last must match it.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    total_size: int = Field(gt=0, le=MAX_TOTAL_SIZE)
    chunk_size: int | None = Field(default=None, ge=MIN_CHUNK_SIZE, le=MAX_CHUNK_SIZE)
    category: str = Field(default="other", max_length=64)
    sha256: str | None = Field(default=None, min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")


class SessionResponse(BaseModel):
    """Current state of a resumable upload session."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    filename: str
    category: str
    total_size: int
    chunk_size: int
    total_chunks: int
    received_chunks: list[int]
    missing_chunks: list[int]
    sha256: str | None
    status: str
    document_id: UUID | None
    created_at: datetime
    expires_at: datetime


class ChunkAcceptedResponse(BaseModel):
    """Returned after a chunk is stored (or recognised as already stored)."""

    model_config = ConfigDict(from_attributes=True)

    session_id: UUID
    chunk_index: int
    received: int
    total_chunks: int
    # True when this exact chunk was already present, so the call was a
    # no-op replay rather than a fresh write.
    duplicate: bool
    status: str


class CompleteResponse(BaseModel):
    """Returned after a successful assemble + hand-off to the document store."""

    model_config = ConfigDict(from_attributes=True)

    session_id: UUID
    document_id: UUID
    filename: str
    file_size: int
    status: str
