"""Integration tests for the admin-controlled public demo-login switch.

A site admin can turn the password-free "Try demo" sign-in on or off from the
Settings screen. The choice is persisted in a small JSON file in the data dir
(``app.core.demo_login``) - no database column, no migration.

Covers:
    * Demo login succeeds while the switch is on (the default).
    * Turning the switch off refuses the demo-login endpoint with a clear 403,
      then turning it back on restores access - exercised through the real
      persisted store, not a mock, so the read+write+enforce path is proven end
      to end.
    * The public first-run probe folds the switch into ``demo_enabled`` so the
      login page hides the "Try demo" block when the switch is off.
    * The password-free shortcut in the normal login form stops accepting demo
      emails once the switch is off (no back door around the switch).
    * The admin GET/PUT endpoints are gated (401 without a token).
    * The persisted store round-trips and defaults to enabled.

The demo accounts are auto-seeded on startup by ``app.main._seed_demo_account``
inside the regular lifespan, so we don't register them ourselves.

The switch covers every demo tile alike, so the tests that expect a session
sign in through a tile below admin. This module runs on the suite's shared
database, where a real administrator usually exists by then, and next to one
the Admin tile is refused by a separate rule (``app.core.demo_admin``) that
would otherwise decide these tests by the order they ran in.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.demo_login import (
    demo_login_enabled,
    demo_login_flag_path,
    set_demo_login_enabled,
)
from app.main import create_app

#: A seeded demo tile whose role is below admin, so the superseded-admin rule
#: never applies to it, whatever else the shared database holds.
DEMO_TILE_EMAIL = "manager@openconstructionerp.com"


@pytest_asyncio.fixture(scope="module")
async def demo_client():
    # Force-enable seeding even when the test runner sets SEED_DEMO=false
    # upstream - this fixture's app must boot with the demo accounts in place.
    os.environ["SEED_DEMO"] = "true"
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture(autouse=True)
def _restore_demo_login_flag():
    """Snapshot and restore the persisted flag file around every test.

    The tests write the real flag file; this returns the data dir to its
    pre-test state afterwards so nothing leaks between tests or out of the run.
    """
    path = demo_login_flag_path()
    original = path.read_text(encoding="utf-8") if path.exists() else None
    try:
        yield
    finally:
        if original is not None:
            path.write_text(original, encoding="utf-8")
        else:
            path.unlink(missing_ok=True)


async def _post_demo_login(client: AsyncClient):
    """POST the demo-login endpoint, retrying briefly for seeder warmup."""
    last = None
    for _ in range(5):
        last = await client.post(
            "/api/v1/users/auth/demo-login/",
            json={"email": DEMO_TILE_EMAIL},
        )
        if last.status_code == 200:
            return last
        await asyncio.sleep(0.2)
    return last


class TestDemoLoginToggle:
    async def test_demo_login_allowed_when_enabled(self, demo_client: AsyncClient) -> None:
        """With the switch on (default), the demo login mints tokens."""
        set_demo_login_enabled(True)
        resp = await _post_demo_login(demo_client)
        assert resp is not None
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["access_token"]
        assert body["refresh_token"]

    async def test_demo_login_refused_when_disabled_then_restored(
        self,
        demo_client: AsyncClient,
    ) -> None:
        """Turning the switch off refuses the demo login with a clear 403;
        turning it back on restores access. Real persisted store, no mock."""
        set_demo_login_enabled(False)
        resp = await demo_client.post(
            "/api/v1/users/auth/demo-login/",
            json={"email": DEMO_TILE_EMAIL},
        )
        assert resp.status_code == 403, resp.text
        assert "administrator" in (resp.json().get("detail") or "").lower()

        # Flip it back on - demo login works again.
        set_demo_login_enabled(True)
        resp = await _post_demo_login(demo_client)
        assert resp is not None
        assert resp.status_code == 200, resp.text
        assert resp.json()["access_token"]

    async def test_first_run_reflects_switch(self, demo_client: AsyncClient) -> None:
        """The public first-run probe folds the switch into ``demo_enabled`` so
        the login page hides its demo block when the switch is off."""
        set_demo_login_enabled(True)
        resp = await demo_client.get("/api/v1/auth/first-run/")
        assert resp.status_code == 200, resp.text
        assert resp.json().get("demo_enabled") is True

        set_demo_login_enabled(False)
        resp = await demo_client.get("/api/v1/auth/first-run/")
        assert resp.status_code == 200, resp.text
        assert resp.json().get("demo_enabled") is False

    async def test_manual_login_shortcut_disabled_when_switch_off(
        self,
        demo_client: AsyncClient,
    ) -> None:
        """The password-free shortcut in the normal login form must not accept a
        demo email once the switch is off - it falls through to the real
        password-verify path, which rejects the wrong password with 401."""
        set_demo_login_enabled(False)
        resp = await demo_client.post(
            "/api/v1/users/auth/login/",
            json={"email": "demo@openconstructionerp.com", "password": "wrong-on-purpose"},
        )
        assert resp.status_code == 401, resp.text

    async def test_admin_setting_endpoints_require_auth(self, demo_client: AsyncClient) -> None:
        """The admin read/write endpoints reject an unauthenticated caller."""
        resp = await demo_client.get("/api/v1/users/auth/demo-login/settings/")
        assert resp.status_code == 401, resp.text

        resp = await demo_client.put(
            "/api/v1/users/auth/demo-login/settings/",
            json={"enabled": False},
        )
        assert resp.status_code == 401, resp.text


def test_flag_store_round_trip(tmp_path) -> None:
    """The persisted store defaults to enabled and round-trips a written value."""
    # No file yet -> the historical default is "enabled".
    assert demo_login_enabled(tmp_path) is True

    assert set_demo_login_enabled(False, tmp_path) is False
    assert demo_login_enabled(tmp_path) is False

    assert set_demo_login_enabled(True, tmp_path) is True
    assert demo_login_enabled(tmp_path) is True


def test_flag_store_fails_closed_on_corrupt_file(tmp_path) -> None:
    """A corrupt flag file fails closed: the demo login is treated as off rather
    than silently re-opening a password-free login the admin may have switched
    off. Only a genuinely absent file keeps the historical "enabled" default."""
    demo_login_flag_path(tmp_path).write_text("{ not json", encoding="utf-8")
    assert demo_login_enabled(tmp_path) is False
