"""PG: a proposal the chat stream makes is there for another connection before the stream ends.

The card's Apply request runs on a connection of its own while the chat stream
is still open - the model may still be writing its answer. So the stream stores
the proposal on its own session, the one that created the chat session row
(the proposal's foreign key points at that row, and a write from another
session would fail on it while the row is uncommitted), and commits before it
sends the card.

Against real PostgreSQL, with a fresh database per test:

* mid-stream, a second connection reads the proposal and its chat session, and
  applies it through the lifecycle service; the stream then finishes and
  links the proposal to its assistant message;
* the stream's session expires its objects on commit here, unlike the
  production factory, so a turn that kept using a stale chat-session object
  after the mid-stream commit would fail on a lazy load instead of passing;
* a turn that fails after proposing, and a client that goes away right after
  the card, both leave the proposal committed, without a message, for the
  Changes list.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.boq.models import BOQ, Position
from app.modules.erp_chat.actions.service import ChatActionService
from app.modules.erp_chat.models import ChatAction, ChatSession
from app.modules.erp_chat.schemas import StreamChatRequest
from app.modules.erp_chat.service import ERPChatService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import isolated_engine


@pytest_asyncio.fixture
async def engine():
    async with isolated_engine() as eng:
        yield eng


@pytest.fixture(autouse=True)
def _permissions() -> None:
    """The registry the apply gates read; the app fills it on startup, tests do not boot the app."""
    from app.modules.boq.permissions import register_boq_permissions
    from app.modules.tasks.permissions import register_tasks_permissions

    register_boq_permissions()
    register_tasks_permissions()


@pytest.fixture(autouse=True)
def _quiet_domain_events(monkeypatch: pytest.MonkeyPatch, no_detached_subscribers: None) -> None:
    """Keep BOQ events from reaching subscribers that open sessions on another database."""
    import app.modules.boq.service as boq_service

    async def _record(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(boq_service, "_safe_publish", _record)


async def _estimator_with_a_bill(maker: async_sessionmaker) -> tuple[uuid.UUID, uuid.UUID]:
    async with maker() as session:
        user = User(
            email=f"estimator-{uuid.uuid4().hex[:6]}@site.test",
            hashed_password="x",
            full_name="Anna Schmidt",
            role="editor",
            is_active=True,
        )
        session.add(user)
        await session.flush()
        project = Project(name="Residential House", owner_id=user.id, currency="EUR")
        session.add(project)
        await session.flush()
        session.add(BOQ(project_id=project.id, name="Shell and core"))
        await session.commit()
        return user.id, project.id


def _frame(chunk: str) -> tuple[str, dict[str, Any]]:
    head, _, body = chunk.partition("\n")
    return head.removeprefix("event: "), json.loads(body.removeprefix("data: "))


def _service(session: AsyncSession, rounds: list[Any]) -> ERPChatService:
    service = ERPChatService(session)
    queue = list(rounds)

    async def _resolve(_uid: str):
        return "anthropic", "test-key", None

    async def _anthropic(api_key, messages, preferred_model):  # noqa: ARG001
        step = queue.pop(0)
        if isinstance(step, Exception):
            raise step
        return step, 10

    service._resolve_ai = _resolve  # type: ignore[method-assign]
    service._call_anthropic = _anthropic  # type: ignore[method-assign]
    return service


_LINE = {"description": "Concrete wall C30/37", "unit": "m2", "quantity": 12.5, "unit_rate": 95.5, "confidence": 0.8}
_PROPOSE = {
    "content": [{"type": "tool_use", "id": "tu-1", "name": "propose_add_boq_position", "input": _LINE}],
    "usage": {},
}
_ANSWER = {"content": [{"type": "text", "text": "The line waits for your approval."}], "usage": {}}


async def _until_the_card(stream) -> dict[str, Any]:
    """Iterate the stream up to its first ``tool_result`` frame and leave it suspended there."""
    async for chunk in stream:
        event, payload = _frame(chunk)
        if event == "tool_result":
            return payload["result"]
    raise AssertionError("the stream ended without a tool_result frame")


async def _proposals(maker: async_sessionmaker) -> list[ChatAction]:
    async with maker() as session:
        return list((await session.execute(select(ChatAction))).scalars().all())


async def _lines(maker: async_sessionmaker) -> int:
    async with maker() as session:
        return int((await session.execute(select(func.count()).select_from(Position))).scalar_one())


@pytest.mark.asyncio
async def test_a_proposal_is_there_for_another_connection_before_the_stream_ends(engine) -> None:
    reader = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # Expiring on commit on purpose: the production factory does not, so only
    # this setting shows whether the stream re-reads what a commit expired.
    stream_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=True)
    user_id, project_id = await _estimator_with_a_bill(reader)

    async with stream_maker() as stream_session:
        request = StreamChatRequest.model_validate(
            {"message": "add the wall", "locale": "en", "client_context": {"project_id": str(project_id)}}
        )
        stream = _service(stream_session, [_PROPOSE, _ANSWER]).stream_response(str(user_id), request)

        card = await _until_the_card(stream)
        assert card["renderer"] == "action_proposal", card
        action_id = uuid.UUID(card["data"]["id"])

        # The stream is suspended mid-turn. Another connection sees the
        # proposal and the chat session it points at...
        async with reader() as other:
            row = (await other.execute(select(ChatAction).where(ChatAction.id == action_id))).scalar_one()
            assert row.status == "proposed"
            assert row.message_id is None
            chat = (await other.execute(select(ChatSession).where(ChatSession.id == row.session_id))).scalar_one()
            assert chat.user_id == user_id
            assert chat.project_id == project_id
            # ...and applies it, the way the card's Apply request does.
            actions = ChatActionService(other)
            applied = await actions.apply(action_id, await actions.viewer(user_id))
            assert applied.status == "applied", applied.error
            await other.commit()

        rest = [_frame(chunk) async for chunk in stream]

    assert "error" not in [event for event, _ in rest], rest
    done = next(payload for event, payload in rest if event == "done")
    assert done["message_id"]
    [row] = await _proposals(reader)
    assert row.status == "applied"
    assert str(row.message_id) == done["message_id"]
    assert await _lines(reader) == 1

    # The applied change is on the project's Timeline, as the page receives it.
    from app.modules.timeline.router import _to_entry
    from app.modules.timeline.service import get_project_timeline

    async with reader() as check:
        [entry] = [_to_entry(r) for r in await get_project_timeline(check, project_id=project_id, modules=["erp_chat"])]
    assert (entry.module, entry.entity_type, entry.action) == ("erp_chat", "position", "created")
    assert (entry.parent_entity_type, entry.parent_entity_id) == ("project", str(project_id))
    assert entry.actor_id == user_id
    assert entry.metadata["via"] == "ai_assistant"
    assert entry.metadata["ai_action_id"] == str(action_id)


@pytest.mark.asyncio
async def test_a_turn_that_fails_after_proposing_keeps_its_proposal(engine) -> None:
    reader = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    user_id, project_id = await _estimator_with_a_bill(reader)

    async with reader() as stream_session:
        request = StreamChatRequest.model_validate({"message": "add the wall", "project_id": str(project_id)})
        service = _service(stream_session, [_PROPOSE, RuntimeError("provider fell over")])
        frames = [_frame(chunk) async for chunk in service.stream_response(str(user_id), request)]
        # No commit after the stream, as when the router never gets there:
        # what the stream did not commit itself is rolled back on close.

    events = [event for event, _ in frames]
    assert "error" in events and events[-1] == "done"
    assert [(r.status, r.message_id) for r in await _proposals(reader)] == [("proposed", None)]
    assert await _lines(reader) == 0


@pytest.mark.asyncio
async def test_a_client_that_goes_away_after_the_card_keeps_the_proposal(engine) -> None:
    reader = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    user_id, project_id = await _estimator_with_a_bill(reader)

    async with reader() as stream_session:
        request = StreamChatRequest.model_validate({"message": "add the wall", "project_id": str(project_id)})
        stream = _service(stream_session, [_PROPOSE, _ANSWER]).stream_response(str(user_id), request)
        card = await _until_the_card(stream)
        # The server closes the generator at the frame it was suspended on.
        await stream.aclose()

    assert card["renderer"] == "action_proposal", card
    [row] = await _proposals(reader)
    assert (str(row.id), row.status, row.message_id) == (card["data"]["id"], "proposed", None)
    async with reader() as check:
        chat = (await check.execute(select(ChatSession).where(ChatSession.id == row.session_id))).scalar_one()
    assert chat.project_id == project_id
    assert await _lines(reader) == 0
