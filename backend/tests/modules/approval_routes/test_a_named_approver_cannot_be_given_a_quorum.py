# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A step that names one approver cannot also ask for several approvals.

The engine clears a step that names a user on that user's approval alone and
never reads ``required_approver_count`` for it, while the unique decision row
per approver means one named person can only ever give one approval. A count
above one on such a step is therefore a gate that looks stricter than it is:
the author asked for two approvals and the step clears on one, with nothing
red anywhere. Saving that configuration is refused with a 422 that says why,
on create, on a step replacement and on a clone of a route written before
the check existed. A route already holding such a step can still be renamed,
because refusing an unrelated edit would not repair anything.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.core.audit_log  # noqa: F401 - registers ActivityLog with Base
from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.approval_routes.models import Route, Step
from app.modules.approval_routes.router import router as ar_router
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    async with transactional_session() as s:
        yield s


async def _make_user(session) -> uuid.UUID:
    user = User(email=f"quorum-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role="admin")
    session.add(user)
    await session.flush()
    return user.id


def _build_app(db_session, caller_id: str) -> FastAPI:
    app = FastAPI()
    app.include_router(ar_router, prefix="/v1/approval-routes")

    async def _session_override():
        yield db_session

    async def _user_override() -> str:
        return caller_id

    async def _payload_override() -> dict:
        return {"sub": caller_id, "role": "admin", "permissions": []}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    return app


@asynccontextmanager
async def _http(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _route(steps: list[dict]) -> dict:
    return {"project_id": None, "name": "Sign-off", "target_kind": "submittal", "steps": steps}


async def _legacy_route(session, approver_id: uuid.UUID) -> uuid.UUID:
    """A route saved before the check: one named approver asked for two approvals."""
    route = Route(project_id=None, name="Legacy sign-off", target_kind="submittal", is_active=True)
    session.add(route)
    await session.flush()
    session.add(
        Step(
            route_id=route.id,
            ordinal=1,
            approver_role=None,
            approver_user_id=approver_id,
            mode="all",
            required_approver_count=2,
        )
    )
    await session.commit()
    return route.id


@pytest.mark.asyncio
async def test_creating_a_named_approver_step_with_a_count_of_two_is_refused(db_session) -> None:
    user_id = await _make_user(db_session)
    await db_session.commit()
    async with _http(_build_app(db_session, str(user_id))) as client:
        resp = await client.post(
            "/v1/approval-routes/routes",
            json=_route(
                [
                    {"ordinal": 1, "approver_role": "editor", "mode": "all", "required_approver_count": 3},
                    {"ordinal": 2, "approver_user_id": str(user_id), "mode": "all", "required_approver_count": 2},
                ]
            ),
        )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "Step 2" in detail
    assert "required_approver_count 2" in detail


@pytest.mark.asyncio
async def test_a_named_approver_with_a_count_of_one_or_none_is_accepted(db_session) -> None:
    user_id = await _make_user(db_session)
    await db_session.commit()
    async with _http(_build_app(db_session, str(user_id))) as client:
        resp = await client.post(
            "/v1/approval-routes/routes",
            json=_route(
                [
                    {"ordinal": 1, "approver_user_id": str(user_id), "mode": "all", "required_approver_count": 1},
                    {"ordinal": 2, "approver_user_id": str(user_id), "mode": "any"},
                ]
            ),
        )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_replacing_the_steps_with_that_configuration_is_refused(db_session) -> None:
    user_id = await _make_user(db_session)
    await db_session.commit()
    async with _http(_build_app(db_session, str(user_id))) as client:
        created = await client.post(
            "/v1/approval-routes/routes",
            json=_route([{"ordinal": 1, "approver_role": "editor", "mode": "any"}]),
        )
        assert created.status_code == 201, created.text
        route_id = created.json()["id"]
        resp = await client.patch(
            f"/v1/approval-routes/routes/{route_id}",
            json={
                "steps": [
                    {"ordinal": 1, "approver_user_id": str(user_id), "mode": "majority", "required_approver_count": 3}
                ]
            },
        )
        assert resp.status_code == 422, resp.text
        assert "required_approver_count 3" in resp.json()["detail"]
        # Refused before anything was written: the old step is still there.
        after = await client.get(f"/v1/approval-routes/routes/{route_id}")
    assert [s["approver_role"] for s in after.json()["steps"]] == ["editor"]


@pytest.mark.asyncio
async def test_a_route_saved_before_the_check_can_still_be_renamed(db_session) -> None:
    user_id = await _make_user(db_session)
    route_id = await _legacy_route(db_session, user_id)
    async with _http(_build_app(db_session, str(user_id))) as client:
        resp = await client.patch(f"/v1/approval-routes/routes/{route_id}", json={"name": "Renamed"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Renamed"


@pytest.mark.asyncio
async def test_cloning_a_route_saved_before_the_check_is_refused_not_a_server_error(db_session) -> None:
    user_id = await _make_user(db_session)
    project = Project(name="Quorum clone", owner_id=user_id)
    db_session.add(project)
    await db_session.flush()
    route_id = await _legacy_route(db_session, user_id)
    async with _http(_build_app(db_session, str(user_id))) as client:
        resp = await client.post(
            f"/v1/approval-routes/routes/{route_id}/clone",
            json={"project_id": str(project.id), "name": "Copy"},
        )
    # The clone would copy the contradiction, so it is refused the same way,
    # and as a 422 rather than the 500 a validation error raised while the
    # clone rebuilds its steps would give.
    assert resp.status_code == 422, resp.text
    assert "required_approver_count 2" in resp.json()["detail"]
