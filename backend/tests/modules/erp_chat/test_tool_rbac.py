"""RBAC gate around the erp_chat tool registry.

The floating-chat tools split into READ (anyone authenticated) and WRITE
(manager+ on the referenced project). The dispatcher in
``ERPChatService._tool_loop`` enforces the split BEFORE invoking the
handler so a member cannot mutate via the AI chat what they could not
mutate via the regular HTTP endpoints.

Coverage in this module:

* manager calling ``create_boq_item`` succeeds (handler runs).
* member calling ``create_boq_item`` is refused with the
  ``manager_permission_required`` card — the BOQ position is NOT created.
* member calling ``get_boq_items`` succeeds (reads are open).
* cross-tenant manager calling ``create_boq_item`` for someone else's
  project gets the 404-style "project not found" card — never the role
  card, never a leak of project existence.

Tests run against an in-memory SQLite database initialised with only the
tables they need — no FastAPI app boot, no migrations.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# Per-module SQLite isolation — must run BEFORE any app.* import.
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-chat-rbac-"))
_TMP_DB = _TMP_DIR / "chat_rbac.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session_factory():
    """In-memory SQLite with every table create_all can reach.

    We import the full module set so Project / User / Team /
    TeamMembership / BOQ rows can coexist — the tools touch all of them.
    """
    # Import models so their tables are on Base.metadata before create_all.
    import app.modules.boq.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.teams.models  # noqa: F401
    import app.modules.users.models  # noqa: F401
    from app.database import Base

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}",
        echo=False,
    )
    # Per-test isolation: drop + recreate so leftover Position / Project
    # rows from a previous case never bleed into the next ("no row was
    # created" assertions must mean THIS test's row, not a stale one).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


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
        )
        session.add(project)
        await session.flush()
        await session.commit()
        return str(project.id)


async def _make_boq(maker, *, project_id: str, name: str = "Default BOQ") -> str:
    """Insert an empty BOQ on a project so ``create_boq_item`` has somewhere
    to add its position. Returns BOQ UUID string."""
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


# ── Test cases ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_manager_can_create_boq_item(session_factory):
    """Global-manager user passes the write gate AND mutates the BOQ."""
    from sqlalchemy import select

    from app.modules.boq.models import Position
    from app.modules.erp_chat.tools import (
        TOOL_PERMISSIONS,
        ToolPermissionDenied,
        check_tool_permission,
        handle_create_boq_item,
    )

    assert TOOL_PERMISSIONS["create_boq_item"] == "write"

    manager_id = await _make_user(
        session_factory,
        email="mgr@test.io",
        role="manager",
    )
    project_id = await _make_project(
        session_factory,
        owner_id=manager_id,
        name="Mgr Project",
    )
    await _make_boq(session_factory, project_id=project_id)

    args = {
        "project_id": project_id,
        "description": "Concrete wall C30/37",
        "unit": "m2",
        "quantity": 12.5,
        "unit_rate": 95.50,
    }

    async with session_factory() as session:
        # Permission check first — must not raise.
        await check_tool_permission(session, "create_boq_item", args, manager_id)

        # Handler call then succeeds.
        result = await handle_create_boq_item(session, args, manager_id)
        await session.commit()

    assert result["renderer"] == "boq_item_created", result
    assert result["data"]["description"] == "Concrete wall C30/37"

    async with session_factory() as session:
        rows = (await session.execute(select(Position))).scalars().all()
        assert len(rows) == 1
        assert rows[0].description == "Concrete wall C30/37"

    # Sanity: ToolPermissionDenied is the exception type we use.
    assert issubclass(ToolPermissionDenied, Exception)


@pytest.mark.asyncio
async def test_member_cannot_create_boq_item(session_factory):
    """Non-manager (``editor``) user is blocked by the write gate."""
    from sqlalchemy import select

    from app.modules.boq.models import Position
    from app.modules.erp_chat.tools import (
        ToolPermissionDenied,
        check_tool_permission,
    )

    # Owner = admin (so the project exists + member can read it later).
    admin_id = await _make_user(
        session_factory,
        email="owner@test.io",
        role="admin",
    )
    project_id = await _make_project(
        session_factory,
        owner_id=admin_id,
        name="Shared Project",
    )
    await _make_boq(session_factory, project_id=project_id)

    member_id = await _make_user(
        session_factory,
        email="member@test.io",
        role="editor",
    )

    args = {
        "project_id": project_id,
        "description": "Should not land",
        "unit": "m",
        "quantity": 1,
        "unit_rate": 1,
    }

    # The gate raises — the dispatcher catches and emits the error card.
    async with session_factory() as session:
        with pytest.raises(ToolPermissionDenied) as ei:
            await check_tool_permission(
                session,
                "create_boq_item",
                args,
                member_id,
            )
        assert ei.value.i18n_key == "chat.error.manager_required"

    # And no Position row was created (gate ran before handler).
    async with session_factory() as session:
        rows = (await session.execute(select(Position))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_member_can_read_boq_items(session_factory):
    """Read tools have ``permission='read'`` — any user passes the gate."""
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
async def test_cross_tenant_manager_gets_404_not_403(session_factory):
    """IDOR posture: a manager whose project_id belongs to someone else
    gets the standard 404-style 'project not found' error — never the
    role-required card (which would leak the project's existence)."""
    from app.modules.erp_chat.service import ERPChatService
    from app.modules.erp_chat.tools import ToolAuthError, _require_project_access

    # Tenant A owns the project.
    tenant_a_id = await _make_user(
        session_factory,
        email="tenant-a@test.io",
        role="admin",
    )
    project_id = await _make_project(
        session_factory,
        owner_id=tenant_a_id,
        name="Tenant A Project",
    )
    await _make_boq(session_factory, project_id=project_id)

    # Tenant B is a manager — but NOT on this project.
    tenant_b_id = await _make_user(
        session_factory,
        email="tenant-b@test.io",
        role="manager",
    )

    # The IDOR check (which the dispatcher runs FIRST for write tools)
    # raises ToolAuthError — that becomes the 404-shaped error card and
    # we never reach the role check.
    async with session_factory() as session:
        with pytest.raises(ToolAuthError) as ei:
            await _require_project_access(
                session,
                uuid.UUID(project_id),
                tenant_b_id,
            )
        # The message must not include the words "manager" or "permission"
        # so the cross-tenant card is indistinguishable from "project
        # missing" — that's the IDOR posture.
        text = str(ei.value).lower()
        assert "manager" not in text
        assert "permission" not in text

    # End-to-end through the dispatcher: simulate one tool round and assert
    # the surfaced result is the IDOR card, NOT the role card.
    args = {
        "project_id": project_id,
        "description": "X",
        "unit": "m",
        "quantity": 1,
        "unit_rate": 1,
    }
    async with session_factory() as session:
        service = ERPChatService(session)
        result = await _dispatch_one(service, "create_boq_item", args, tenant_b_id)

    assert result["renderer"] == "error", result
    # IDOR-flavour error (carries the project_id in its message) — NOT the
    # role-denied card with i18n_key "chat.error.manager_required".
    payload = result.get("data") or {}
    assert payload.get("i18n_key") != "chat.error.manager_required"


# ── Helper: inline copy of the dispatcher logic from ``stream_response`` ───
#
# We don't drive the whole SSE generator because it would also try to
# call out to Anthropic. The dispatcher's permission-gate block is a
# self-contained piece of logic — we copy it here so the test runs the
# exact same branch.


async def _dispatch_one(service, tool_name, tool_args, user_id):
    """Run one tool call through the same permission + handler logic
    ``ERPChatService.stream_response`` uses, returning the tool_result
    that would have been emitted on the SSE wire."""
    from app.modules.erp_chat.tools import (
        TOOL_HANDLER_MAP,
        TOOL_PERMISSIONS,
        ToolAuthError,
        ToolPermissionDenied,
        _auth_error,
        _extract_project_id,
        _require_project_access,
        check_tool_permission,
        manager_permission_error_result,
    )

    handler = TOOL_HANDLER_MAP[tool_name]
    is_write = TOOL_PERMISSIONS.get(tool_name, "read") == "write"
    tool_result = None

    if is_write:
        project_id = _extract_project_id(tool_name, tool_args)
        if project_id is not None:
            try:
                await _require_project_access(
                    service.session,
                    project_id,
                    user_id,
                )
            except ToolAuthError as te:
                tool_result = _auth_error(str(te))
        if tool_result is None:
            try:
                await check_tool_permission(
                    service.session,
                    tool_name,
                    tool_args,
                    user_id,
                )
            except ToolPermissionDenied:
                tool_result = manager_permission_error_result()

    if tool_result is None:
        tool_result = await handler(service.session, tool_args, user_id)
    return tool_result
