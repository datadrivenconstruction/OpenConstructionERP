"""‌⁠‍ERP Chat Pydantic schemas — request/response models."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StreamChatRequest(BaseModel):
    """‌⁠‍Request body for the streaming chat endpoint."""

    model_config = ConfigDict(from_attributes=True)

    session_id: UUID | None = None
    message: str = Field(..., min_length=1, max_length=5000)
    project_id: UUID | None = None
    conversation_history: list[dict] | None = None


class ChatSessionResponse(BaseModel):
    """‌⁠‍Chat session returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    project_id: UUID | None = None
    title: str
    created_at: datetime
    updated_at: datetime


class ChatSessionCreate(BaseModel):
    """Create a new chat session."""

    model_config = ConfigDict(from_attributes=True)

    project_id: UUID | None = None
    title: str = "New Chat"


class ChatMessageResponse(BaseModel):
    """Chat message returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    role: str
    content: str | None = None
    tool_calls: dict | None = None
    tool_results: dict | None = None
    renderer: str | None = None
    renderer_data: dict | None = None
    tokens_used: int = 0
    created_at: datetime


class SessionListResponse(BaseModel):
    """Paginated list of chat sessions."""

    model_config = ConfigDict(from_attributes=True)

    items: list[ChatSessionResponse]
    total: int


# ── T8: feedback + admin observability ─────────────────────────────────────


class FeedbackRequest(BaseModel):
    """‌⁠‍Body for ``POST /v1/erp_chat/messages/{id}/feedback``."""

    model_config = ConfigDict(from_attributes=True)

    # +1 = thumbs up, -1 = thumbs down. We deliberately do *not* accept 0 —
    # to clear feedback the frontend should DELETE (future) or just leave
    # the row in place; "no rating" is the absence of a row.
    rating: Literal[-1, 1]
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    """‌⁠‍Echo of the persisted feedback row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    message_id: UUID
    user_id: UUID | None = None
    rating: int
    comment: str | None = None
    created_at: datetime
    updated_at: datetime


class DailyChatStat(BaseModel):
    """‌⁠‍One row of the admin-stats daily breakdown."""

    model_config = ConfigDict(from_attributes=True)

    date: str  # ISO date "YYYY-MM-DD"
    messages: int
    thumbs_up: int
    thumbs_down: int
    tokens: int


class NegativePromptSnippet(BaseModel):
    """‌⁠‍One of the top user-prompts that received a thumbs-down."""

    model_config = ConfigDict(from_attributes=True)

    snippet: str  # First 120 chars of the user-prompt
    thumbs_down: int  # How many distinct downvotes the linked turn drew
    message_id: UUID | None = None


class AdminStatsResponse(BaseModel):
    """‌⁠‍Admin observability rollup over a ``window_days`` window."""

    model_config = ConfigDict(from_attributes=True)

    window_days: int
    total_messages: int
    total_thumbs_up: int
    total_thumbs_down: int
    feedback_rate_pct: float  # % of assistant messages with any rating
    total_tokens_input: int
    total_tokens_output: int
    cache_hit_rate_pct: float  # % of turns where provider reported cache_hit=True
    top_negative_prompts: list[NegativePromptSnippet]
    daily_breakdown: list[DailyChatStat]
