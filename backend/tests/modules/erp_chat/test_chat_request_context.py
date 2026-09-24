"""The project a chat request names reaches the model only after an access check.

The dock sends where the person is: ``locale`` and ``client_context`` with the
route and the open project, next to the older ``project_id`` field. All of it
is what the browser claims. The stream turns the project into the prompt's
"Active project" line (id, name, currency), stores it on a new chat session and
uses it as the fallback project of a proposal - so it has to pass the platform's
project access rule first. A project the caller cannot open is dropped, not
refused: the chat answers, and the project's name, id and existence stay out of
the prompt, the session row and the proposal.

The stream endpoint used to store ``project_id`` on the chat session without
any check; the stranger cases below cover that field as well.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.erp_chat.models import ChatAction, ChatSession
from app.modules.erp_chat.prompts import SYSTEM_PROMPT
from app.modules.erp_chat.schemas import StreamChatRequest
from app.modules.erp_chat.service import ERPChatService
from app.modules.projects.models import Project
from app.modules.teams.models import Team, TeamMembership
from app.modules.users.models import User
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


async def _user(session: AsyncSession, name: str, role: str = "editor") -> User:
    user = User(
        email=f"{name.lower()}-{uuid.uuid4().hex[:6]}@site.test",
        hashed_password="x",
        full_name=name,
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _project(session: AsyncSession, owner: User, name: str, currency: str = "EUR") -> Project:
    project = Project(name=name, owner_id=owner.id, currency=currency)
    session.add(project)
    await session.flush()
    return project


async def _member(session: AsyncSession, project: Project, user: User) -> None:
    team = Team(project_id=project.id, name="Site team")
    session.add(team)
    await session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=user.id, role="member"))
    await session.flush()


def _frames(chunks: list[str], event: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in "".join(chunks).split("\n\n"):
        lines = block.strip().splitlines()
        if len(lines) >= 2 and lines[0] == f"event: {event}":
            out.append(json.loads(lines[1][len("data:") :].strip()))
    return out


async def _turn(
    session: AsyncSession,
    user: User,
    request: StreamChatRequest,
    rounds: list[dict[str, Any]] | None = None,
) -> tuple[list[str], list[str]]:
    """Run one turn; return the SSE chunks and the system prompt of every provider call."""
    service = ERPChatService(session)
    queue = list(rounds or [{"content": [{"type": "text", "text": "Hello."}], "usage": {}}])
    systems: list[str] = []

    async def _resolve(_uid: str):
        return "anthropic", "test-key", None

    async def _anthropic(api_key, messages, preferred_model):  # noqa: ARG001
        systems.append(service._system_prompt)
        return queue.pop(0), 5

    with (
        patch.object(service, "_resolve_ai", new=_resolve),
        patch.object(service, "_call_anthropic", new=_anthropic),
    ):
        chunks = [c async for c in service.stream_response(str(user.id), request)]
    await session.commit()
    return chunks, systems


async def _chat_row(session: AsyncSession, chunks: list[str]) -> ChatSession:
    [frame] = _frames(chunks, "session_id")
    return (
        await session.execute(select(ChatSession).where(ChatSession.id == uuid.UUID(frame["session_id"])))
    ).scalar_one()


@pytest.mark.asyncio
async def test_the_owners_project_is_named_to_the_model(session_factory):
    async with session_factory() as session:
        owner = await _user(session, "Olga")
        project = await _project(session, owner, "Residential House", currency="CHF")

        request = StreamChatRequest.model_validate(
            {
                "message": "what is left to price?",
                "locale": "de",
                "client_context": {"route": f"/projects/{project.id}/boq", "project_id": str(project.id)},
            }
        )
        chunks, [system] = await _turn(session, owner, request)

        tail = system[len(SYSTEM_PROMPT) :]
        assert system.startswith(SYSTEM_PROMPT)
        assert '"Residential House"' in tail
        assert f"id {project.id}" in tail
        assert "currency CHF" in tail
        assert "Interface language: Deutsch (de)" in tail
        assert f"Current page: /projects/{project.id}/boq" in tail
        assert (await _chat_row(session, chunks)).project_id == project.id


@pytest.mark.asyncio
async def test_a_team_members_project_is_named_to_the_model(session_factory):
    async with session_factory() as session:
        owner = await _user(session, "Olga", role="manager")
        member = await _user(session, "Mira")
        project = await _project(session, owner, "Harbour Office")
        await _member(session, project, member)

        request = StreamChatRequest.model_validate({"message": "hi", "client_context": {"project_id": str(project.id)}})
        chunks, [system] = await _turn(session, member, request)

        assert '"Harbour Office"' in system
        assert (await _chat_row(session, chunks)).project_id == project.id


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["client_context", "project_id"])
async def test_a_strangers_project_leaks_nowhere(session_factory, field: str):
    """Neither the prompt, nor the new chat session, nor a proposal's fallback sees it."""
    async with session_factory() as session:
        owner = await _user(session, "Olga", role="admin")
        project = await _project(session, owner, "Tenant A Secret Tower")
        stranger = await _user(session, "Sam", role="manager")

        body: dict[str, Any] = {"message": "add a task to check the formwork"}
        if field == "client_context":
            body["client_context"] = {"project_id": str(project.id), "route": "/tasks"}
        else:
            body["project_id"] = str(project.id)
        propose_without_project = [
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu-1",
                        "name": "propose_create_task",
                        "input": {"title": "Check formwork"},
                    }
                ],
                "usage": {},
            },
            {"content": [{"type": "text", "text": "Which project?"}], "usage": {}},
        ]
        chunks, systems = await _turn(
            session, stranger, StreamChatRequest.model_validate(body), propose_without_project
        )

        for system in systems:
            assert "Secret Tower" not in system
            assert str(project.id) not in system
            assert "Active project: none selected" in system
        assert not _frames(chunks, "error")
        assert (await _chat_row(session, chunks)).project_id is None
        # The dropped project is not the proposal's fallback either: the spec
        # asks for a project instead of reaching one the caller cannot open.
        [result] = _frames(chunks, "tool_result")
        assert result["result"]["renderer"] == "error"
        assert result["result"]["data"]["error"] == "project_required"
        assert (await session.execute(select(ChatAction))).scalars().all() == []


@pytest.mark.asyncio
async def test_the_page_project_wins_over_the_older_field(session_factory):
    async with session_factory() as session:
        owner = await _user(session, "Olga")
        on_page = await _project(session, owner, "On The Page")
        older = await _project(session, owner, "Older Field")

        request = StreamChatRequest.model_validate(
            {"message": "hi", "project_id": str(older.id), "client_context": {"project_id": str(on_page.id)}}
        )
        chunks, [system] = await _turn(session, owner, request)

        assert '"On The Page"' in system
        assert "Older Field" not in system
        assert (await _chat_row(session, chunks)).project_id == on_page.id
