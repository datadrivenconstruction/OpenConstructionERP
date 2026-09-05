"""HTTP-layer verification of the new BOQ proposal endpoints.

In-process FastAPI app + TestClient, mounting ONLY the ai_agents router with
the auth/session dependencies overridden, so the new
``GET /runs/{id}/proposals`` and ``POST /runs/{id}/apply`` endpoints are
exercised exactly as the real app serves them (route registration, status
codes, RBAC dependency wiring, response shapes) - without the full module
loader (which an unrelated in-progress module currently breaks at import time).

The DB is a transaction-isolated PostgreSQL session shared between the app
dependency and the test setup, so a run + BOQ created in setup is visible to
the endpoint under test, and everything is rolled back on teardown.
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


@pytest_asyncio.fixture
async def app_and_user(session):
    """A minimal app exposing the ai_agents router with auth overridden."""
    from app.dependencies import (
        get_current_user_id,
        get_current_user_payload,
        get_session,
    )
    from app.modules.ai_agents.router import router as ai_router

    user_id = uuid.uuid4()

    app = FastAPI()
    app.include_router(ai_router, prefix="/api/v1/ai-agents")

    async def _override_session():
        # Hand the app the SAME transactional session the test set up.
        yield session

    def _override_user_id() -> str:
        return str(user_id)

    def _override_payload() -> dict[str, Any]:
        # Admin role + the permissions the endpoints require.
        return {
            "sub": str(user_id),
            "role": "admin",
            "permissions": ["ai_agents.read", "ai_agents.run", "boq.create"],
        }

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user_id] = _override_user_id
    app.dependency_overrides[get_current_user_payload] = _override_payload

    return app, user_id


async def _seed_run_with_proposals(
    session,
    user_id: uuid.UUID,
    *,
    project_id: uuid.UUID | None = None,
) -> uuid.UUID:
    from app.modules.ai_agents.models import AgentRun, AgentStep
    from app.modules.ai_agents.proposals import PROPOSAL_KIND

    run = AgentRun(
        agent_name="boq_drafter",
        user_id=user_id,
        project_id=project_id,
        status="completed",
        user_input="draft a slab",
        final_output="Drafted 2 positions.",
    )
    session.add(run)
    await session.flush()
    session.add_all(
        [
            AgentStep(
                run_id=run.id,
                step_idx=1,
                role="observation",
                content={
                    "kind": PROPOSAL_KIND,
                    "description": "Excavation to reduce levels",
                    "unit": "m3",
                    "qty": 100.0,
                    "unit_rate": 18.5,
                    "total": 1850.0,
                    "currency": "EUR",
                },
            ),
            AgentStep(
                run_id=run.id,
                step_idx=2,
                role="observation",
                content={
                    "kind": PROPOSAL_KIND,
                    "description": "C30/37 ground slab 200mm",
                    "unit": "m3",
                    "qty": 30.0,
                    "unit_rate": 165.0,
                    "total": 4950.0,
                    "currency": "EUR",
                },
            ),
        ]
    )
    await session.flush()
    return run.id


@pytest.mark.asyncio
async def test_get_proposals_endpoint(app_and_user, session):
    app, user_id = app_and_user
    run_id = await _seed_run_with_proposals(session, user_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/ai-agents/runs/{run_id}/proposals")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == 2
    assert body["currencies"] == ["EUR"]
    assert body["mixed_currency"] is False
    assert body["proposals"][0]["description"] == "Excavation to reduce levels"
    assert body["proposals"][1]["unit_rate"] == "165.0"


@pytest.mark.asyncio
async def test_get_proposals_unknown_run_404(app_and_user):
    app, _user_id = app_and_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/ai-agents/runs/{uuid.uuid4()}/proposals")
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_apply_endpoint_creates_positions(app_and_user, session):
    app, user_id = app_and_user

    # Seed a BOQ whose project the acting user owns (so the access guard passes).
    from app.modules.boq.schemas import BOQCreate
    from app.modules.boq.service import BOQService
    from app.modules.projects.models import Project

    project = Project(name=f"Apply {uuid.uuid4().hex[:6]}", currency="EUR", owner_id=user_id)
    session.add(project)
    await session.flush()
    boq = await BOQService(session).create_boq(BOQCreate(project_id=project.id, name="Draft", currency="EUR"))
    await session.flush()

    run_id = await _seed_run_with_proposals(session, user_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            f"/api/v1/ai-agents/runs/{run_id}/apply",
            json={"boq_id": str(boq.id)},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["created"] == 2
    assert body["skipped"] == 0
    assert body["currency"] == "EUR"

    # Positions really landed in the BOQ.
    refreshed = await BOQService(session).get_boq_with_positions(boq.id)
    assert refreshed.position_count == 2


@pytest.mark.asyncio
async def test_apply_endpoint_no_proposals_422(app_and_user, session):
    app, user_id = app_and_user

    from app.modules.ai_agents.models import AgentRun
    from app.modules.boq.schemas import BOQCreate
    from app.modules.boq.service import BOQService
    from app.modules.projects.models import Project

    project = Project(name=f"NP {uuid.uuid4().hex[:6]}", currency="EUR", owner_id=user_id)
    session.add(project)
    await session.flush()
    boq = await BOQService(session).create_boq(BOQCreate(project_id=project.id, name="Draft", currency="EUR"))
    await session.flush()

    run = AgentRun(
        agent_name="schedule_analyst",
        user_id=user_id,
        status="completed",
        user_input="explain SPI",
        final_output="## Analysis\nSPI is 0.95.",
    )
    session.add(run)
    await session.flush()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            f"/api/v1/ai-agents/runs/{run.id}/apply",
            json={"boq_id": str(boq.id)},
        )
    assert res.status_code == 422, res.text
    assert "no BOQ position proposals" in res.text


@pytest.mark.asyncio
async def test_apply_endpoint_unreachable_project_404(app_and_user, session):
    """Applying into a BOQ whose project the user cannot access is a 404.

    404 and not 403: ``verify_project_access`` answers "missing" and "denied"
    identically so a caller cannot use the status code as an existence oracle
    for project UUIDs, and every module that guards a project goes through it.
    The run here is seeded unbound (``project_id=None``), so the endpoint takes
    its fallback branch and verifies the chosen BOQ's own project - which is
    why the body is "Project not found" and not "BOQ not found". Asserting the
    detail pins that branch: a 404 arriving from the run-lookup or the
    project-mismatch guard would be the right code for the wrong reason.
    """
    app, user_id = app_and_user

    from app.modules.boq.schemas import BOQCreate
    from app.modules.boq.service import BOQService
    from app.modules.projects.models import Project

    # Project owned by SOMEONE ELSE - the acting user is neither owner nor member.
    project = Project(name=f"Other {uuid.uuid4().hex[:6]}", currency="EUR", owner_id=uuid.uuid4())
    session.add(project)
    await session.flush()
    boq = await BOQService(session).create_boq(BOQCreate(project_id=project.id, name="Draft", currency="EUR"))
    await session.flush()

    run_id = await _seed_run_with_proposals(session, user_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            f"/api/v1/ai-agents/runs/{run_id}/apply",
            json={"boq_id": str(boq.id)},
        )
    assert res.status_code == 404, res.text
    assert res.json()["detail"] == "Project not found", res.text


# ── Project-binding security: apply targets the RUN's project, never the
#    caller's active/chosen project ─────────────────────────────────────────


async def _seed_owned_project_boq(session, owner_id: uuid.UUID, *, currency: str = "EUR"):
    """Create a Project owned by ``owner_id`` plus an empty BOQ in it."""
    from app.modules.boq.schemas import BOQCreate
    from app.modules.boq.service import BOQService
    from app.modules.projects.models import Project

    project = Project(name=f"P {uuid.uuid4().hex[:6]}", currency=currency, owner_id=owner_id)
    session.add(project)
    await session.flush()
    boq = await BOQService(session).create_boq(BOQCreate(project_id=project.id, name="Draft", currency=currency))
    await session.flush()
    return project, boq


@pytest.mark.asyncio
async def test_apply_targets_run_project_when_boq_matches(app_and_user, session):
    """A run bound to project P applies into a BOQ that lives in P (the run's
    own project is the target - the lines really land there)."""
    app, user_id = app_and_user

    from app.modules.boq.service import BOQService

    project, boq = await _seed_owned_project_boq(session, user_id)
    # The run is explicitly bound to this same project.
    run_id = await _seed_run_with_proposals(session, user_id, project_id=project.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            f"/api/v1/ai-agents/runs/{run_id}/apply",
            json={"boq_id": str(boq.id)},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["created"] == 2
    assert body["skipped"] == 0

    # The positions really landed in the run's project BOQ.
    refreshed = await BOQService(session).get_boq_with_positions(boq.id)
    assert refreshed.position_count == 2


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_apply_run_inaccessible_project_rejected(app_and_user, session):
    """A run bound to a project the caller cannot access is rejected, even if
    the caller owns the run (the run's project gates the apply)."""
    app, user_id = app_and_user

    from app.modules.boq.service import BOQService

    # Project owned by SOMEONE ELSE; the acting user is neither owner nor member.
    foreign_project, foreign_boq = await _seed_owned_project_boq(session, uuid.uuid4())
    # The user's own run is bound to that foreign project (e.g. a stale/forged id).
    run_id = await _seed_run_with_proposals(session, user_id, project_id=foreign_project.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            f"/api/v1/ai-agents/runs/{run_id}/apply",
            json={"boq_id": str(foreign_boq.id)},
        )
    # IDOR-safe rejection (404 per verify_project_access policy; 403 also acceptable).
    assert res.status_code in (403, 404), res.text

    # Nothing was written into the foreign BOQ.
    refreshed = await BOQService(session).get_boq_with_positions(foreign_boq.id)
    assert refreshed.position_count == 0


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_apply_client_boq_in_other_project_does_not_override_run(app_and_user, session):
    """A client-passed BOQ in a DIFFERENT project than the run's is refused -
    the caller's active project can never redirect a run's output.

    The run belongs to project A; the caller also owns project B and passes B's
    BOQ. Even though the caller can access B, the apply targets the run's own
    project, so the mismatch is rejected and B's BOQ is left untouched.
    """
    app, user_id = app_and_user

    from app.modules.boq.service import BOQService

    # Both projects are owned by the caller, so access is NOT the blocker here -
    # the only thing that should reject the apply is the project mismatch.
    project_a, _boq_a = await _seed_owned_project_boq(session, user_id)
    _project_b, boq_b = await _seed_owned_project_boq(session, user_id)

    # The run is bound to project A, but the request points at project B's BOQ.
    run_id = await _seed_run_with_proposals(session, user_id, project_id=project_a.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            f"/api/v1/ai-agents/runs/{run_id}/apply",
            json={"boq_id": str(boq_b.id)},
        )
    # Refused (not silently honoured); IDOR-safe 404 (403 also acceptable).
    assert res.status_code in (403, 404), res.text

    # Project B's BOQ - the caller's "active" project - received nothing.
    refreshed_b = await BOQService(session).get_boq_with_positions(boq_b.id)
    assert refreshed_b.position_count == 0
