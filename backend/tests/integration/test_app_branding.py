"""Integration tests for server-persisted white-label branding (issue #272).

Branding used to live only in the browser's localStorage, so it never followed
the workspace to another browser or to an invited user's pre-auth view of the
login page. These endpoints persist it on the server:

    GET    /api/v1/branding/   - public (login page reads it before sign-in)
    PUT    /api/v1/branding/   - admin only
    DELETE /api/v1/branding/   - admin only

Covers:
    * Test A - GET is public (no auth) and reports the default when nothing is
      set.
    * Test B - an admin sets a brand, and a later (even unauthenticated) GET
      reads it back; the trio is reconciled (a logo wins over text).
    * Test C - a non-admin cannot write or clear the brand (403).
    * Test D - a bad logo payload is sanitised rather than stored verbatim.
    * Test E - an admin can clear the brand back to the default.

The module-scoped client + auth fixtures mirror
``test_bim_upload_converter_preflight.py``.
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from contextlib import asynccontextmanager

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

_PNG_DATA_URL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

# --- Module-scoped fixtures -------------------------------------------------


@pytest_asyncio.fixture(scope="module")
async def brand_client():
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def _login(client: AsyncClient, email: str, password: str) -> str:
    token = ""
    for attempt in range(3):
        resp = await client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in (data.get("detail") or ""):
            await asyncio.sleep(5 * (attempt + 1))
            continue
        break
    return token


@pytest_asyncio.fixture(scope="module")
async def brand_admin(brand_client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"brandadm-{unique}@test.io"
    password = f"BrandAdm{unique}9"
    reg = await brand_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Brand Admin", "role": "admin"},
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    from tests.integration._auth_helpers import promote_to_admin

    await promote_to_admin(email)
    token = await _login(brand_client, email, password)
    assert token, "Admin login failed"
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def brand_viewer(brand_client: AsyncClient, brand_admin: dict[str, str]) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"brandview-{unique}@test.io"
    password = f"BrandView{unique}9"
    resp = await brand_client.post(
        "/api/v1/users/",
        json={"email": email, "password": password, "full_name": "Brand Viewer", "role": "viewer"},
        headers=brand_admin,
    )
    assert resp.status_code == 201, f"Viewer create failed: {resp.text}"
    token = await _login(brand_client, email, password)
    assert token, "Viewer login failed"
    return {"Authorization": f"Bearer {token}"}


# --- Tests ------------------------------------------------------------------


class TestAppBranding:
    """issue #272 - workspace branding persists on the server."""

    async def test_get_is_public_and_defaults(
        self,
        brand_client: AsyncClient,
        brand_admin: dict[str, str],
    ) -> None:
        # Reset to a known baseline, then read with NO auth header at all.
        await brand_client.delete("/api/v1/branding/", headers=brand_admin)
        resp = await brand_client.get("/api/v1/branding/")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["mode"] == "default"
        assert body["logo_data_url"] is None
        assert body["company_name"] == ""

    async def test_admin_sets_brand_and_anyone_reads_it(
        self,
        brand_client: AsyncClient,
        brand_admin: dict[str, str],
    ) -> None:
        put = await brand_client.put(
            "/api/v1/branding/",
            json={"mode": "text", "company_name": "Acme Construction"},
            headers=brand_admin,
        )
        assert put.status_code == 200, put.text
        assert put.json()["mode"] == "text"
        assert put.json()["company_name"] == "Acme Construction"

        # A later, unauthenticated read sees the workspace brand.
        got = await brand_client.get("/api/v1/branding/")
        assert got.status_code == 200, got.text
        assert got.json()["company_name"] == "Acme Construction"
        assert got.json()["mode"] == "text"

        # A logo wins over text: setting both reconciles mode to "logo".
        put2 = await brand_client.put(
            "/api/v1/branding/",
            json={"mode": "text", "logo_data_url": _PNG_DATA_URL, "company_name": "Acme"},
            headers=brand_admin,
        )
        assert put2.status_code == 200, put2.text
        assert put2.json()["mode"] == "logo"
        assert put2.json()["logo_data_url"] == _PNG_DATA_URL

    async def test_non_admin_cannot_write_or_clear(
        self,
        brand_client: AsyncClient,
        brand_viewer: dict[str, str],
    ) -> None:
        put = await brand_client.put(
            "/api/v1/branding/",
            json={"mode": "text", "company_name": "Hijack"},
            headers=brand_viewer,
        )
        assert put.status_code == 403, put.text

        delete = await brand_client.delete("/api/v1/branding/", headers=brand_viewer)
        assert delete.status_code == 403, delete.text

    async def test_bad_logo_is_rejected_with_its_rule(
        self,
        brand_client: AsyncClient,
        brand_admin: dict[str, str],
    ) -> None:
        put = await brand_client.put(
            "/api/v1/branding/",
            json={"mode": "logo", "logo_data_url": "javascript:alert(1)", "company_name": ""},
            headers=brand_admin,
        )
        assert put.status_code == 422, put.text
        assert put.json()["detail"]["rule"] == "branding.logo.data_url"

    async def test_svg_logo_is_stored_without_scripts(
        self,
        brand_client: AsyncClient,
        brand_admin: dict[str, str],
    ) -> None:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(2)</script>'
            '<rect width="4" height="4" onclick="x()"/></svg>'
        )
        url = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
        put = await brand_client.put("/api/v1/branding/", json={"logo_data_url": url}, headers=brand_admin)
        assert put.status_code == 200, put.text
        stored = base64.b64decode(put.json()["logo_data_url"].split(",", 1)[1]).decode()
        assert "script" not in stored
        assert "onload" not in stored
        assert "onclick" not in stored
        assert "rect" in stored
        await brand_client.delete("/api/v1/branding/", headers=brand_admin)

    async def test_png_with_wrong_bytes_is_rejected(
        self,
        brand_client: AsyncClient,
        brand_admin: dict[str, str],
    ) -> None:
        fake = "data:image/png;base64," + base64.b64encode(b"<svg onload=1>").decode()
        put = await brand_client.put("/api/v1/branding/", json={"logo_data_url": fake}, headers=brand_admin)
        assert put.status_code == 422, put.text
        assert put.json()["detail"]["rule"] == "branding.logo.content"

    async def test_edit_button_toggle_is_admin_only(
        self,
        brand_client: AsyncClient,
        brand_admin: dict[str, str],
        brand_viewer: dict[str, str],
    ) -> None:
        denied = await brand_client.put("/api/v1/branding/", json={"show_logo_edit": False}, headers=brand_viewer)
        assert denied.status_code == 403, denied.text
        denied_colour = await brand_client.put(
            "/api/v1/branding/", json={"appearance": {"accent_hex": "#123456"}}, headers=brand_viewer
        )
        assert denied_colour.status_code == 403, denied_colour.text

        put = await brand_client.put(
            "/api/v1/branding/",
            json={"company_name": "Keep", "show_logo_edit": False, "appearance": {"accent_hex": "#1A2B3C"}},
            headers=brand_admin,
        )
        assert put.status_code == 200, put.text
        got = (await brand_client.get("/api/v1/branding/")).json()
        assert got["show_logo_edit"] is False
        assert got["appearance"]["accent_hex"] == "#1a2b3c"
        await brand_client.delete("/api/v1/branding/", headers=brand_admin)

    async def test_admin_can_clear_brand(
        self,
        brand_client: AsyncClient,
        brand_admin: dict[str, str],
    ) -> None:
        await brand_client.put(
            "/api/v1/branding/",
            json={"mode": "text", "company_name": "Temporary"},
            headers=brand_admin,
        )
        cleared = await brand_client.delete("/api/v1/branding/", headers=brand_admin)
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["mode"] == "default"

        got = await brand_client.get("/api/v1/branding/")
        assert got.json()["mode"] == "default"
        assert got.json()["company_name"] == ""
