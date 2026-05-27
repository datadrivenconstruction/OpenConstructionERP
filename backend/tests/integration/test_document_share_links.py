"""Integration tests for documents.share-link endpoints.

Covers the seven scenarios from the spec:

    1. Owner can create a share link and receives ``{token, url, …}``
    2. Anonymous access with no password → 401 when one is required
    3. Anonymous access with the wrong password → 401
    4. Anonymous access with the right password → ``download_url`` is
       returned and ``download_count`` increments
    5. Expired link → 404
    6. Revoked link → 404
    7. Non-owner cannot revoke a link → 403 (mapped to 404 by
       :func:`verify_project_access` to avoid leaking project ids)

All tests reuse the smoke-test fixtures (``client``, ``auth_headers``)
so the in-memory SQLite + lifespan plumbing is set up once at session
scope.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def client():
    """FastAPI test client with full app lifespan (modules + DDL)."""
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


async def _register_admin(client: AsyncClient) -> tuple[dict[str, str], str]:
    """Register a fresh admin, return Bearer headers + user id."""
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    unique = uuid.uuid4().hex[:8]
    email = f"share-{unique}@smoke.io"
    password = f"ShareTest{unique}9!"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Share Tester"},
    )
    assert reg.status_code == 201, reg.text

    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()

    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = resp.json().get("access_token", "")
    assert token, resp.text
    user_id = reg.json().get("id", "")
    return {"Authorization": f"Bearer {token}"}, user_id


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    headers, _ = await _register_admin(client)
    return headers


@pytest_asyncio.fixture
async def project_id(client: AsyncClient, auth_headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": "Share Link Test",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


@pytest_asyncio.fixture
async def document_id(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project_id: str,
    tmp_path,
) -> str:
    """Upload a real document so the share-link access endpoint can resolve
    a file path. Returns the document id.
    """
    # Use the upload endpoint so the file lands inside UPLOAD_BASE.
    pdf_bytes = b"%PDF-1.4\n%shared test\n%%EOF"
    files = {"file": ("share_me.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    resp = await client.post(
        f"/api/v1/documents/upload/?project_id={project_id}",
        files=files,
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── 1. Owner creates a link ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_creates_share_link(
    client: AsyncClient,
    auth_headers: dict[str, str],
    document_id: str,
) -> None:
    resp = await client.post(
        f"/api/v1/documents/{document_id}/share-links/",
        json={"password": "letmein", "expires_in_days": 7},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["token"], "token must be returned"
    assert len(body["token"]) >= 32, "token must be at least 32 chars URL-safe"
    assert body["url"].endswith(body["token"])
    assert body["url"].startswith("/share/")
    assert body["requires_password"] is True
    assert body["expires_at"] is not None
    assert body["download_count"] == 0
    assert body["revoked"] is False


# ── 2. Anonymous w/ no password → 401 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_access_without_password_is_unauthorized(
    client: AsyncClient,
    auth_headers: dict[str, str],
    document_id: str,
) -> None:
    create = await client.post(
        f"/api/v1/documents/{document_id}/share-links/",
        json={"password": "letmein"},
        headers=auth_headers,
    )
    assert create.status_code == 201
    token = create.json()["token"]

    # No auth header → anonymous. No password in body either.
    resp = await client.post(
        f"/api/v1/documents/share-links/{token}/access/",
        json={},
    )
    assert resp.status_code == 401, resp.text


# ── 3. Wrong password → 401 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_access_with_wrong_password_is_unauthorized(
    client: AsyncClient,
    auth_headers: dict[str, str],
    document_id: str,
) -> None:
    create = await client.post(
        f"/api/v1/documents/{document_id}/share-links/",
        json={"password": "letmein"},
        headers=auth_headers,
    )
    token = create.json()["token"]

    resp = await client.post(
        f"/api/v1/documents/share-links/{token}/access/",
        json={"password": "wrongpw"},
    )
    assert resp.status_code == 401, resp.text


# ── 4. Right password → download_url + count incremented ───────────────────


@pytest.mark.asyncio
async def test_access_with_right_password_returns_url_and_bumps_count(
    client: AsyncClient,
    auth_headers: dict[str, str],
    document_id: str,
) -> None:
    create = await client.post(
        f"/api/v1/documents/{document_id}/share-links/",
        json={"password": "letmein"},
        headers=auth_headers,
    )
    token = create.json()["token"]
    link_id = create.json()["id"]

    # Right password.
    resp = await client.post(
        f"/api/v1/documents/share-links/{token}/access/",
        json={"password": "letmein"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["download_url"], "download_url must be returned"
    assert token in body["download_url"]
    assert body["filename"] == "share_me.pdf"

    # Hit it twice more — count must be 3 after.
    for _ in range(2):
        r = await client.post(
            f"/api/v1/documents/share-links/{token}/access/",
            json={"password": "letmein"},
        )
        assert r.status_code == 200

    # List endpoint surfaces the count to the owner.
    listing = await client.get(
        f"/api/v1/documents/{document_id}/share-links/",
        headers=auth_headers,
    )
    assert listing.status_code == 200
    rows = listing.json()
    mine = next(r for r in rows if r["id"] == link_id)
    assert mine["download_count"] == 3, mine


# ── 5. Expired link → 404 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_expired_link_returns_404(
    client: AsyncClient,
    auth_headers: dict[str, str],
    document_id: str,
) -> None:
    create = await client.post(
        f"/api/v1/documents/{document_id}/share-links/",
        json={"expires_in_days": 1},
        headers=auth_headers,
    )
    assert create.status_code == 201
    token = create.json()["token"]

    # Backdate ``expires_at`` directly so we don't have to wait.
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.documents.share_models import DocumentShareLink

    past = datetime.now(tz=UTC) - timedelta(days=2)
    async with async_session_factory() as session:
        await session.execute(
            sa_update(DocumentShareLink).where(DocumentShareLink.token == token).values(expires_at=past)
        )
        await session.commit()

    # Public probe still surfaces ``expired=True`` (so the UI can render
    # a useful message) but access returns 404.
    info = await client.get(f"/api/v1/documents/share-links/{token}/")
    assert info.status_code == 200, info.text
    assert info.json()["expired"] is True

    access = await client.post(
        f"/api/v1/documents/share-links/{token}/access/",
        json={},
    )
    assert access.status_code == 404, access.text


# ── 6. Revoked link → 404 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoked_link_returns_404(
    client: AsyncClient,
    auth_headers: dict[str, str],
    document_id: str,
) -> None:
    create = await client.post(
        f"/api/v1/documents/{document_id}/share-links/",
        json={"password": "secret"},
        headers=auth_headers,
    )
    assert create.status_code == 201
    token = create.json()["token"]
    link_id = create.json()["id"]

    # Revoke via DELETE.
    delete = await client.delete(
        f"/api/v1/documents/{document_id}/share-links/{link_id}/",
        headers=auth_headers,
    )
    assert delete.status_code == 204, delete.text

    # Probe + access both 404.
    info = await client.get(f"/api/v1/documents/share-links/{token}/")
    assert info.status_code == 404

    access = await client.post(
        f"/api/v1/documents/share-links/{token}/access/",
        json={"password": "secret"},
    )
    assert access.status_code == 404

    # Revoked links are filtered from the owner-only list.
    listing = await client.get(
        f"/api/v1/documents/{document_id}/share-links/",
        headers=auth_headers,
    )
    assert listing.status_code == 200
    assert not any(r["id"] == link_id for r in listing.json())


# ── 7. Non-owner cannot revoke ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_owner_cannot_revoke_share_link(
    client: AsyncClient,
    auth_headers: dict[str, str],
    document_id: str,
) -> None:
    """A different user must not be able to revoke a link they didn't create.

    ``verify_project_access`` returns 404 (not 403) by design — leaking
    "project exists, but you're not allowed" is itself an information
    disclosure. The contract is the same: the operation must NOT succeed
    for a stranger.
    """
    create = await client.post(
        f"/api/v1/documents/{document_id}/share-links/",
        json={},
        headers=auth_headers,
    )
    assert create.status_code == 201
    link_id = create.json()["id"]

    # Register a SECOND user — not admin, fresh non-owner.
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    unique = uuid.uuid4().hex[:8]
    email = f"stranger-{unique}@smoke.io"
    password = f"Stranger{unique}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Stranger"},
    )
    assert reg.status_code == 201
    # Promote to editor so `documents.update` permission is held — the
    # 403 we care about must come from project-access, NOT a missing role.
    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="editor", is_active=True))
        await session.commit()
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    stranger_token = login.json()["access_token"]
    stranger_headers = {"Authorization": f"Bearer {stranger_token}"}

    resp = await client.delete(
        f"/api/v1/documents/{document_id}/share-links/{link_id}/",
        headers=stranger_headers,
    )
    # 404 from verify_project_access OR 403 (if a future change tightens
    # to a real forbidden) — either way the operation must NOT succeed.
    assert resp.status_code in (403, 404), resp.text

    # Original owner can still see the link — proves the stranger's
    # request didn't accidentally mutate state.
    listing = await client.get(
        f"/api/v1/documents/{document_id}/share-links/",
        headers=auth_headers,
    )
    assert listing.status_code == 200
    assert any(r["id"] == link_id for r in listing.json())


# ── 8. Public probe surfaces filename + requires_password ──────────────────


@pytest.mark.asyncio
async def test_public_probe_returns_filename_and_flags(
    client: AsyncClient,
    auth_headers: dict[str, str],
    document_id: str,
) -> None:
    # Open link (no password, no expiry).
    create_open = await client.post(
        f"/api/v1/documents/{document_id}/share-links/",
        json={},
        headers=auth_headers,
    )
    assert create_open.status_code == 201
    open_token = create_open.json()["token"]

    info = await client.get(f"/api/v1/documents/share-links/{open_token}/")
    assert info.status_code == 200
    body = info.json()
    assert body["filename"] == "share_me.pdf"
    assert body["requires_password"] is False
    assert body["expired"] is False
