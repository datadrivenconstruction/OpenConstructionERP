# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠File Favourites Pydantic schemas - request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

FavoriteKindLiteral = Literal[
    "document",
    "photo",
    "sheet",
    "bim_model",
    "dwg_drawing",
    "takeoff",
    "report",
    "markup",
]


class FavoriteCreateRequest(BaseModel):
    """Star (or pin) a file for the current user.

    Idempotent: posting the same ``(user_id, file_kind, file_id)`` twice
    returns the existing row. ``pinned`` defaults to ``False`` so a
    one-click star never accidentally pins.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    file_kind: FavoriteKindLiteral
    file_id: str = Field(min_length=1, max_length=64)
    pinned: bool = False


class FavoriteResponse(BaseModel):
    """One favourite row returned to the client."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    project_id: UUID
    file_kind: str
    file_id: str
    pinned: bool
    created_at: datetime
    updated_at: datetime
