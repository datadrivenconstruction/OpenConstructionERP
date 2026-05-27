"""Integration tests for the password-free demo-login endpoint (v2.6.22).

Covers:
    * Test A — POST /auth/demo-login/ with a whitelisted, seeded email
      returns a valid token pair.
    * Test B — POST /auth/demo-login/ with a NON-whitelisted email returns
      a generic 401 (no enumeration leak about which emails are demo).
    * Test C — When SEED_DEMO=false, the endpoint disables itself and
      returns 404 even for a whitelisted email.
    * Test D — Whitelist must match the seeder spec list — a sync-test
      that fails loudly if the two lists drift apart (BUG-D02 guard).

The demo accounts are auto-seeded on startup by ``app.main._seed_demo_account``
inside the regular lifespan, so we don't need to register them ourselves.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def demo_client():
    # Force-enable seeding even when the test runner sets SEED_DEMO=false
    # somewhere upstream — this fixture's app must boot with the demo
    # accounts in place.
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


class TestDemoLoginEndpoint:
    """v2.6.22 demo-login coverage."""

    async def test_whitelisted_email_returns_tokens(
        self,
        demo_client: AsyncClient,
    ) -> None:
        # Hit the endpoint a few times in case the seeder is still warming
        # up — the lifespan completes before yield, but on slow CI Postgres
        # writes occasionally lag the read.
        last_resp = None
        for _ in range(5):
            resp = await demo_client.post(
                "/api/v1/users/auth/demo-login/",
                json={"email": "demo@openestimator.io"},
            )
            last_resp = resp
            if resp.status_code == 200:
                break
            await asyncio.sleep(0.2)

        assert last_resp is not None
        assert last_resp.status_code == 200, last_resp.text
        body = last_resp.json()
        assert body["access_token"], body
        assert body["refresh_token"], body
        assert body["expires_in"] > 0

    async def test_non_whitelisted_email_returns_401(
        self,
        demo_client: AsyncClient,
    ) -> None:
        resp = await demo_client.post(
            "/api/v1/users/auth/demo-login/",
            json={"email": f"intruder-{uuid.uuid4().hex[:8]}@evil.example.com"},
        )
        assert resp.status_code == 401, resp.text
        # Must NOT leak whitelist membership in the detail string.
        assert "demo" not in (resp.json().get("detail") or "").lower(), (
            "Endpoint must not reveal demo whitelist contents."
        )

    async def test_seed_demo_disabled_returns_404(
        self,
        demo_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SEED_DEMO", "false")
        try:
            resp = await demo_client.post(
                "/api/v1/users/auth/demo-login/",
                json={"email": "demo@openestimator.io"},
            )
            assert resp.status_code == 404, resp.text
            assert "disabled" in (resp.json().get("detail") or "").lower()
        finally:
            monkeypatch.setenv("SEED_DEMO", "true")

    async def test_whitelist_matches_seeder_spec(self) -> None:
        """Sync guard — whitelist in router AND service MUST match seeder.

        If someone adds a new demo account to ``_seed_demo_account`` they
        also need to add it to ``router._DEMO_EMAIL_WHITELIST`` and
        ``service._DEMO_EMAIL_WHITELIST`` (used by the BUG-D02 shortcut in
        :py:meth:`UserService.login`) or demo login silently breaks for
        one of them.
        """
        # Pull the seeder's spec list by importing the function module
        # and reading the literal — keeps the test independent of any
        # runtime side-effects.
        import inspect

        from app.main import _seed_demo_account
        from app.modules.users.router import (
            _DEMO_EMAIL_WHITELIST as ROUTER_WHITELIST,
        )
        from app.modules.users.service import (
            _DEMO_EMAIL_WHITELIST as SERVICE_WHITELIST,
        )

        src = inspect.getsource(_seed_demo_account)
        seeded_emails = {
            line.split('"email":')[1].split('"')[1]
            for line in src.splitlines()
            if '"email":' in line and "@openestimator.io" in line
        }
        assert seeded_emails, "Could not parse seeder spec list — has _seed_demo_account changed?"
        assert seeded_emails == set(ROUTER_WHITELIST), (
            f"Whitelist drift: seeder={seeded_emails!r} vs router whitelist={set(ROUTER_WHITELIST)!r}"
        )
        assert seeded_emails == set(SERVICE_WHITELIST), (
            f"Whitelist drift: seeder={seeded_emails!r} vs service whitelist={set(SERVICE_WHITELIST)!r}"
        )

    async def test_manual_login_form_accepts_demo_email_any_password(
        self,
        demo_client: AsyncClient,
    ) -> None:
        """BUG-D02 shortcut: ``POST /auth/login/`` with a demo email and
        ANY password mints tokens (when SEED_DEMO=true).

        Why this matters: BUG-D01 randomised demo passwords per install,
        but the documented credential is ``DemoPass1234!``. Users who
        typed the documented password into the manual login form got 401.
        The shortcut in ``UserService.login`` routes demo emails through
        ``demo_login`` so the documented credential JustWorks without
        reintroducing a hardcoded password into the seeder.
        """
        # The documented password — must still work.
        resp = await demo_client.post(
            "/api/v1/users/auth/login/",
            json={"email": "demo@openestimator.io", "password": "DemoPass1234!"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["access_token"]

        # ANY password works for a whitelisted demo email — the password
        # is intentionally ignored on the demo path.
        resp = await demo_client.post(
            "/api/v1/users/auth/login/",
            json={"email": "demo@openestimator.io", "password": "wrong-on-purpose"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["access_token"]

        # Non-demo email still requires a correct password — the shortcut
        # is scoped strictly to the whitelist and does not weaken regular
        # auth.
        resp = await demo_client.post(
            "/api/v1/users/auth/login/",
            json={"email": "nobody@example.com", "password": "anything"},
        )
        assert resp.status_code == 401, resp.text

    async def test_manual_login_demo_email_blocked_when_seed_demo_off(
        self,
        demo_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """BUG-D02 shortcut must be gated on SEED_DEMO=true.

        On production installs (SEED_DEMO=false) the manual login form
        must NOT accept whitelisted demo emails with arbitrary passwords
        — that would be a security hole. The shortcut must defer to the
        normal password-verify path.
        """
        monkeypatch.setenv("SEED_DEMO", "false")
        try:
            resp = await demo_client.post(
                "/api/v1/users/auth/login/",
                json={
                    "email": "demo@openestimator.io",
                    "password": "wrong-on-purpose",
                },
            )
            # The user row may still exist from earlier tests but the
            # password is the seeded one (not "wrong-on-purpose") so we
            # expect a real 401 from the bcrypt verify path.
            assert resp.status_code == 401, resp.text
        finally:
            monkeypatch.setenv("SEED_DEMO", "true")
