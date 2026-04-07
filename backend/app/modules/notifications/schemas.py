"""Notification Pydantic schemas — request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NotificationResponse(BaseModel):
    """Single notification returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    user_id: UUID
    notification_type: str
    entity_type: str | None = None
    entity_id: str | None = None
    title_key: str
    body_key: str | None = None
    body_context: dict[str, Any] = Field(default_factory=dict)
    action_url: str | None = None
    is_read: bool = False
    read_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class NotificationListResponse(BaseModel):
    """Paginated notification list."""

    items: list[NotificationResponse]
    total: int
    unread_count: int


class MarkReadRequest(BaseModel):
    """Request body for marking notifications as read."""

    model_config = ConfigDict(str_strip_whitespace=True)

    notification_ids: list[UUID] = Field(
        default_factory=list,
        description="Optional list of IDs to mark as read. Empty = mark all.",
    )
