"""ERP Chat API routes.

Endpoints:
    POST   /erp_chat/stream/                       — SSE streaming chat with tool-calling
    GET    /erp_chat/sessions/                      — List user's chat sessions
    POST   /erp_chat/sessions/                      — Create a new chat session
    GET    /erp_chat/sessions/{session_id}/messages/ — Get messages for a session
    DELETE /erp_chat/sessions/{session_id}/          — Delete a chat session
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.dependencies import CurrentUserId, SessionDep, check_ai_rate_limit
from app.modules.erp_chat.models import ChatSession
from app.modules.erp_chat.schemas import (
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionResponse,
    SessionListResponse,
    StreamChatRequest,
)
from app.modules.erp_chat.service import ERPChatService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ERP Chat"])


@router.post("/stream/")
async def stream_chat(
    body: StreamChatRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    _remaining: int = Depends(check_ai_rate_limit),
) -> StreamingResponse:
    """Stream an AI chat response with tool-calling via SSE.

    The response is a Server-Sent Events stream with events:
    - session_id: emitted first with the chat session UUID
    - tool_start: emitted when a tool call begins
    - tool_result: emitted when a tool call completes with data
    - text: emitted with assistant text content (chunked)
    - error: emitted on errors
    - done: emitted when the stream is complete
    """
    service = ERPChatService(session)
    return StreamingResponse(
        service.stream_response(user_id, body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions/", response_model=SessionListResponse)
async def list_sessions(
    user_id: CurrentUserId,
    session: SessionDep,
) -> SessionListResponse:
    """List chat sessions for the current user, newest first."""
    service = ERPChatService(session)
    sessions, total = await service.list_sessions(user_id, limit=20)
    return SessionListResponse(
        items=[
            ChatSessionResponse(
                id=s.id,
                user_id=s.user_id,
                project_id=s.project_id,
                title=s.title,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in sessions
        ],
        total=total,
    )


@router.post("/sessions/", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: ChatSessionCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> ChatSessionResponse:
    """Create a new chat session."""
    chat_session = ChatSession(
        user_id=uuid.UUID(user_id),
        project_id=body.project_id,
        title=body.title,
    )
    session.add(chat_session)
    await session.flush()
    await session.refresh(chat_session)
    return ChatSessionResponse(
        id=chat_session.id,
        user_id=chat_session.user_id,
        project_id=chat_session.project_id,
        title=chat_session.title,
        created_at=chat_session.created_at,
        updated_at=chat_session.updated_at,
    )


@router.get("/sessions/{session_id}/messages/", response_model=list[ChatMessageResponse])
async def get_messages(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> list[ChatMessageResponse]:
    """Get all messages for a chat session."""
    service = ERPChatService(session)
    messages = await service.get_session_messages(session_id, user_id)
    return [
        ChatMessageResponse(
            id=m.id,
            session_id=m.session_id,
            role=m.role,
            content=m.content,
            tool_calls=m.tool_calls,
            tool_results=m.tool_results,
            renderer=m.renderer,
            renderer_data=m.renderer_data,
            tokens_used=m.tokens_used,
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.delete("/sessions/{session_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> None:
    """Delete a chat session and all its messages."""
    service = ERPChatService(session)
    deleted = await service.delete_session(session_id, user_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )
