"""Deepen-wave regression tests for the erp_chat streaming endpoint.

Two behaviours the chat-deepen wave added end to end:

1. The ``done`` SSE event now carries the persisted assistant
   ``message_id``. The /chat frontend reconciles its optimistic bubble id
   against this so per-turn thumbs feedback POSTs land on a real row
   (previously they 404'd on a client UUID and the whole T8 feedback +
   admin-observability pipeline was unreachable from /chat).

2. A tool-using turn persists the ``renderer`` + ``renderer_data`` of the
   last non-error tool result onto the assistant row, so resuming a
   session can rebuild the right-hand data panel - and the persisted
   ``message_id`` returned in ``done`` is exactly that assistant row's id.

Both run with the LLM provider mocked so the suite is offline. They reuse
the same transactional PostgreSQL fixture pattern as ``test_erp_chat.py``.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.erp_chat.models import ChatMessage
from app.modules.erp_chat.schemas import StreamChatRequest
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


def _parse_done_payload(joined: str) -> dict:
    """Extract the JSON payload of the ``done`` SSE frame from a stream."""
    lines = joined.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "event: done":
            # The data line follows immediately.
            for data_line in lines[i + 1 :]:
                if data_line.startswith("data:"):
                    return json.loads(data_line[len("data:") :].strip())
    raise AssertionError(f"no done frame found in stream:\n{joined}")


@pytest.mark.asyncio
async def test_done_event_carries_persisted_assistant_message_id(session_factory):
    """The ``done`` payload's ``message_id`` must equal the persisted
    assistant ChatMessage id (so the client can feedback against it)."""
    user_id = uuid.uuid4()
    async with session_factory() as session:
        service = ERPChatService(session)

        async def _fake_resolve(_uid: str):
            return "anthropic", "test-key", None

        async def _fake_anthropic(api_key, messages, preferred_model):  # noqa: ARG001
            service._record_turn_metrics(tokens_in=10, tokens_out=5, cache_hit=False, latency_ms=50)
            return (
                {
                    "content": [{"type": "text", "text": "Hello from the assistant."}],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
                15,
            )

        with (
            patch.object(service, "_resolve_ai", new=_fake_resolve),
            patch.object(service, "_call_anthropic", new=_fake_anthropic),
        ):
            req = StreamChatRequest(message="hi")
            chunks: list[str] = []
            async for c in service.stream_response(str(user_id), req):
                chunks.append(c)
            await session.commit()

        joined = "".join(chunks)
        done = _parse_done_payload(joined)

        assert done.get("message_id"), f"done frame missing message_id: {done}"

        # The id must match the persisted assistant row.
        assistant = (await session.execute(select(ChatMessage).where(ChatMessage.role == "assistant"))).scalar_one()
        assert done["message_id"] == str(assistant.id)


@pytest.mark.asyncio
async def test_tool_turn_persists_renderer_and_returns_its_message_id(session_factory):
    """A turn that calls a read tool persists the tool's renderer +
    renderer_data on the assistant row, and the ``done`` message_id points
    at that same row - the data the /chat history reconstruction needs."""
    user_id = uuid.uuid4()
    async with session_factory() as session:
        service = ERPChatService(session)

        async def _fake_resolve(_uid: str):
            return "anthropic", "test-key", None

        # Round 1: model asks to call get_all_projects. Round 2: it answers.
        calls = {"n": 0}

        async def _fake_anthropic(api_key, messages, preferred_model):  # noqa: ARG001
            service._record_turn_metrics(tokens_in=8, tokens_out=4, cache_hit=False, latency_ms=30)
            calls["n"] += 1
            if calls["n"] == 1:
                return (
                    {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tool-1",
                                "name": "get_all_projects",
                                "input": {},
                            }
                        ],
                        "usage": {"input_tokens": 8, "output_tokens": 4},
                    },
                    12,
                )
            return (
                {
                    "content": [{"type": "text", "text": "You have projects."}],
                    "usage": {"input_tokens": 8, "output_tokens": 4},
                },
                12,
            )

        # Stub the tool handler so we don't depend on project seed data, and
        # so the renderer name is deterministic.
        async def _fake_handler(_session, _args, _uid):
            return {
                "renderer": "projects_grid",
                "data": {"projects": [{"id": "p1", "name": "Berlin Tower"}], "total": 1},
                "summary": "1 project found",
            }

        with (
            patch.object(service, "_resolve_ai", new=_fake_resolve),
            patch.object(service, "_call_anthropic", new=_fake_anthropic),
            patch.dict(
                "app.modules.erp_chat.tools.TOOL_HANDLER_MAP",
                {"get_all_projects": _fake_handler},
            ),
        ):
            req = StreamChatRequest(message="show projects")
            chunks: list[str] = []
            async for c in service.stream_response(str(user_id), req):
                chunks.append(c)
            await session.commit()

        joined = "".join(chunks)
        assert "event: tool_result" in joined
        done = _parse_done_payload(joined)

        assistant = (await session.execute(select(ChatMessage).where(ChatMessage.role == "assistant"))).scalar_one()

        # Renderer + data were persisted for history reconstruction.
        assert assistant.renderer == "projects_grid"
        assert assistant.renderer_data == {
            "projects": [{"id": "p1", "name": "Berlin Tower"}],
            "total": 1,
        }
        # And done.message_id points at that row.
        assert done["message_id"] == str(assistant.id)


@pytest.mark.asyncio
async def test_a_proposal_turn_attaches_its_message_to_its_proposals(session_factory):
    """The proposals of one turn share a batch and point at the assistant
    message that carried them, the same id ``done`` hands the client - so the
    card in a reloaded conversation and the row in the Changes list are one."""
    from app.modules.boq.models import BOQ, Position
    from app.modules.erp_chat.models import ChatAction
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    async with session_factory() as session:
        user = User(
            email=f"est-{uuid.uuid4().hex[:6]}@test.io", hashed_password="x", full_name="Estimator", role="editor"
        )
        session.add(user)
        await session.flush()
        project = Project(name="Residential House", owner_id=user.id, currency="EUR")
        session.add(project)
        await session.flush()
        session.add(BOQ(project_id=project.id, name="Shell and core"))
        await session.flush()

        service = ERPChatService(session)
        line = {"description": "Concrete wall C30/37", "unit": "m2", "quantity": 12.5, "unit_rate": 95.5}
        rounds = [
            {
                "content": [
                    {"type": "tool_use", "id": "tu-1", "name": "propose_add_boq_position", "input": line},
                    {
                        "type": "tool_use",
                        "id": "tu-2",
                        "name": "propose_add_boq_position",
                        "input": {**line, "description": "Formwork for the wall", "unit_rate": 30},
                    },
                ],
                "usage": {},
            },
            {"content": [{"type": "text", "text": "Two lines are waiting for your approval."}], "usage": {}},
        ]

        async def _fake_resolve(_uid: str):
            return "anthropic", "test-key", None

        async def _fake_anthropic(api_key, messages, preferred_model):  # noqa: ARG001
            return rounds.pop(0), 12

        with (
            patch.object(service, "_resolve_ai", new=_fake_resolve),
            patch.object(service, "_call_anthropic", new=_fake_anthropic),
        ):
            # The project comes from the page the person is on, not from the tool arguments.
            req = StreamChatRequest(message="add the wall and its formwork", client_context={"project_id": project.id})
            chunks = [c async for c in service.stream_response(str(user.id), req)]
        await session.commit()

        done = _parse_done_payload("".join(chunks))
        actions = (await session.execute(select(ChatAction).order_by(ChatAction.created_at))).scalars().all()
        assert len(actions) == 2, "".join(chunks)
        assert {a.status for a in actions} == {"proposed"}
        assert {str(a.message_id) for a in actions} == {done["message_id"]}
        assert len({a.batch_id for a in actions}) == 1 and actions[0].batch_id
        assert {a.project_id for a in actions} == {project.id}
        assert (await session.execute(select(Position))).scalars().all() == []
