"""Access around the erp_chat tools: reads for every caller, changes only as proposals.

The chat once had one tool that wrote: ``create_boq_item`` added a BOQ line on
the model's word, behind a manager-only gate in the dispatcher. It is gone. A
change is now a ``propose_*`` tool from the action registry. It stores a
proposal and nothing else, and a person applies it later from its card, under
the gates of the record's own REST route. So the dispatcher gate no longer
decides who may change what; the person who clicks Apply does. Covered here:

* a project member who is not a manager can propose, and the proposal writes
  no domain row: the BOQ has no new line until someone applies it;
* a stranger to the project gets the 404-style access error, the same card as
  for a project that does not exist, never the manager card, and nothing is
  stored;
* read tools stay open to any caller (their handlers check project access);
* no tool is marked ``write`` any more, and the manager gate is still the
  fail-closed default for one that would be.

The turns run through ``ERPChatService.stream_response`` with only the provider
faked, on a throwaway PostgreSQL database (``tests._pg.isolated_engine``), so the
stream commits for real and a second session reads what it committed.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests._pg import isolated_engine

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session_factory():
    """Per-test throwaway PostgreSQL database, cloned from the schema-loaded
    template.

    The turns below commit on the stream's session and are read back through
    another one, so the test needs a real database with cross-connection
    commit visibility (not a savepoint-rolled-back shared session). The
    template already carries every module table, so Project / User / Team /
    TeamMembership / BOQ / ChatAction rows can coexist.
    """
    async with isolated_engine() as engine:
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield maker


@pytest.fixture(autouse=True)
def _permissions() -> None:
    """The permission registry the proposal card reads; the app fills it on startup, tests do not boot it."""
    from app.modules.boq.permissions import register_boq_permissions
    from app.modules.tasks.permissions import register_tasks_permissions

    register_boq_permissions()
    register_tasks_permissions()


async def _make_user(maker, *, email: str, role: str) -> str:
    """Insert a user with the given global role; return UUID string."""
    from app.modules.users.models import User

    async with maker() as session:
        user = User(
            email=email,
            hashed_password="x",
            full_name=email.split("@", 1)[0],
            role=role,
            is_active=True,
        )
        session.add(user)
        await session.flush()
        await session.commit()
        return str(user.id)


async def _make_project(maker, *, owner_id: str, name: str) -> str:
    """Insert a project with the given owner; return UUID string."""
    from app.modules.projects.models import Project

    async with maker() as session:
        project = Project(
            name=name,
            owner_id=uuid.UUID(owner_id),
            currency="EUR",
        )
        session.add(project)
        await session.flush()
        await session.commit()
        return str(project.id)


async def _make_member(maker, *, project_id: str, user_id: str) -> None:
    """Put a user on the project's team with the plain ``member`` role."""
    from app.modules.teams.models import Team, TeamMembership

    async with maker() as session:
        team = Team(project_id=uuid.UUID(project_id), name="Site team")
        session.add(team)
        await session.flush()
        session.add(TeamMembership(team_id=team.id, user_id=uuid.UUID(user_id), role="member"))
        await session.commit()


async def _make_boq(maker, *, project_id: str, name: str = "Default BOQ") -> str:
    """Insert an empty BOQ on a project so a proposed line has a bill to go to. Returns BOQ UUID string."""
    from app.modules.boq.models import BOQ

    async with maker() as session:
        boq = BOQ(
            project_id=uuid.UUID(project_id),
            name=name,
        )
        session.add(boq)
        await session.flush()
        await session.commit()
        return str(boq.id)


async def _count(maker, model, *where) -> int:
    async with maker() as session:
        stmt = select(func.count()).select_from(model)
        if where:
            stmt = stmt.where(*where)
        return int((await session.execute(stmt)).scalar_one())


def _frames(chunks: list[str], event: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in "".join(chunks).split("\n\n"):
        lines = block.strip().splitlines()
        if len(lines) >= 2 and lines[0] == f"event: {event}":
            out.append(json.loads(lines[1][len("data:") :].strip()))
    return out


async def _turn(maker, user_id: str, tool_name: str, args: dict[str, Any]) -> list[str]:
    """One chat turn in which the model calls ``tool_name`` once, then answers."""
    from app.modules.erp_chat.schemas import StreamChatRequest
    from app.modules.erp_chat.service import ERPChatService

    rounds = [
        {"content": [{"type": "tool_use", "id": "tu-1", "name": tool_name, "input": args}], "usage": {}},
        {"content": [{"type": "text", "text": "Prepared; it waits for your approval."}], "usage": {}},
    ]

    async with maker() as session:
        service = ERPChatService(session)

        async def _resolve(_uid: str):
            return "anthropic", "test-key", None

        async def _anthropic(api_key, messages, preferred_model):  # noqa: ARG001
            return rounds.pop(0), 10

        with (
            patch.object(service, "_resolve_ai", new=_resolve),
            patch.object(service, "_call_anthropic", new=_anthropic),
        ):
            chunks = [c async for c in service.stream_response(user_id, StreamChatRequest(message="add a line"))]
        await session.commit()
    return chunks


def _line_args(project_id: str) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "description": "Concrete wall C30/37",
        "unit": "m2",
        "quantity": 12.5,
        "unit_rate": 95.50,
        "confidence": 0.9,
        "rationale": "The user gave all four values.",
    }


