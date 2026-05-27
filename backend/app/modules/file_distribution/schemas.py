# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic schemas for the file-distribution module."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# ── Cross-project search ─────────────────────────────────────────────────────


SearchHitKind = Literal["document", "sheet", "photo"]


class SearchHit(BaseModel):
    """One result row from cross-project file search."""

    project_id: uuid.UUID
    project_name: str
    file_id: uuid.UUID
    kind: SearchHitKind
    canonical_name: str
    snippet: str = ""
    score: float = 0.0


class SearchResponse(BaseModel):
    items: list[SearchHit]
    total: int
    # True when the ``file_search`` module was available and its full
    # content index was consulted; false when we fell back to
    # canonical_name only. The frontend surfaces this as a hint chip
    # so the user knows whether the search is "metadata only".
    used_content_index: bool


# ── Distribution lists ───────────────────────────────────────────────────────


MEMBER_ROLES = ("for_review", "fyi", "for_construction")


class DistributionMemberCreate(BaseModel):
    email: EmailStr
    display_name: str | None = Field(default=None, max_length=128)
    role: str | None = Field(default=None, max_length=32)


class DistributionMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    list_id: uuid.UUID
    email: str
    display_name: str | None
    role: str | None
    created_at: datetime


class DistributionListCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    project_id: uuid.UUID | None = None
    is_shared: bool = False
    members: list[DistributionMemberCreate] = Field(default_factory=list)


class DistributionListUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    is_shared: bool | None = None


class DistributionListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    project_id: uuid.UUID | None
    name: str
    description: str | None
    is_shared: bool
    members: list[DistributionMemberResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    is_own: bool = True


class DistributionListListResponse(BaseModel):
    items: list[DistributionListResponse]
    total: int


# ── Subscriptions ────────────────────────────────────────────────────────────


NOTIFY_EVENTS = ("created", "updated", "deleted")


class SubscriptionCreate(BaseModel):
    project_id: uuid.UUID
    file_kind: str = Field(default="*", max_length=32)
    subscriber_email: EmailStr
    subscriber_user_id: uuid.UUID | None = None
    notify_on: list[str] = Field(default_factory=lambda: list(NOTIFY_EVENTS))
    active: bool = True


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    file_kind: str
    subscriber_email: str
    subscriber_user_id: uuid.UUID | None
    notify_on: list[str]
    active: bool
    created_at: datetime
    updated_at: datetime


class SubscriptionListResponse(BaseModel):
    items: list[SubscriptionResponse]
    total: int
