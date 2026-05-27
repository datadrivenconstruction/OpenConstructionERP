# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Comments Pydantic schemas — request/response models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Constants ────────────────────────────────────────────────────────────

# Allowed FileKind values (kept in lockstep with frontend
# ``features/file-manager/types.ts`` ``FileKind`` union).
ALLOWED_FILE_KINDS: tuple[str, ...] = (
    "document",
    "photo",
    "sheet",
    "bim_model",
    "dwg_drawing",
    "takeoff",
    "report",
    "markup",
)
_FILE_KIND_PATTERN = r"^(document|photo|sheet|bim_model|dwg_drawing|takeoff|report|markup)$"

# Sane body length: a comment is not a wiki page. 10k chars covers the
# longest reasonable structured triage note without inviting abuse.
_MAX_BODY = 10_000
# Maximum nesting depth at which we still render replies as nested — the
# service flattens deeper threads onto the deepest visible parent.
MAX_NESTING_DEPTH = 8
# A PDF page is one-indexed; 100k pages covers every real-world document.
_MAX_PAGE = 100_000


# ── Comment create / update ──────────────────────────────────────────────


class FileCommentCreate(BaseModel):
    """Body for ``POST /file-comments/``."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    project_id: UUID
    file_kind: str = Field(..., pattern=_FILE_KIND_PATTERN)
    file_id: str = Field(..., min_length=1, max_length=255)
    # Pre-Epic-C label snapshot (V01 etc.) — kept for one release as a
    # fallback. Prefer ``file_version_id`` below.
    file_version_snapshot: str | None = Field(default=None, max_length=32)
    # Epic C — explicit version pin. When omitted the service looks up
    # the chain head and uses it, so comments default to the current
    # revision (the usual behaviour). Clients can pin to a historical
    # version by passing this explicitly (e.g. when annotating an old
    # revision still visible in the dropdown).
    file_version_id: UUID | None = None
    parent_id: UUID | None = None
    body: str = Field(..., min_length=1, max_length=_MAX_BODY)
    page_number: int | None = Field(default=None, ge=1, le=_MAX_PAGE)
    anchor_x: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    anchor_y: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)


class FileCommentUpdate(BaseModel):
    """Body for ``PATCH /file-comments/{id}/``.

    ``body`` is an optional edit, ``resolved`` is an optional toggle —
    both can be set in one request (edit + resolve in one round-trip).
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    body: str | None = Field(default=None, min_length=1, max_length=_MAX_BODY)
    resolved: bool | None = None


# ── Mention response ─────────────────────────────────────────────────────


class FileCommentMentionResponse(BaseModel):
    """A resolved @mention inside a comment."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    comment_id: UUID
    mentioned_user_id: UUID
    notified_at: datetime | None = None
    created_at: datetime


# ── Comment response ─────────────────────────────────────────────────────


class FileCommentResponse(BaseModel):
    """A comment row returned from the API. Replies are flat (parent_id)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    file_kind: str
    file_id: str
    file_version_snapshot: str | None = None
    file_version_id: UUID | None = None
    parent_id: UUID | None = None
    author_id: UUID
    body: str
    page_number: int | None = None
    anchor_x: float | None = None
    anchor_y: float | None = None
    resolved: bool = False
    resolved_at: datetime | None = None
    resolved_by_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    mentions: list[FileCommentMentionResponse] = Field(default_factory=list)


class FileCommentThread(FileCommentResponse):
    """A top-level comment plus its (recursively-flattened) replies."""

    replies: list[FileCommentThread] = Field(default_factory=list)


class FileCommentListResponse(BaseModel):
    """``GET /file-comments/?kind=&file_id=`` payload — top-level threads."""

    file_kind: str
    file_id: str
    threads: list[FileCommentThread]
    total: int


class UnreadMentionItem(BaseModel):
    """One entry in ``GET /file-comments/mentions/me/``."""

    model_config = ConfigDict(from_attributes=True)

    mention_id: UUID
    comment_id: UUID
    project_id: UUID
    file_kind: str
    file_id: str
    author_id: UUID
    body_excerpt: str
    created_at: datetime


class UnreadMentionListResponse(BaseModel):
    """Container so the endpoint matches the rest of the file-* surface."""

    items: list[UnreadMentionItem]
    total: int
