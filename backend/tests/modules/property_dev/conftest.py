"""Shared fixtures for property_dev R7 security tests.

Per ``feedback_test_isolation.md`` we redirect ``DATABASE_URL`` to a
per-module temp SQLite file BEFORE the app is first imported. This file
exists ONLY for the R7 test suite — the legacy integration tests in
``backend/tests/integration/test_property_dev_*`` keep their own
per-file scaffolds.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-propdev-r7-"))
_TMP_DB = _TMP_DIR / "propdev_r7.db"
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

        # Import every module's models so create_all sees all tables.
        from app.modules.property_dev import models as _propdev_models  # noqa: F401

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

    Public ``/auth/register`` demotes to viewer + ``is_active=False`` since
    v2.5.2 admin-approve default. Bypass both gates for the test suite.
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

    Returns ``(user_id, email, header)``.
    """
    tag = tag or uuid.uuid4().hex[:8]
    email = f"propdev-r7-{tag}@test.io"
    password = f"PropDevR7{tag}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"PropDev R7 Tester {tag}",
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
