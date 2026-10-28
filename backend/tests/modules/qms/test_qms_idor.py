"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests: QMS IDOR ownership enforcement.

Each test seeds two users (victim / attacker), creates a resource under
the victim's project, then attempts to read / mutate / delete it as the
attacker. Every such attempt must return HTTP 404 — not 403 and not 200.
Returning 404 avoids leaking the existence of the UUID (the same behaviour
used across every R6/R7-audited module).

Router is mounted against a live PostgreSQL session (the shared unit
database, isolated per test by an outer transaction that is rolled back on
teardown) so the real ``verify_project_access`` runs against persisted
``Project.owner_id`` rows.

The router is exercised with :class:`httpx.AsyncClient` over an in-process
``ASGITransport`` so the app runs on the *same* event loop as the test. The
synchronous ``fastapi.testclient.TestClient`` drives the app from a worker
thread on its own loop, which breaks when a handler reuses the asyncpg
session created on the test loop ("Future attached to a different loop").
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    get_current_user_id,
    get_current_user_payload,
    get_session,
)
from app.modules.projects.models import Project
from app.modules.qms.router import router as qms_router
from app.modules.qms.schemas import (
    InspectionCreate,
    NCRCreate,
)
from app.modules.qms.service import QMSService
from app.modules.users.models import User
from tests._pg import transactional_session

# Every test in this file has identity as the variable under test.
pytestmark = pytest.mark.tenant_isolation

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Function-scoped session on the shared PostgreSQL unit database.

    Each test runs inside an outer transaction that is rolled back on
    teardown, so the database starts empty for every test. The session's own
    ``commit()`` calls become savepoint releases (visible within the test,
    undone afterwards), which the router tests rely on after seeding rows.
    """
    async with transactional_session() as s:
        yield s


async def _make_user(session: AsyncSession) -> uuid.UUID:
    user = User(email=f"u{uuid.uuid4().hex[:6]}@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user.id


async def _make_project(session: AsyncSession, owner_id: uuid.UUID) -> uuid.UUID:
    project = Project(name="Test", owner_id=owner_id)
    session.add(project)
    await session.flush()
    await session.refresh(project)
    return project.id


def _build_app(db_session: AsyncSession, *, caller_id: str) -> FastAPI:
    app = FastAPI()
    app.include_router(qms_router, prefix="/v1/qms")

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def _user_override() -> str:
        return caller_id

    async def _payload_override() -> dict[str, Any]:
        return {"sub": caller_id, "role": "admin", "permissions": []}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    return app


@asynccontextmanager
async def _http(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """In-process async HTTP client bound to ``app`` on the current loop."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ── IDOR: GET /inspections/{id} ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_inspection_idor_404_for_attacker(
    session: AsyncSession,
) -> None:
    """Attacker guessing victim's inspection UUID must receive 404."""
    victim = await _make_user(session)
    attacker = await _make_user(session)
    victim_project = await _make_project(session, victim)

    svc = QMSService(session)
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=victim_project),
    )
    await session.commit()

    app = _build_app(session, caller_id=str(attacker))
    async with _http(app) as client:
        resp = await client.get(f"/v1/qms/inspections/{insp.id}")
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_get_inspection_200_for_owner(session: AsyncSession) -> None:
    """Project owner can retrieve their own inspection."""
    owner = await _make_user(session)
    project_id = await _make_project(session, owner)
    svc = QMSService(session)
    insp = await svc.schedule_inspection(InspectionCreate(project_id=project_id))
    await session.commit()

    app = _build_app(session, caller_id=str(owner))
    async with _http(app) as client:
        resp = await client.get(f"/v1/qms/inspections/{insp.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(insp.id)


# ── IDOR: GET /ncrs/{id} ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_ncr_idor_404_for_attacker(session: AsyncSession) -> None:
    """Attacker cannot read victim's NCR by UUID."""
    victim = await _make_user(session)
    attacker = await _make_user(session)
    victim_project = await _make_project(session, victim)

    svc = QMSService(session)
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=victim_project,
            title="Structural crack",
            description="Crack at joint",
            severity="major",
        ),
    )
    await session.commit()

    app = _build_app(session, caller_id=str(attacker))
    async with _http(app) as client:
        resp = await client.get(f"/v1/qms/ncrs/{ncr.id}")
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_get_ncr_200_for_owner(session: AsyncSession) -> None:
    """Project owner can retrieve their own NCR."""
    owner = await _make_user(session)
    project_id = await _make_project(session, owner)
    svc = QMSService(session)
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=project_id,
            title="Minor gap",
            description="d",
            severity="minor",
        ),
    )
    await session.commit()

    app = _build_app(session, caller_id=str(owner))
    async with _http(app) as client:
        resp = await client.get(f"/v1/qms/ncrs/{ncr.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(ncr.id)


# ── IDOR: PATCH /ncrs/{id} for cross-project ─────────────────────────────


@pytest.mark.asyncio
async def test_patch_ncr_idor_404_for_attacker(session: AsyncSession) -> None:
    """Attacker cannot update victim's NCR via PATCH."""
    victim = await _make_user(session)
    attacker = await _make_user(session)
    victim_project = await _make_project(session, victim)

    svc = QMSService(session)
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=victim_project,
            title="Structural issue",
            description="d",
            severity="critical",
        ),
    )
    await session.commit()

    app = _build_app(session, caller_id=str(attacker))
    async with _http(app) as client:
        resp = await client.patch(
            f"/v1/qms/ncrs/{ncr.id}",
            json={"title": "Injected title"},
        )
    assert resp.status_code == 404, resp.text

    # Confirm victim's NCR was not mutated
    original = await svc.repo.get_ncr(ncr.id)
    assert original is not None
    assert original.title == "Structural issue"


