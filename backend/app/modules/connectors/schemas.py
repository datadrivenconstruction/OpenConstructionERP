# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas for the connectors API."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConnectorSourceCreate(BaseModel):
    """Register an inbound document source for a project."""

    name: str = Field(min_length=1, max_length=200)
    # Server-local directory to watch. Required for the watched_folder kind.
    root_path: str = Field(min_length=1, max_length=1000)
    kind: str = "watched_folder"
    enabled: bool = True


class ConnectorSourceOut(BaseModel):
    """A registered connector source."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    name: str
    root_path: str
    enabled: bool
    last_synced_at: str | None
    last_result: dict | None
    created_at: datetime
    updated_at: datetime


class SyncResultOut(BaseModel):
    """Outcome of a connector sync: how the scanned files were partitioned."""

    source_id: str
    created: int
    duplicate: int
    already_known: int
    total: int
    # Ids of the Document rows created this sync (for the UI to link to).
    created_document_ids: list[str]
