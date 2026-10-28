# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Request bodies of the project handbook API. Responses are plain dicts built by the service."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HandbookSet(_In):
    """Create the handbook. A missing catalogue means the pack's default, else the neutral one."""

    catalogue_source: str = "shipped"
    catalogue_id: str | None = None
    catalogue_version: int | None = None
    title: str = Field(default="", max_length=255)
    edition: str = Field(default="", max_length=120)


class HandbookPatch(_In):
    title: str | None = Field(default=None, max_length=255)
    edition: str | None = Field(default=None, max_length=120)


class ChapterPatch(_In):
    """Fields of a chapter. Only the fields sent are changed; ``owner_id: null`` clears the owner."""

    title: str | None = Field(default=None, max_length=255)
    content: str | None = Field(default=None, max_length=200_000)
    owner_id: uuid.UUID | None = None


class PlaceDocument(_In):
    """File a document: into the folder with this code, else the folder of the area or subject."""

    document_id: uuid.UUID
    folder_code: str | None = Field(default=None, max_length=120)
    subject: str | None = Field(default=None, max_length=64)
    area_code: str | None = Field(default=None, max_length=64)


class Page(BaseModel):
    items: list[Any]
    total: int
    offset: int = 0
    limit: int = 0
