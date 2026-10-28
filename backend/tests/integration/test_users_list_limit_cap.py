"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Regression: GET /v1/users/ limit cap contract.

Source defect (user error log openconstructionerp-log-2026-05-22.json,
v4.3.2): the /admin/audit-log page (and other resolvers) defaulted to
``limit=200`` against this endpoint, but the backend caps it at 100 -
every audit-log mount fired a 422. The frontend default is now 100.

The cap itself moved on 2026-06-05 (``36f3ebcb8``): directory and assignee
pickers load the whole active-user list in one call, and a hard 100 dropped
assignees silently, so ``app/modules/users/router.py`` now declares
``le=500`` with that reasoning next to it. This module still locks both ends
of the contract, it just locks them at the cap the endpoint actually ships:

* limit=100 -> 200 OK (the frontend default).
* limit=500 -> 200 OK (the cap itself).
* limit=501 -> 422 (one past it; the cap cannot move without both numbers moving).

Uses the lightweight test pattern (mount just the users router on a
minimal FastAPI app with auth/perm/session dependencies stubbed) to
avoid the full ``create_app()`` boot path - see comment in
``test_crm_opportunities_limit.py`` for the rationale.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests._pg import isolated_engine


@pytest_asyncio.fixture
async def app() -> AsyncGenerator[FastAPI, None]:
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        from app.dependencies import (
            RequirePermission,
            get_current_user_id,
            get_current_user_payload,
            get_session,
        )
        from app.modules.users.router import router as users_router

        fastapi_app = FastAPI()
        fastapi_app.include_router(users_router, prefix="/api/v1/users")

        async def _override_session() -> AsyncGenerator[AsyncSession, None]:
            async with factory() as s:
                try:
                    yield s
                    await s.commit()
                except Exception:
                    await s.rollback()
                    raise

        async def _override_user_id() -> str:
            return str(uuid.uuid4())

        async def _override_payload() -> dict[str, str]:
            return {"sub": str(uuid.uuid4()), "role": "admin"}

        async def _allow() -> None:
            return None

        fastapi_app.dependency_overrides[get_session] = _override_session
        fastapi_app.dependency_overrides[get_current_user_id] = _override_user_id
        fastapi_app.dependency_overrides[get_current_user_payload] = _override_payload

        for route in fastapi_app.routes:
            deps = getattr(route, "dependencies", None) or []
            for dep in deps:
                call = getattr(dep, "dependency", None)
                if isinstance(call, RequirePermission):
                    fastapi_app.dependency_overrides[call] = _allow

        yield fastapi_app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_list_users_limit_100_succeeds(client: AsyncClient) -> None:
    """The new frontend default of limit=100 must succeed (200, not 422)."""
    r = await client.get("/api/v1/users/?limit=100")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_list_users_limit_above_cap_still_rejected(
    client: AsyncClient,
) -> None:
    """Cap must remain enforced — frontend can't sneak a bigger limit."""
    r = await client.get("/api/v1/users/?limit=501")
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_list_users_limit_at_the_cap_succeeds(
    client: AsyncClient,
) -> None:
    """The cap itself must be admitted — 500 in, and the test above says 501 out.

    This assertion is the pair of the one above and the reason the module
    exists: the two of them bracket the cap, so it cannot move without both
    numbers moving together. Deliberately the cap and not some historical
    request size, which is what this used to be. It asked for ``limit=200``
    and a 422 until 2026-09-22, true of the 100-row cap the module was
    written against and false from ``36f3ebcb8`` onwards, so it had been
    failing every night for three months while the endpoint served 200 rows
    quite happily. A number chosen for a frontend default drifts out of date
    on its own; the boundary cannot, because it is the thing being guarded.
    """
    r = await client.get("/api/v1/users/?limit=500")
    assert r.status_code == 200, r.text
