# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Auth gate on the in-app upgrade endpoint (GHSA-pc2c-6g89-xxcr).

POST /api/system/upgrade shells out to ``pip install --upgrade`` and used to run
with NO authentication, so anyone who could reach the API could force a
reinstall / downgrade. It now requires an authenticated ``admin``. These tests
prove the gate without ever executing pip: an autouse fixture forces
``ALLOW_RUNTIME_UPGRADE=false`` so even a request that clears the auth gate stops
at the feature flag instead of touching the environment.
"""

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update as sa_update

from app.database import async_session_factory
from app.main import create_app
from app.modules.users.models import User


@pytest.fixture(autouse=True)
def _disable_runtime_upgrade(monkeypatch):
    """Belt and braces: never let a test actually run pip, even if auth passes."""
    monkeypatch.setenv("ALLOW_RUNTIME_UPGRADE", "false")


@pytest_asyncio.fixture(scope="module")
async def client():
    # Module-scoped so the app lifespan (which, under the local embedded-PG
    # setup, tears down the shared cluster on shutdown) runs once for the whole
    # module rather than per test.
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def _register_with_role(client: AsyncClient, role: str) -> dict[str, str]:
    """Register a fresh user, force its role via the ORM, and return auth headers."""
    unique = uuid.uuid4().hex[:8]
    email = f"upgrade-{role}-{unique}@test.io"
    password = f"UpgradeTest{unique}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Upgrade Tester"},
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"
    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await session.commit()
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = resp.json().get("access_token", "")
    assert token, f"Login failed: {resp.text}"
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_upgrade_rejects_unauthenticated(client):
    resp = await client.post("/api/system/upgrade")
    assert resp.status_code == 401, resp.text
    assert "disabled" not in resp.text.lower()  # never reached the handler body


@pytest.mark.asyncio
async def test_upgrade_forbidden_for_non_admin(client):
    headers = await _register_with_role(client, "viewer")
    resp = await client.post("/api/system/upgrade", headers=headers)
    assert resp.status_code == 403, resp.text
    # Blocked at the role gate, not at the feature flag.
    assert "disabled" not in resp.text.lower()


@pytest.mark.asyncio
async def test_upgrade_admin_clears_auth_gate(client):
    headers = await _register_with_role(client, "admin")
    resp = await client.post("/api/system/upgrade", headers=headers)
    # Admin passes RequireRole; the autouse flag=false then stops it before pip,
    # so a 403 whose detail mentions the disabled flag proves auth succeeded.
    assert resp.status_code == 403, resp.text
    assert "disabled" in resp.text.lower()


# ── P-17: off unless switched on, and never for a demo login ────────────────
#
# The switch used to default to on, so any admin session could run pip in the
# environment the server runs from, and the seeded demo login is an admin that
# needs no password wherever the demo login is offered. These tests replace pip
# with a trap: a refusal that failed would start a job, and the trap fails the
# test instead of touching the environment.


@pytest.fixture
def pip_trap(monkeypatch):
    import app.main as main_module

    def _no_pip(*_args, **_kwargs):
        raise AssertionError("the upgrade route reached pip")

    monkeypatch.setattr(main_module, "claim_upgrade", _no_pip)
    monkeypatch.setattr(main_module, "run_upgrade", _no_pip)


async def _demo_admin_headers() -> dict[str, str]:
    """A token for the seeded demo admin, creating the account if this database has none."""
    from sqlalchemy import select

    from app.config import get_settings
    from app.modules.users.service import create_access_token, hash_password

    async with async_session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == "demo@openconstructionerp.com"))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                id=uuid.uuid4(),
                email="demo@openconstructionerp.com",
                hashed_password=hash_password(uuid.uuid4().hex),
                full_name="Demo Admin",
                role="admin",
                locale="en",
                is_active=True,
                metadata_={},
            )
            session.add(user)
        else:
            user.role = "admin"
            user.is_active = True
        await session.commit()
        await session.refresh(user)
        token = create_access_token(user, get_settings())
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_upgrade_is_off_when_the_switch_is_not_set(client, monkeypatch, pip_trap):
    monkeypatch.delenv("ALLOW_RUNTIME_UPGRADE", raising=False)
    headers = await _register_with_role(client, "admin")
    resp = await client.post("/api/system/upgrade", headers=headers)
    assert resp.status_code == 403, resp.text
    assert "ALLOW_RUNTIME_UPGRADE=true" in resp.json()["detail"]

    check = await client.get("/api/system/version-check", headers=headers)
    assert check.status_code == 200, check.text
    assert check.json()["runtime_upgrade_allowed"] is False
    assert check.json()["runtime_upgrade_blocked"] == "disabled"


@pytest.mark.asyncio
async def test_a_demo_admin_is_refused_even_with_the_switch_on(client, monkeypatch, pip_trap):
    monkeypatch.setenv("ALLOW_RUNTIME_UPGRADE", "true")
    headers = await _demo_admin_headers()
    resp = await client.post("/api/system/upgrade", headers=headers)
    assert resp.status_code == 403, resp.text
    assert "Demo accounts" in resp.json()["detail"]

    check = await client.get("/api/system/version-check", headers=headers)
    assert check.json()["runtime_upgrade_allowed"] is False
    assert check.json()["runtime_upgrade_blocked"] == "demo_account"


@pytest.mark.asyncio
async def test_a_real_admin_is_offered_the_button_when_the_switch_is_on(client, monkeypatch):
    monkeypatch.setenv("ALLOW_RUNTIME_UPGRADE", "true")
    headers = await _register_with_role(client, "admin")
    check = await client.get("/api/system/version-check", headers=headers)
    assert check.status_code == 200, check.text
    assert check.json()["runtime_upgrade_allowed"] is True
    assert check.json()["runtime_upgrade_blocked"] is None
