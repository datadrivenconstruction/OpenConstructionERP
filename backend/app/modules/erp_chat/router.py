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
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.dependencies import CurrentUserId, SessionDep, check_ai_rate_limit
from app.modules.erp_chat.models import ChatMessage, ChatSession
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


# ── Vector / semantic memory endpoints ───────────────────────────────────
#
# ``/vector/status/`` + ``/vector/reindex/`` are wired via the shared
# factory (see ``include_router`` at the bottom of this file).  Chat
# messages are scoped via a join through ``ChatSession.project_id``, so
# we pass a custom loader.  These endpoints have no module-permission
# check — any authenticated user can inspect / rebuild chat embeddings,
# preserving the original behaviour.


@router.get("/messages/{message_id}/similar/")
async def chat_message_similar(
    message_id: uuid.UUID,
    session: SessionDep,
    _user_id: CurrentUserId,
    limit: int = Query(default=5, ge=1, le=20),
    cross_project: bool = Query(default=True),
) -> dict[str, Any]:
    """Return chat messages semantically similar to the given one."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.core.vector_index import find_similar
    from app.modules.erp_chat.vector_adapter import chat_message_adapter

    stmt = (
        select(ChatMessage)
        .options(selectinload(ChatMessage.session))
        .where(ChatMessage.id == message_id)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Chat message not found")
    project_id = (
        str(row.session.project_id)
        if row.session is not None and getattr(row.session, "project_id", None)
        else None
    )
    hits = await find_similar(
        chat_message_adapter,
        row,
        project_id=project_id,
        cross_project=cross_project,
        limit=limit,
    )
    return {
        "source_id": str(message_id),
        "limit": limit,
        "cross_project": cross_project,
        "hits": [h.to_dict() for h in hits],
    }


# ── Mount vector status + reindex via the shared factory ────────────────
from sqlalchemy import select as _select  # noqa: E402
from sqlalchemy.orm import selectinload as _selectinload  # noqa: E402

from app.core.vector_index import COLLECTION_CHAT  # noqa: E402
from app.core.vector_routes import create_vector_routes  # noqa: E402
from app.modules.erp_chat.vector_adapter import (  # noqa: E402
    chat_message_adapter as _chat_message_adapter,
)


async def _chat_loader(session: Any, project_id: uuid.UUID | None) -> list[Any]:
    stmt = _select(ChatMessage).options(_selectinload(ChatMessage.session))
    if project_id is not None:
        stmt = stmt.join(
            ChatSession, ChatMessage.session_id == ChatSession.id
        ).where(ChatSession.project_id == project_id)
    return list((await session.execute(stmt)).scalars().all())


router.include_router(
    create_vector_routes(
        collection=COLLECTION_CHAT,
        adapter=_chat_message_adapter,
        loader=_chat_loader,
        read_permission=None,
        write_permission=None,
    )
)

