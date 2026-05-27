"""Shared fixtures for accommodation tests.

Per ``feedback_test_isolation.md`` we redirect ``DATABASE_URL`` to a
per-module temp SQLite file BEFORE the app is first imported.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-accom-"))
_TMP_DB = _TMP_DIR / "accom.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module against the temp SQLite."""
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _force_set_role(email: str, role: str) -> None:
    """Set the user's role + force ``is_active=True``.

    The public ``/auth/register`` endpoint demotes new users to ``viewer``
    AND (since v2.5.2 admin-approve default) lands them ``is_active=False``,
    so login returns 401. This helper bypasses both gates for the test
    suite, mirroring ``promote_to_admin`` but with a user-specified role.
    """
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await session.commit()


async def _register_user(
    client: AsyncClient,
    *,
    role: str = "admin",
    tag: str | None = None,
) -> tuple[str, str, dict[str, str]]:
    """Register + log in a fresh user with the requested role.

    Forces ``is_active=True`` regardless of the registration mode so the
    follow-up login never trips the admin-approve gate.

    Returns ``(user_id, email, header)``.
    """
    tag = tag or uuid.uuid4().hex[:8]
    email = f"accom-{tag}@test.io"
    password = f"AccomTest{tag}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"Accom Tester {tag}",
            "role": role,
        },
    )
    assert reg.status_code in (200, 201), reg.text
    user_id = reg.json()["id"]

    await _force_set_role(email, role)

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    return user_id, email, {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def admin_auth(
    client: AsyncClient,
    request,
) -> tuple[str, dict[str, str]]:
    """Admin caller (full RBAC).

    The tag includes the module's short name so each test file gets its
    own admin row and the second module's fixture doesn't 409 on the
    first module's email (we share one temp SQLite across the whole
    directory via env vars set at conftest import time).
    """
    mod_tag = request.module.__name__.rsplit(".", 1)[-1][-12:]
    uid, _email, header = await _register_user(
        client,
        role="admin",
        tag=f"adm-{mod_tag}",
    )
    return uid, header


@pytest_asyncio.fixture(scope="module")
async def project_id(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
) -> str:
    """A real project owned by the admin caller."""
    _, header = admin_auth
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": "Accommodation Tests",
            "description": "test fixture project",
        },
        headers=header,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


# Exposed for tests that need a fresh, non-admin user to verify IDOR.
@pytest_asyncio.fixture(scope="module")
async def other_user_auth(
    client: AsyncClient,
    request,
) -> tuple[str, dict[str, str]]:
    """A second admin caller in a completely different project."""
    mod_tag = request.module.__name__.rsplit(".", 1)[-1][-12:]
    uid, _email, header = await _register_user(
        client,
        role="admin",
        tag=f"oth-{mod_tag}",
    )
    return uid, header


@pytest_asyncio.fixture(scope="module")
async def other_project_id(
    client: AsyncClient,
    other_user_auth: tuple[str, dict[str, str]],
) -> str:
    """Another project, owned by ``other_user_auth``."""
    _, header = other_user_auth
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": "Accommodation Tests — Other",
            "description": "isolated tenant",
        },
        headers=header,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]
