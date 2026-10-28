# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠HTTP-layer verification of the AI feedback sink (POST /feedback).

In-process FastAPI app + httpx AsyncClient, mounting ONLY the ai_agents router
with the auth/session dependencies overridden, so the generic trust-loop
``POST /feedback`` endpoint is exercised exactly as the real app serves it
(route registration, status codes, RBAC dependency wiring, project-access
guard) - without the full module loader.

These cover two access controls the endpoint must enforce:

* a ``project_id`` the caller cannot access is rejected before any row is
  written (IDOR / verify_project_access policy: 404 on both missing and
  denied, so project existence never leaks); and
* the endpoint requires the ``ai_agents.run`` capability - a caller whose
  role does not grant it is rejected (403).

The DB is a transaction-isolated PostgreSQL session shared between the app
dependency and the test setup, so a project created in setup is visible to the
endpoint under test, and everything is rolled back on teardown.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session():
    # FK triggers off: we seed a project without a real user row.
    async with transactional_session(disable_fks=True) as s:
        yield s


def _build_app(session, *, user_id: uuid.UUID, role: str, permissions: list[str]) -> FastAPI:
    """A minimal app exposing the ai_agents router with auth overridden.

    The payload override drives both ``RequirePermission`` (which reads ``role``
    + ``permissions``) and the handler's ``CurrentUserId``. A non-admin ``role``
    is deliberate: ``verify_project_access`` only short-circuits for an admin
    whose row exists, so a non-admin keeps the project-access guard real here.
    """
    from app.dependencies import (
        get_current_user_id,
        get_current_user_payload,
        get_session,
    )
    from app.modules.ai_agents.router import router as ai_router

    app = FastAPI()
    app.include_router(ai_router, prefix="/api/v1/ai-agents")

    async def _override_session():
        # Hand the app the SAME transactional session the test set up.
        yield session

    def _override_user_id() -> str:
        return str(user_id)

    def _override_payload() -> dict[str, Any]:
        return {"sub": str(user_id), "role": role, "permissions": permissions}

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user_id] = _override_user_id
    app.dependency_overrides[get_current_user_payload] = _override_payload
    return app


async def _make_project(session, owner_id: uuid.UUID) -> uuid.UUID:
    """Create a Project owned by ``owner_id`` and return its id."""
    from app.modules.projects.models import Project

    project = Project(name=f"FB {uuid.uuid4().hex[:6]}", currency="EUR", owner_id=owner_id)
    session.add(project)
    await session.flush()
    return project.id


# --- Happy path: access + permission records a verdict ----------------------


@pytest.mark.asyncio
async def test_feedback_with_access_and_permission_records(session):
    """An editor who owns the project records a verdict (anchors the negatives)."""
    user_id = uuid.uuid4()
    project_id = await _make_project(session, owner_id=user_id)
    app = _build_app(session, user_id=user_id, role="editor", permissions=["ai_agents.run"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/ai-agents/feedback",
            json={"surface": "ai_estimator", "correct": True, "project_id": str(project_id)},
        )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["surface"] == "ai_estimator"
    assert body["correct"] is True


# --- (a) IDOR: a project the caller cannot access is rejected ----------------


@pytest.mark.asyncio
async def test_feedback_inaccessible_project_rejected(session):
    """A verdict scoped to a project the caller cannot see is refused, and no
    feedback row is written for it.

    The project is owned by someone else and the caller is neither owner nor
    member, so ``verify_project_access`` rejects it. Per the IDOR-safe policy
    that is a 404 (it never reveals whether the project exists).
    """
    user_id = uuid.uuid4()
    # Project owned by SOMEONE ELSE - the acting user is neither owner nor member.
    foreign_project_id = await _make_project(session, owner_id=uuid.uuid4())
    app = _build_app(session, user_id=user_id, role="editor", permissions=["ai_agents.run"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/ai-agents/feedback",
            json={"surface": "ai_estimator", "correct": False, "project_id": str(foreign_project_id)},
        )
    assert res.status_code == 404, res.text

    # Nothing was attributed to the foreign project.
    from sqlalchemy import func, select

    from app.modules.ai_agents.models import AIFeedback

    count = (
        await session.execute(
            select(func.count()).select_from(AIFeedback).where(AIFeedback.project_id == foreign_project_id)
        )
    ).scalar_one()
    assert count == 0


# --- (b) Permission: the endpoint requires ai_agents.run --------------------


@pytest.mark.asyncio
async def test_feedback_requires_run_permission(session):
    """A caller whose role does not grant ``ai_agents.run`` is rejected (403).

    ``ai_agents.run`` requires an editor; a viewer is below that, so the
    ``RequirePermission`` gate denies before the handler body runs. No
    ``project_id`` is sent so the only thing under test is the capability gate.
    """
    user_id = uuid.uuid4()
    app = _build_app(session, user_id=user_id, role="viewer", permissions=[])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/ai-agents/feedback",
            json={"surface": "ai_estimator", "correct": True},
        )
    assert res.status_code == 403, res.text


# --- (c) Read side: the summary rolls up the caller's own verdicts -----------


def _add_feedback(session, *, user_id: uuid.UUID, surface: str, correct: bool) -> None:
    """Insert one AIFeedback row directly (the write path is covered above)."""
    from app.modules.ai_agents.models import AIFeedback

    session.add(AIFeedback(user_id=user_id, surface=surface, correct=correct, project_id=None, ref=None, note=None))


@pytest.mark.asyncio
async def test_feedback_summary_rolls_up_callers_verdicts(session):
    """GET /feedback/summary aggregates the caller's verdicts overall and per surface."""
    user_id = uuid.uuid4()
    _add_feedback(session, user_id=user_id, surface="ai_estimator", correct=True)
    _add_feedback(session, user_id=user_id, surface="ai_estimator", correct=True)
    _add_feedback(session, user_id=user_id, surface="ai_estimator", correct=False)
    _add_feedback(session, user_id=user_id, surface="match_elements", correct=False)
    await session.flush()

    app = _build_app(session, user_id=user_id, role="editor", permissions=["ai_agents.read"])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/ai-agents/feedback/summary")
    assert res.status_code == 200, res.text

    body = res.json()
    assert body["total"] == 4
    assert body["correct"] == 2
    assert body["incorrect"] == 2
    assert body["correct_rate"] == 0.5
    by_surface = {row["surface"]: row for row in body["by_surface"]}
    assert by_surface["ai_estimator"]["total"] == 3
    assert by_surface["ai_estimator"]["correct"] == 2
    assert by_surface["match_elements"]["correct_rate"] == 0.0


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_feedback_summary_excludes_other_users(session):
    """The summary never counts another user's verdicts (the caller-scoped read).

    The read is fenced to the caller's own ``user_id``, which is the security
    boundary, so a second user's verdicts on the same surface stay invisible.
    """
    user_id = uuid.uuid4()
    other_id = uuid.uuid4()
    _add_feedback(session, user_id=user_id, surface="advisor", correct=True)
    _add_feedback(session, user_id=other_id, surface="advisor", correct=False)
    _add_feedback(session, user_id=other_id, surface="advisor", correct=False)
    await session.flush()

    app = _build_app(session, user_id=user_id, role="editor", permissions=["ai_agents.read"])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/ai-agents/feedback/summary")
    assert res.status_code == 200, res.text

    body = res.json()
    assert body["total"] == 1
    assert body["correct"] == 1
    assert body["correct_rate"] == 1.0
