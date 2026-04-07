"""Collaboration Pydantic schemas — request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Mentions ─────────────────────────────────────────────────────────────


class MentionCreate(BaseModel):
    """A single @mention to include when creating a comment."""

    mentioned_user_id: UUID
    mention_type: str = Field(
        default="at_notify",
        pattern=r"^(at_notify|hash_silent)$",
    )


class MentionResponse(BaseModel):
    """Mention in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    comment_id: UUID
    mentioned_user_id: UUID
    mention_type: str
    created_at: datetime


# ── Viewpoints ───────────────────────────────────────────────────────────


class ViewpointCreate(BaseModel):
    """Create a standalone or comment-attached viewpoint."""

    entity_type: str = Field(..., min_length=1, max_length=100)
    entity_id: str = Field(..., min_length=1, max_length=36)
    viewpoint_type: str = Field(
        ...,
        pattern=r"^(pdf_section|bim_section|general)$",
    )
    data: dict[str, Any] = Field(..., description="Camera position, bbox, etc.")
    comment_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ViewpointResponse(BaseModel):
    """Viewpoint in API responses."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    entity_type: str
    entity_id: str
    viewpoint_type: str
    data: dict[str, Any]
    created_by: UUID
    comment_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Comments ─────────────────────────────────────────────────────────────


class CommentCreate(BaseModel):
    """Create a new comment."""

    entity_type: str = Field(..., min_length=1, max_length=100)
    entity_id: str = Field(..., min_length=1, max_length=36)
    text: str = Field(..., min_length=1, max_length=10000)
    comment_type: str = Field(
        default="comment",
        pattern=r"^(comment|question|decision|blocker)$",
    )
    parent_comment_id: UUID | None = None
    mentions: list[MentionCreate] = Field(default_factory=list)
    viewpoint: ViewpointCreate | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CommentUpdate(BaseModel):
    """Edit a comment (text only)."""

    text: str = Field(..., min_length=1, max_length=10000)


class CommentResponse(BaseModel):
    """Comment in API responses."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    entity_type: str
    entity_id: str
    author_id: UUID
    text: str
    comment_type: str
    parent_comment_id: UUID | None = None
    edited_at: datetime | None = None
    is_deleted: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    mentions: list[MentionResponse] = Field(default_factory=list)
    viewpoints: list[ViewpointResponse] = Field(default_factory=list)
    replies: list["CommentResponse"] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ── List response ────────────────────────────────────────────────────────


class CommentListResponse(BaseModel):
    """Paginated list of comments."""

    items: list[CommentResponse]
    total: int
