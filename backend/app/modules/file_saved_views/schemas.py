# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic schemas for the file-saved-views module."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── Filter snapshot ──────────────────────────────────────────────────────────
#
# Open-shape on purpose: every key is optional and the file-manager UI
# may add keys (e.g. ``custom_keys``) without a schema migration. We
# validate that values are JSON-serialisable but do not lock down the
# keys, mirroring how ``oe_clash_run.set_a`` and similar JSON-bag columns
# are typed elsewhere in this codebase.


class FilterSnapshot(BaseModel):
    """Serialised filter state stored under ``filter_json``."""

    model_config = ConfigDict(extra="allow")

    kind: str | None = Field(default=None, max_length=64)
    q: str | None = Field(default=None, max_length=255)
    sort: str | None = Field(default=None, max_length=32)
    extension: str | None = Field(default=None, max_length=32)
    tag_ids: list[str] = Field(default_factory=list, max_length=200)
    date_range: dict[str, Any] | None = None
    custom_keys: dict[str, Any] = Field(default_factory=dict)


# ── Create / update ──────────────────────────────────────────────────────────


class SavedViewCreate(BaseModel):
    """Create a new saved view from the current filter snapshot."""

    name: str = Field(..., min_length=1, max_length=128)
    project_id: uuid.UUID | None = None
    icon: str | None = Field(default=None, max_length=32)
    filter_json: FilterSnapshot = Field(default_factory=FilterSnapshot)
    is_pinned: bool = False
    is_shared: bool = False
    sort_order: int = 0


class SavedViewUpdate(BaseModel):
    """Patch view metadata. All fields optional — only provided keys change."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    icon: str | None = Field(default=None, max_length=32)
    filter_json: FilterSnapshot | None = None
    is_pinned: bool | None = None
    is_shared: bool | None = None
    sort_order: int | None = None


# ── Response ─────────────────────────────────────────────────────────────────


class SavedViewResponse(BaseModel):
    """Wire shape of a saved view row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID | None
    name: str
    icon: str | None
    filter_json: dict[str, Any]
    sort_order: int
    is_pinned: bool
    is_shared: bool
    last_used_at: datetime | None
    use_count: int
    created_at: datetime
    updated_at: datetime
    # True when this view was authored by the current caller (i.e.
    # ``user_id == current_user_id``). Lets the frontend distinguish
    # editable rows from shared-by-someone-else rows in the rail.
    is_own: bool = True


class SavedViewListResponse(BaseModel):
    """Paginated list wrapper."""

    items: list[SavedViewResponse]
    total: int
