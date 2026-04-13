"""ERP Chat Pydantic schemas — request/response models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StreamChatRequest(BaseModel):
    """Request body for the streaming chat endpoint."""

    model_config = ConfigDict(from_attributes=True)

    session_id: UUID | None = None
    message: str = Field(..., min_length=1, max_length=5000)
    project_id: UUID | None = None
    conversation_history: list[dict] | None = None


class ChatSessionResponse(BaseModel):
    """Chat session returned from the API."""

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
