# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠File tags Pydantic schemas."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Allowed kinds - same enumeration as the file-manager.
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

# AECO standard category buckets. Free-form ``custom`` is allowed too.
TagCategory = Literal["discipline", "phase", "package", "custom"]

# Hex color (#abc or #aabbcc) - validated server-side so the picker
# cannot inject CSS variables.
_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def slugify(value: str) -> str:
    """Slug used for the canonical ``name`` column.

    Lowercases, replaces every run of non-alphanumeric ASCII characters
    with a single underscore, strips leading/trailing underscores. Empty
    input becomes ``"tag"`` so the unique constraint is still well-defined.
    """
    if not value:
        return "tag"
    out = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return out or "tag"


class TagBase(BaseModel):
    """Shared fields for create/response."""

    model_config = ConfigDict(str_strip_whitespace=True)

    display_name: str = Field(min_length=1, max_length=128)
    color: str = Field(default="#94a3b8", max_length=7)
    category: TagCategory | None = None

    @field_validator("color")
    @classmethod
    def _check_color(cls, v: str) -> str:
        if not _HEX_RE.match(v):
            raise ValueError(f"color must be a hex string (#abc or #aabbcc), got {v!r}")
        # Normalise to lowercase 6-char form.
        if len(v) == 4:
            v = "#" + "".join(c * 2 for c in v[1:])
        return v.lower()


class TagCreate(TagBase):
    """POST /file-tags/ body."""

    project_id: UUID
    # Optional explicit slug; if absent we slugify(display_name).
    name: str | None = Field(default=None, max_length=64)


class TagUpdate(BaseModel):
    """PATCH /file-tags/{id}/ body. All fields optional."""

    model_config = ConfigDict(str_strip_whitespace=True)

    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    color: str | None = Field(default=None, max_length=7)
    category: TagCategory | None = None

    @field_validator("color")
    @classmethod
    def _check_color(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not _HEX_RE.match(v):
            raise ValueError(f"color must be a hex string (#abc or #aabbcc), got {v!r}")
        if len(v) == 4:
            v = "#" + "".join(c * 2 for c in v[1:])
        return v.lower()


class TagResponse(BaseModel):
    """Returned tag row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    display_name: str
    color: str
    category: str | None = None
    created_at: datetime
    updated_at: datetime
    created_by_id: UUID | None = None
    assignment_count: int = 0


class TagAssignmentRequest(BaseModel):
    """POST /file-tags/{id}/assign/ + /unassign/ body."""

    file_kind: FileKindLiteral
    file_ids: list[str] = Field(min_length=1, max_length=500)


class TagAssignmentResponse(BaseModel):
    """Result of a bulk assign/unassign."""

    tag_id: UUID
    file_kind: str
    requested: int
    changed: int
    already_done: int


class TagSeedResponse(BaseModel):
    """Result of POST /file-tags/seed-defaults/."""

    project_id: UUID
    created: int
    existing: int
    total: int
    tags: list[TagResponse] = Field(default_factory=list)
