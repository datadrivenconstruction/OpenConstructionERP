"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data-integrity tests for the RFI -> change-order variation handoff.

Scope (BUG-RFI-VARIATION-DUP):
    1. ``POST /{rfi_id}/create-variation/`` is idempotent - a second call
       (double-submit / retry) returns the *same* change order instead of
       minting a duplicate, and the project ends up with exactly one CO.
    2. The RFI's ``change_order_id`` link is stable across the repeated
       call (it is not re-pointed at a freshly-minted duplicate, which
       would orphan the first CO whose metadata still references this RFI).

The suite mirrors ``test_rfi_attachments.py``: the RFI router is mounted on an
``httpx.AsyncClient`` with dependency overrides for session / auth / project
access, and each test runs against a PostgreSQL session wrapped in an outer
transaction rolled back on teardown (see ``tests._pg.transactional_session``).
The change-orders module is a real dependency here, so this exercises the
genuine cross-module create path.

The client has to be the async one. The synchronous ``TestClient`` drives the
app from a private event loop in a worker thread, while ``db_session`` is bound
to the loop the test runs on, and a single asyncpg connection cannot be shared
across both.
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import func, select

from app.dependencies import (
    get_current_user_id,
    get_current_user_payload,
    get_session,
    verify_project_access,
)
from app.modules.projects.models import Project
from app.modules.rfi.router import router as rfi_router
from app.modules.rfi.schemas import RFICreate
from app.modules.rfi.service import RFIService
from app.modules.users.models import User
from tests._pg import transactional_session

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    """PostgreSQL session inside a transaction rolled back on teardown."""
    async with transactional_session() as s:
        yield s


async def _make_user(session, *, email: str | None = None) -> uuid.UUID:
    user = User(
        email=email or f"u{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user.id


async def _make_project(session, owner_id: uuid.UUID) -> uuid.UUID:
    project = Project(name="Test Project", owner_id=owner_id, currency="EUR")
    session.add(project)
    await session.flush()
    await session.refresh(project)
    return project.id


def _build_app(db_session, *, caller_id: str) -> FastAPI:
    """Mount the RFI router with auth + session overrides (admin caller)."""
    app = FastAPI()
    app.include_router(rfi_router, prefix="/v1/rfi")

    async def _session_override():
        yield db_session

    async def _user_override() -> str:
        return caller_id

    async def _project_access_override(project_id, user_id, session) -> None:
        from fastapi import HTTPException
        from fastapi import status as st

        from app.modules.projects.models import Project as _P  # noqa: N814

        row = await session.get(_P, project_id)
        if row is None:
            raise HTTPException(status_code=st.HTTP_404_NOT_FOUND, detail="Project not found")
        if str(row.owner_id) != str(user_id):
            raise HTTPException(status_code=st.HTTP_404_NOT_FOUND, detail="Project not found")

    async def _payload_override() -> dict:
        # Admin role short-circuits ``RequirePermission`` for both ``rfi.*``
        # and ``changeorders.create`` so this test exercises the data-integrity
        # path, not the RBAC gate.
        return {"sub": caller_id, "role": "admin", "permissions": []}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    app.dependency_overrides[verify_project_access] = _project_access_override
    return app


async def _count_change_orders(session, project_id: uuid.UUID) -> int:
    from app.modules.changeorders.models import ChangeOrder

    return (
        await session.execute(select(func.count()).select_from(ChangeOrder).where(ChangeOrder.project_id == project_id))
    ).scalar_one()


async def _seed_answered_cost_rfi(db_session, owner: str, project_id: uuid.UUID):
    """Create an ``answered`` RFI carrying a cost impact, ready for variation."""
    service = RFIService(db_session)
    rfi = await service.create_rfi(
        RFICreate(
            project_id=project_id,
            subject="Extra rebar at grid C",
            question="Confirm additional reinforcement?",
            status="open",
            cost_impact=True,
            cost_impact_value="12500.00",
        ),
        user_id=owner,
    )
    # Move open -> answered through the real respond path (unassigned RFI, so
    # any caller with rfi.respond may answer).
    await service.respond_to_rfi(
        rfi.id,
        "Yes - add the reinforcement as marked.",
        responded_by=owner,
        actor_role="admin",
    )
    await db_session.commit()
    return rfi


# ── 1 + 2. create-variation idempotency ──────────────────────────────────


class TestCreateVariationIdempotency:
    @pytest.mark.asyncio
    async def test_double_submit_returns_same_change_order(self, db_session) -> None:
        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        rfi = await _seed_answered_cost_rfi(db_session, owner, project_id)

        app = _build_app(db_session, caller_id=owner)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(f"/v1/rfi/{rfi.id}/create-variation/")
            assert first.status_code == 201, first.text
            first_co = first.json()["change_order_id"]

            # Second call = double-submit / retry. Must NOT mint a new CO.
            second = await client.post(f"/v1/rfi/{rfi.id}/create-variation/")
        assert second.status_code == 201, second.text
        second_co = second.json()["change_order_id"]

        assert first_co == second_co, "double-submit minted a duplicate change order"
        # Exactly one CO exists for the project despite two POSTs.
        assert await _count_change_orders(db_session, project_id) == 1

    @pytest.mark.asyncio
    async def test_rfi_link_is_stable_across_repeated_calls(self, db_session) -> None:
        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        rfi = await _seed_answered_cost_rfi(db_session, owner, project_id)

        app = _build_app(db_session, caller_id=owner)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(f"/v1/rfi/{rfi.id}/create-variation/")
            assert first.status_code == 201, first.text
            linked_co = first.json()["change_order_id"]

            # Re-fetch the RFI: it points at the CO we just minted.
            got = await client.get(f"/v1/rfi/{rfi.id}")
            assert got.status_code == 200, got.text
            assert got.json()["change_order_id"] == linked_co

            # A repeated create-variation keeps the same link (no re-pointing at
            # a duplicate, which would orphan the first CO).
            again = await client.post(f"/v1/rfi/{rfi.id}/create-variation/")
            assert again.status_code == 201, again.text
            assert again.json()["change_order_id"] == linked_co

            got2 = await client.get(f"/v1/rfi/{rfi.id}")
        assert got2.status_code == 200, got2.text
        assert got2.json()["change_order_id"] == linked_co
