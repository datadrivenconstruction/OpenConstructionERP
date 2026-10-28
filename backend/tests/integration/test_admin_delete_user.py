"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for admin-initiated account deletion (issue #272).

Until now an administrator could only deactivate an account; the row, and its
email, stayed on the books. ``DELETE /users/{id}`` lets an admin erase another
user's account the same way the self-service path does - anonymised in place so
the user's projects and history keep resolving, but every personal field is
stripped and the account can no longer log in.

Covers:
    * Test A - an admin deletes another user: 204, the row is anonymised
      (is_active False, placeholder email) and the original credentials no
      longer authenticate.
    * Test B - an admin cannot delete their own account through this route
      (400); self-deletion must go through account settings.
    * Test C - deleting an unknown / already-deleted user returns 404.
    * Test D - a non-admin (viewer) is refused by the permission gate (403).

The module-scoped client + auth fixtures mirror
``test_bim_upload_converter_preflight.py``.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# --- Module-scoped fixtures -------------------------------------------------


@pytest_asyncio.fixture(scope="module")
async def admindel_client():
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
    data: dict = {}
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
async def admin_auth(admindel_client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"admindel-{unique}@test.io"
    password = f"AdminDel{unique}9"

    reg = await admindel_client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Admin Delete Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    from tests.integration._auth_helpers import promote_to_admin

    await promote_to_admin(email)

    token = await _login(admindel_client, email, password)
    assert token, "Admin login failed"
    return {"Authorization": f"Bearer {token}"}


async def _create_user(
    client: AsyncClient,
    admin_auth: dict[str, str],
    *,
    role: str = "viewer",
) -> tuple[str, str, str]:
    """Admin-create a user and return (id, email, password)."""
    unique = uuid.uuid4().hex[:8]
    email = f"target-{unique}@test.io"
    password = f"TargetPass{unique}9"
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": email,
            "password": password,
            "full_name": "Target User",
            "role": role,
        },
        headers=admin_auth,
    )
    assert resp.status_code == 201, f"User create failed ({resp.status_code}): {resp.text}"
    return resp.json()["id"], email, password


# --- Tests ------------------------------------------------------------------


class TestAdminDeleteUser:
    """issue #272 - admin can delete (erase) an account, not only disable it."""

    async def test_admin_deletes_user_anonymises_in_place(
        self,
        admindel_client: AsyncClient,
        admin_auth: dict[str, str],
    ) -> None:
        user_id, email, password = await _create_user(admindel_client, admin_auth)

        # The freshly created account can log in before deletion.
        assert await _login(admindel_client, email, password), "target should log in pre-delete"

        resp = await admindel_client.delete(f"/api/v1/users/{user_id}", headers=admin_auth)
        assert resp.status_code == 204, resp.text

        # Row survives but is anonymised: inactive + placeholder email.
        got = await admindel_client.get(f"/api/v1/users/{user_id}", headers=admin_auth)
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["is_active"] is False
        assert body["email"].startswith("deleted+"), body["email"]

        # Original credentials no longer authenticate.
        assert not await _login(admindel_client, email, password), "erased account must not log in"

    async def test_admin_cannot_delete_self(
        self,
        admindel_client: AsyncClient,
        admin_auth: dict[str, str],
    ) -> None:
        me = await admindel_client.get("/api/v1/users/me/", headers=admin_auth)
        assert me.status_code == 200, me.text
        my_id = me.json()["id"]

        resp = await admindel_client.delete(f"/api/v1/users/{my_id}", headers=admin_auth)
        assert resp.status_code == 400, resp.text

        # And the admin can still authenticate / act afterwards.
        still = await admindel_client.get("/api/v1/users/me/", headers=admin_auth)
        assert still.status_code == 200, still.text

    async def test_delete_missing_user_returns_404(
        self,
        admindel_client: AsyncClient,
        admin_auth: dict[str, str],
    ) -> None:
        resp = await admindel_client.delete(
            f"/api/v1/users/{uuid.uuid4()}",
            headers=admin_auth,
        )
        assert resp.status_code == 404, resp.text

    async def test_non_admin_cannot_delete(
        self,
        admindel_client: AsyncClient,
        admin_auth: dict[str, str],
    ) -> None:
        # A second account to be the (forbidden) caller, and a third as target.
        _viewer_id, viewer_email, viewer_pw = await _create_user(admindel_client, admin_auth)
        target_id, _t_email, _t_pw = await _create_user(admindel_client, admin_auth)

        viewer_token = await _login(admindel_client, viewer_email, viewer_pw)
        assert viewer_token, "viewer login failed"
        viewer_auth = {"Authorization": f"Bearer {viewer_token}"}

        resp = await admindel_client.delete(f"/api/v1/users/{target_id}", headers=viewer_auth)
        assert resp.status_code == 403, resp.text

        # The target is untouched - an admin can still read it as active.
        got = await admindel_client.get(f"/api/v1/users/{target_id}", headers=admin_auth)
        assert got.status_code == 200, got.text
        assert got.json()["is_active"] is True
