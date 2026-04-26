"""Integration tests for Wave-2 user API hardening.

Covers four bugs landing in the same patch:

* BUG-API01    — ``GET /api/v1/users/me`` must resolve to the current user
                 instead of falling through to ``GET /users/{user_id}``
                 and 422-ing on the literal ``"me"``.
* BUG-API02    — RequestValidationError responses must not leak Pydantic
                 detail (path-param names + types) to unauthenticated /
                 anonymous probes — they used to enumerate the route
                 surface from those bodies.
* BUG-RBAC05   — ``RequirePermission`` denial path must log at DEBUG, not
                 WARN. A viewer scrolling normal pages used to flood
                 server logs with hundreds of WARN lines per minute,
                 breaking Datadog/Splunk alert rules.
* BUG-USERS-CR — Admin POST /api/v1/users/ must validate input at the
                 schema boundary: empty / non-RFC email, password < 12
                 chars, and unknown roles ("god", "root", "owner") all
                 reject with 422 instead of being silently persisted.

Run: pytest backend/tests/integration/test_users_api_hardening.py -v
"""

import logging
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def client():
    """Boot the full app once per test (lifespan = module discovery)."""
    app = create_app()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def _register_and_login(
    client: AsyncClient, *, email: str | None = None, password: str = "Hardening123Test"
) -> tuple[str, dict[str, str]]:
    """Register a fresh user and return (email, auth_headers)."""
    if email is None:
        email = f"hard-{uuid.uuid4().hex[:8]}@hardening.io"
    await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Hardening Tester",
        },
    )
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = resp.json().get("access_token", "")
    return email, {"Authorization": f"Bearer {token}"}


async def _promote(email: str, role: str = "admin") -> None:
    """Promote ``email`` to ``role`` via direct DB write (test-only)."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(
            update(User).where(User.email == email.lower()).values(role=role)
        )
        await session.commit()


# ── BUG-API01 ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_users_me_returns_current_user(client):
    """GET /api/v1/users/me with a valid token returns the caller, not 422."""
    email, headers = await _register_and_login(client)

    resp = await client.get("/api/v1/users/me", headers=headers)

    assert resp.status_code == 200, (
        f"Expected 200 from /users/me but got {resp.status_code}: {resp.text!r}"
    )
    body = resp.json()
    assert body.get("email") == email
    assert "permissions" in body  # UserMeResponse extends UserResponse


@pytest.mark.asyncio
async def test_get_users_me_with_trailing_slash_still_works(client):
    """The historical /users/me/ form must keep working (no regression)."""
    email, headers = await _register_and_login(client)
    resp = await client.get("/api/v1/users/me/", headers=headers)
    assert resp.status_code == 200
    assert resp.json().get("email") == email


# ── BUG-API02 ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_users_invalid_uuid_returns_sanitised_error(client):
    """A non-UUID path param must NOT leak the param name or its type.

    Before the fix the body was a Pydantic ``[{"type":"uuid_parsing",
    "loc":["path","user_id"],...}]`` blob that handed unauthenticated
    probes the route schema for free.
    """
    _email, headers = await _register_and_login(client)

    resp = await client.get("/api/v1/users/abc", headers=headers)

    # Either 400 (sanitised) or 401/403 (auth-first) is acceptable — what
    # matters is that the body does NOT mention the param name or type.
    body_text = resp.text.lower()
    assert "user_id" not in body_text, (
        f"Response leaks path-param name 'user_id': {resp.text!r}"
    )
    assert "uuid" not in body_text, (
        f"Response leaks expected type 'UUID': {resp.text!r}"
    )
    assert "uuid_parsing" not in body_text


# ── BUG-USERS-CREATE ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_create_user_rejects_weak_password(client):
    email, headers = await _register_and_login(client)
    await _promote(email, "admin")
    # Re-login so the new role makes it into the JWT permissions claim.
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": "Hardening123Test"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = await client.post(
        "/api/v1/users/",
        headers=headers,
        json={
            "email": f"weak-{uuid.uuid4().hex[:6]}@hardening.io",
            "password": "123",
            "full_name": "Weak Password",
            "role": "viewer",
        },
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_admin_create_user_rejects_unknown_role(client):
    email, headers = await _register_and_login(client)
    await _promote(email, "admin")
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": "Hardening123Test"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = await client.post(
        "/api/v1/users/",
        headers=headers,
        json={
            "email": f"god-{uuid.uuid4().hex[:6]}@hardening.io",
            "password": "StrongerThanTwelveChars1",
            "full_name": "God Mode",
            "role": "god",
        },
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_admin_create_user_rejects_blank_email(client):
    """Empty / non-RFC email must be rejected at the schema boundary."""
    email, headers = await _register_and_login(client)
    await _promote(email, "admin")
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": "Hardening123Test"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = await client.post(
        "/api/v1/users/",
        headers=headers,
        json={
            "email": "",
            "password": "StrongerThanTwelveChars1",
            "full_name": "Blank",
            "role": "viewer",
        },
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_admin_create_user_succeeds_with_valid_input(client):
    """Happy path: admin creates a viewer with a strong password."""
    email, headers = await _register_and_login(client)
    await _promote(email, "admin")
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": "Hardening123Test"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    new_email = f"created-{uuid.uuid4().hex[:8]}@hardening.io"
    resp = await client.post(
        "/api/v1/users/",
        headers=headers,
        json={
            "email": new_email,
            "password": "StrongPassword12345",
            "full_name": "Admin-created Viewer",
            "role": "viewer",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == new_email
    assert body["role"] == "viewer"
    assert body["is_active"] is True


# ── BUG-RBAC05 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_permission_denial_logged_at_debug_not_warn(client, caplog):
    """RequirePermission denials must NOT show up at WARN level any more.

    A viewer hits an admin-only endpoint; we capture every record the
    ``app.dependencies`` logger emits and assert no WARN/CRITICAL line
    references the denied permission. The WARNING channel exists for
    genuinely suspicious patterns, not for the routine "viewer scrolled
    past a button the UI already knew was gated" case that flooded logs.
    """
    # Register a user — bootstrap path makes them admin if first.
    email, _ = await _register_and_login(client)
    # Force them to viewer so the permission check actually denies.
    await _promote(email, "viewer")
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": "Hardening123Test"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    with caplog.at_level(logging.DEBUG, logger="app.dependencies"):
        # users.create requires ADMIN — viewer must hit RequirePermission's
        # denial branch.
        resp = await client.post(
            "/api/v1/users/",
            headers=headers,
            json={
                "email": f"denied-{uuid.uuid4().hex[:6]}@hardening.io",
                "password": "StrongerThanTwelveChars1",
                "full_name": "Should Not Be Created",
                "role": "viewer",
            },
        )

    assert resp.status_code == 403, resp.text

    offending = [
        rec
        for rec in caplog.records
        if rec.name.startswith("app.dependencies")
        and rec.levelno >= logging.WARNING
        and "permission" in rec.getMessage().lower()
    ]
    assert not offending, (
        "Permission denials must not log at WARN+; got: "
        + "\n".join(f"{r.levelname} {r.getMessage()}" for r in offending)
    )
