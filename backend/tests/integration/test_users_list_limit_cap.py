"""Regression: GET /v1/users/ limit cap contract.

Source defect (user error log openconstructionerp-log-2026-05-22.json,
v4.3.2): the /admin/audit-log page (and other resolvers) defaulted to
``limit=200`` against this endpoint, but the backend caps it at 100 —
every audit-log mount fired a 422. The frontend default is now 100.
These tests lock the two ends of the contract:

* limit=100 → 200 OK (the new frontend default).
* limit=101 → 422 (the cap stays enforced).

Uses the lightweight test pattern (mount just the users router on a
minimal FastAPI app with auth/perm/session dependencies stubbed) to
avoid the full ``create_app()`` boot path — see comment in
``test_crm_opportunities_limit.py`` for the rationale.
"""

from __future__ import annotations

import tempfile
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _register_minimal_models() -> None:
    import app.core.audit  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def app() -> AsyncGenerator[FastAPI, None]:
    tmp_db = Path(tempfile.mkdtemp()) / "users_limit.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_db.as_posix()}",
        future=True,
    )

    _register_minimal_models()

    from app.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

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

    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


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
    r = await client.get("/api/v1/users/?limit=101")
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_list_users_legacy_oversized_limit_still_rejected(
    client: AsyncClient,
) -> None:
    """The exact previously-shipped frontend default of 200 — must 422.

    Locks the contract: future code can't silently raise the cap.
    """
    r = await client.get("/api/v1/users/?limit=200")
    assert r.status_code == 422, r.text