# ── IDOR: POST /ncrs/{id}/close for cross-project ─────────────────────────


@pytest.mark.asyncio
async def test_close_ncr_idor_404_for_attacker(session: AsyncSession) -> None:
    """Attacker cannot close victim's NCR."""
    victim = await _make_user(session)
    attacker = await _make_user(session)
    victim_project = await _make_project(session, victim)

    svc = QMSService(session)
    ncr = await svc.raise_ncr(
        NCRCreate(
            project_id=victim_project,
            title="T",
            description="d",
            severity="minor",
        ),
    )
    # Assign + verify an action so close_ncr wouldn't fail on validation
    action = await svc.assign_ncr_action(
        ncr.id,
        __import__("app.modules.qms.schemas", fromlist=["NCRActionCreate"]).NCRActionCreate(
            description="Fix",
        ),
    )
    await svc.verify_action(action.id)
    await session.commit()

    app = _build_app(session, caller_id=str(attacker))
    async with _http(app) as client:
        resp = await client.post(f"/v1/qms/ncrs/{ncr.id}/close")
    assert resp.status_code == 404, resp.text

    # Confirm victim's NCR is still verifying, not closed
    refreshed = await svc.repo.get_ncr(ncr.id)
    assert refreshed is not None
    assert refreshed.status == "verifying"


# ── IDOR: PATCH /inspections/{id} for cross-project ──────────────────────


@pytest.mark.asyncio
async def test_patch_inspection_idor_404_for_attacker(
    session: AsyncSession,
) -> None:
    """Attacker cannot mutate victim's inspection."""
    victim = await _make_user(session)
    attacker = await _make_user(session)
    victim_project = await _make_project(session, victim)

    svc = QMSService(session)
    insp = await svc.schedule_inspection(
        InspectionCreate(project_id=victim_project, notes="original"),
    )
    await session.commit()

    app = _build_app(session, caller_id=str(attacker))
    async with _http(app) as client:
        resp = await client.patch(
            f"/v1/qms/inspections/{insp.id}",
            json={"notes": "hacked"},
        )
    assert resp.status_code == 404, resp.text

    # Confirm original notes unchanged
    original = await svc.repo.get_inspection(insp.id)
    assert original is not None
    assert original.notes == "original"