# ── Test cases ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_project_member_can_propose_and_nothing_is_written(session_factory):
    """A plain team member (global role editor) proposes a BOQ line; the bill stays unchanged."""
    from app.modules.boq.models import Position
    from app.modules.erp_chat.models import ChatAction, ChatSession

    owner_id = await _make_user(session_factory, email="owner@test.io", role="admin")
    project_id = await _make_project(session_factory, owner_id=owner_id, name="Shared Project")
    await _make_boq(session_factory, project_id=project_id)
    member_id = await _make_user(session_factory, email="member@test.io", role="editor")
    await _make_member(session_factory, project_id=project_id, user_id=member_id)

    chunks = await _turn(session_factory, member_id, "propose_add_boq_position", _line_args(project_id))

    [result] = _frames(chunks, "tool_result")
    assert result["result"]["renderer"] == "action_proposal", result
    card = result["result"]["data"]
    assert card["status"] == "proposed"
    assert (result["result"].get("data") or {}).get("i18n_key") != "chat.error.manager_required"

    async with session_factory() as session:
        action = (await session.execute(select(ChatAction))).scalar_one()
        chat = (await session.execute(select(ChatSession))).scalar_one()
    assert str(action.id) == card["id"]
    assert str(action.requested_by) == member_id
    assert str(action.project_id) == project_id
    assert action.session_id == chat.id
    assert action.status == "proposed"
    assert action.payload["description"] == "Concrete wall C30/37"
    # The domain table is untouched until a person applies the card.
    assert await _count(session_factory, Position) == 0


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_a_stranger_gets_the_access_error_and_nothing_is_stored(session_factory):
    """IDOR posture: a manager of another tenant proposing on this project gets
    the same 404-style card as for a missing project - never the manager card,
    never the project's name - and no proposal row."""
    from app.modules.boq.models import Position
    from app.modules.erp_chat.models import ChatAction

    tenant_a_id = await _make_user(session_factory, email="tenant-a@test.io", role="admin")
    project_id = await _make_project(session_factory, owner_id=tenant_a_id, name="Tenant A Secret Tower")
    await _make_boq(session_factory, project_id=project_id)
    tenant_b_id = await _make_user(session_factory, email="tenant-b@test.io", role="manager")

    chunks = await _turn(session_factory, tenant_b_id, "propose_add_boq_position", _line_args(project_id))
    missing = await _turn(session_factory, tenant_b_id, "propose_add_boq_position", _line_args(str(uuid.uuid4())))

    [result] = _frames(chunks, "tool_result")
    assert result["result"]["renderer"] == "error", result
    payload = result["result"]["data"]
    assert payload["error"] == "project_not_found"
    assert payload.get("i18n_key") != "chat.error.manager_required"
    assert "Secret Tower" not in json.dumps(result)
    # Indistinguishable from a project that does not exist.
    [missing_result] = _frames(missing, "tool_result")
    assert missing_result["result"]["data"]["error"] == payload["error"]

    assert await _count(session_factory, ChatAction) == 0
    assert await _count(session_factory, Position) == 0


@pytest.mark.asyncio
async def test_member_can_read_boq_items(session_factory):
    """Read tools have ``permission='read'`` - any user passes the gate."""
    from app.modules.erp_chat.tools import (
        TOOL_PERMISSIONS,
        check_tool_permission,
    )

    assert TOOL_PERMISSIONS["get_boq_items"] == "read"

    admin_id = await _make_user(
        session_factory,
        email="adm-read@test.io",
        role="admin",
    )
    project_id = await _make_project(
        session_factory,
        owner_id=admin_id,
        name="Readable Project",
    )

    member_id = await _make_user(
        session_factory,
        email="reader@test.io",
        role="editor",
    )

    args = {"project_id": project_id}

    # Must not raise for a read tool, regardless of caller role.
    async with session_factory() as session:
        await check_tool_permission(session, "get_boq_items", args, member_id)


@pytest.mark.asyncio
async def test_no_tool_writes_directly_and_the_gate_still_fails_closed(session_factory, monkeypatch):
    """Nothing in the read-tool map writes; a handler marked ``write`` would still need manager+."""
    from app.modules.erp_chat.tools import (
        TOOL_DEFINITIONS,
        TOOL_HANDLER_MAP,
        TOOL_PERMISSIONS,
        ToolPermissionDenied,
        check_tool_permission,
    )

    assert "write" not in set(TOOL_PERMISSIONS.values())
    assert "create_boq_item" not in TOOL_HANDLER_MAP
    assert "create_boq_item" not in TOOL_PERMISSIONS
    assert "create_boq_item" not in {t["name"] for t in TOOL_DEFINITIONS}

    admin_id = await _make_user(session_factory, email="gate-owner@test.io", role="admin")
    project_id = await _make_project(session_factory, owner_id=admin_id, name="Gate Project")
    editor_id = await _make_user(session_factory, email="gate-editor@test.io", role="editor")

    monkeypatch.setitem(TOOL_PERMISSIONS, "hypothetical_direct_write", "write")
    async with session_factory() as session:
        with pytest.raises(ToolPermissionDenied) as ei:
            await check_tool_permission(session, "hypothetical_direct_write", {"project_id": project_id}, editor_id)
        assert ei.value.i18n_key == "chat.error.manager_required"
