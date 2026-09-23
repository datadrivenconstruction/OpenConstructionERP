"""A tool turn reads back through ``GET /sessions/{id}/messages/``.

The floating dock and the /chat page rebuild a conversation from this endpoint,
so a card that cannot be read back is a card the user loses on reload. The
assistant row stores ``tool_calls`` and ``tool_results`` as lists, one entry per
call, and a tool whose ``data`` is a list lands in ``renderer_data`` as that
list. The response schema declared all three as dicts, and Pydantic does not
turn a list into a dict, so the first tool turn of a conversation made its whole
history unreadable.

The endpoint is driven over HTTP through a minimal app that mounts only the
erp_chat router, with the session and the caller supplied by dependency
overrides, so the response model is validated exactly as in production.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.erp_chat.schemas import ChatMessageResponse, StreamChatRequest
from app.modules.erp_chat.service import ERPChatService
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session_factory():
    async with transactional_session() as base_session:
        maker = async_sessionmaker(
            bind=base_session.bind,
            class_=AsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        yield maker


def _first_frame(chunks: list[str], event: str) -> dict:
    lines = "".join(chunks).splitlines()
    for i, line in enumerate(lines):
        if line.strip() == f"event: {event}":
            return json.loads(lines[i + 1][len("data:") :].strip())
    raise AssertionError(f"no {event} frame in the stream")


async def _tool_turn(session: AsyncSession, user_id: uuid.UUID) -> str:
    """One persisted turn that called a read tool whose data is a list; returns the chat session id."""
    service = ERPChatService(session)
    calls = {"n": 0}

    async def _fake_resolve(_uid: str):
        return "anthropic", "test-key", None

    async def _fake_anthropic(api_key, messages, preferred_model):  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] == 1:
            return (
                {
                    "content": [{"type": "tool_use", "id": "tool-1", "name": "get_all_projects", "input": {}}],
                    "usage": {"input_tokens": 8, "output_tokens": 4},
                },
                12,
            )
        return (
            {"content": [{"type": "text", "text": "You have two projects."}], "usage": {"input_tokens": 8}},
            8,
        )

    async def _fake_handler(_session, _args, _uid):
        return {
            "renderer": "generic_table",
            "data": [{"name": "Tower A"}, {"name": "Tower B"}],
            "summary": "2 projects",
        }

    with (
        patch.object(service, "_resolve_ai", new=_fake_resolve),
        patch.object(service, "_call_anthropic", new=_fake_anthropic),
        patch.dict("app.modules.erp_chat.tools.TOOL_HANDLER_MAP", {"get_all_projects": _fake_handler}),
    ):
        chunks = [c async for c in service.stream_response(str(user_id), StreamChatRequest(message="list them"))]
    await session.commit()
    assert _first_frame(chunks, "done").get("message_id"), "the turn was not persisted"
    return _first_frame(chunks, "session_id")["session_id"]


def _history_app(maker: async_sessionmaker, user_id: uuid.UUID) -> FastAPI:
    from app.dependencies import get_current_user_id, get_session
    from app.modules.erp_chat.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/erp_chat")

    async def _session():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    return app


@pytest.mark.asyncio
async def test_a_tool_turn_reads_back_through_the_messages_endpoint(session_factory):
    user_id = uuid.uuid4()
    async with session_factory() as session:
        chat_id = await _tool_turn(session, user_id)

    app = _history_app(session_factory, user_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/erp_chat/sessions/{chat_id}/messages/")

    assert resp.status_code == 200, resp.text
    messages = resp.json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assistant = messages[1]
    assert assistant["tool_calls"] == [{"name": "get_all_projects", "args": {}, "id": "tool-1"}]
    assert assistant["tool_results"][0]["tool"] == "get_all_projects"
    assert assistant["tool_results"][0]["result"]["renderer"] == "generic_table"
    assert assistant["renderer"] == "generic_table"
    assert assistant["renderer_data"] == [{"name": "Tower A"}, {"name": "Tower B"}]
    assert assistant["content"] == "You have two projects."


def test_a_row_stored_with_dict_payloads_still_reads_back() -> None:
    """Rows written before the lists (or by another writer) keep loading."""
    row = ChatMessageResponse(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        role="assistant",
        content="ok",
        tool_calls={"name": "get_all_projects"},
        tool_results={"tool": "get_all_projects", "result": {"renderer": "projects_grid"}},
        renderer="projects_grid",
        renderer_data={"projects": []},
        created_at="2026-09-23T10:00:00Z",
    )

    assert row.tool_calls == {"name": "get_all_projects"}
    assert row.renderer_data == {"projects": []}
