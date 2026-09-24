# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""ERP Chat API routes.

Endpoints:
    POST   /erp_chat/stream/                       - SSE streaming chat with tool-calling
    GET    /erp_chat/sessions/                      - List user's chat sessions
    POST   /erp_chat/sessions/                      - Create a new chat session
    GET    /erp_chat/sessions/{session_id}/messages/ - Get messages for a session
    DELETE /erp_chat/sessions/{session_id}/          - Delete a chat session

Assistant proposals (``actions/router.py``, included at the end of this file).
The model's ``propose_*`` tools store a proposal and nothing else; a person
reviews it and applies it here, under the gates of the record's own REST route:
    GET    /erp_chat/actions/                       - List proposals (filters, counts)
    GET    /erp_chat/actions/{id}/                  - One proposal
    PATCH  /erp_chat/actions/{id}/                  - Edit a proposal before applying it
    POST   /erp_chat/actions/{id}/apply/            - Apply it as the caller
    POST   /erp_chat/actions/{id}/reject/           - Reject it
    POST   /erp_chat/actions/{id}/revert/           - Undo an applied proposal
    POST   /erp_chat/actions/apply-batch/           - Apply several, each on its own
"""

import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    check_ai_rate_limit,
    verify_project_access,
)
from app.modules.erp_chat.models import ChatMessage, ChatSession
from app.modules.erp_chat.schemas import (
    AdminStatsResponse,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionResponse,
    FeedbackRequest,
    FeedbackResponse,
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

    Does NOT use the request-scoped SessionDep: Starlette's BaseHTTPMiddleware
    interacts badly with StreamingResponse and cancels the dependency session
    between chunks, killing every ``await session.flush()`` inside the agent
    loop with ``CancelledError``. Instead the generator opens its own session
    whose lifetime matches the stream. The service commits on it mid-stream
    when the model proposes a change, so the card's Apply request (another
    session) sees the proposal as soon as the card is on screen.

    ``project_id`` and ``client_context.project_id`` are what the browser
    claims. The service checks the project against the caller's access before
    naming it to the model or storing it on a new chat session; a project the
    caller cannot open is dropped, and the chat answers without it.
    """
    from app.database import async_session_factory

    async def stream() -> AsyncGenerator[str, None]:
        async with async_session_factory() as session:
            service = ERPChatService(session)
            try:
                async for chunk in service.stream_response(user_id, body):
                    yield chunk
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return StreamingResponse(
        stream(),
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
    if body.project_id is not None:
        await verify_project_access(body.project_id, user_id, session)
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
# check - any authenticated user can inspect / rebuild chat embeddings,
# preserving the original behaviour.


@router.get("/messages/{message_id}/similar/")
async def chat_message_similar(
    message_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    limit: int = Query(default=10, ge=1, le=100),
    cross_project: bool = Query(default=True),
) -> dict[str, Any]:
    """Return chat messages semantically similar to the given one.

    SECURITY: chat is private to its owner. The unified vector payload for
    chat carries no ``user_id`` (see ``vector_adapter.py``), so a raw
    similarity search would surface other users' chat text - even within a
    shared project, and across the whole tenant when ``cross_project`` is
    set. This endpoint therefore enforces own-scope on two levels:

    1. The source ``ChatMessage`` must belong to a ``ChatSession`` owned by
       the caller (IDOR guard - 404 on mismatch, never leaking the
       existence of another account's message UUID).
    2. Every returned hit is re-resolved back to its owning ``ChatSession``
       and dropped unless that session's ``user_id`` equals the caller's.
       This is independent of the ``cross_project`` flag, so even a
       same-project teammate's chat can never come back.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.core.vector_index import find_similar
    from app.modules.erp_chat.vector_adapter import chat_message_adapter

    stmt = select(ChatMessage).options(selectinload(ChatMessage.session)).where(ChatMessage.id == message_id)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Chat message not found")
    # IDOR guard: the message's session must belong to the current user.
    # Treat ownership mismatch as 404 - never leak the existence of a
    # message owned by a different account.
    if row.session is None or str(row.session.user_id) != str(user_id):
        raise HTTPException(status_code=404, detail="Chat message not found")
    project_id = (
        str(row.session.project_id) if row.session is not None and getattr(row.session, "project_id", None) else None
    )
    # Over-fetch candidates so that post-filtering down to the caller's own
    # sessions still leaves a useful number of results.
    raw_hits = await find_similar(
        chat_message_adapter,
        row,
        project_id=project_id,
        cross_project=cross_project,
        limit=max(limit * 5, limit),
    )

    # Re-resolve each hit's owning session and keep only the caller's own
    # chat. We map hit message-id -> owning user via a single query rather
    # than trusting the (user-less) vector payload.
    hit_ids: list[uuid.UUID] = []
    for h in raw_hits:
        try:
            hit_ids.append(uuid.UUID(str(h.id)))
        except (TypeError, ValueError):
            continue
    owned_ids: set[str] = set()
    if hit_ids:
        owner_stmt = (
            select(ChatMessage.id)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(ChatMessage.id.in_(hit_ids), ChatSession.user_id == uuid.UUID(str(user_id)))
        )
        owned_ids = {str(mid) for mid in (await session.execute(owner_stmt)).scalars().all()}

    hits = [h for h in raw_hits if str(h.id) in owned_ids][:limit]
    return {
        "source_id": str(message_id),
        "limit": limit,
        "cross_project": cross_project,
        "hits": [h.to_dict() for h in hits],
    }


# ── T8: Per-turn feedback + admin observability ──────────────────────────


@router.post(
    "/messages/{message_id}/feedback/",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_message_feedback(
    message_id: uuid.UUID,
    body: FeedbackRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> FeedbackResponse:
    """Record a thumbs up/down on a single assistant message.

    Idempotent per ``(message_id, user_id)`` - re-submitting flips the
    rating in place. The IDOR guard inside the service treats messages
    owned by another user as 404 to avoid leaking existence.
    """
    service = ERPChatService(session)
    try:
        row = await service.submit_feedback(
            message_id=message_id,
            user_id=user_id,
            rating=body.rating,
            comment=body.comment,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return FeedbackResponse(
        id=row.id,
        message_id=row.message_id,
        user_id=row.user_id,
        rating=row.rating,
        comment=row.comment,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get(
    "/admin/stats/",
    response_model=AdminStatsResponse,
    dependencies=[Depends(RequirePermission("erp_chat.admin"))],
)
async def admin_stats(
    session: SessionDep,
    window_days: int = Query(default=30, ge=1, le=365),
) -> AdminStatsResponse:
    """Return the T8 observability dashboard rollup.

    Manager+ only (admin role bypasses all permission checks). Covers
    token spend, prompt-cache hit rate, thumbs feedback totals, top-5
    user prompts that received thumbs-down, and a per-day breakdown.
    """
    service = ERPChatService(session)
    stats = await service.get_admin_stats(window_days=window_days)
    return AdminStatsResponse(**stats)


# ── Mount vector status + reindex via the shared factory ────────────────
from sqlalchemy import Select as _Select  # noqa: E402
from sqlalchemy import select as _select  # noqa: E402
from sqlalchemy.orm import selectinload as _selectinload  # noqa: E402

from app.core.vector_index import COLLECTION_CHAT  # noqa: E402
from app.core.vector_routes import create_vector_routes  # noqa: E402
from app.modules.erp_chat.vector_adapter import (  # noqa: E402
    chat_message_adapter as _chat_message_adapter,
)


async def _chat_statement(_session: Any, project_id: uuid.UUID | None) -> _Select[Any]:
    """Return the SELECT over chat messages, scoped through their session.

    Hands back the statement, not its rows: the factory is what orders, pages
    and releases it, and a scope that returned a list would have read every
    message in the deployment into memory before the first one was embedded.
    """
    stmt = _select(ChatMessage).options(_selectinload(ChatMessage.session))
    if project_id is not None:
        stmt = stmt.join(ChatSession, ChatMessage.session_id == ChatSession.id).where(
            ChatSession.project_id == project_id
        )
    return stmt


router.include_router(
    create_vector_routes(
        collection=COLLECTION_CHAT,
        adapter=_chat_message_adapter,
        statement_factory=_chat_statement,
        read_permission=None,
        write_permission=None,
    )
)

# ── Assistant proposals: review, apply, reject, undo (/actions/) ─────────
from app.modules.erp_chat.actions.router import router as _actions_router  # noqa: E402

router.include_router(_actions_router)
