"""Integration tests for the per-user tour-state API.

Mirrors the dashboard-rollup test suite (per-module SQLite isolation +
single app boot per module) so the test runs fast and is independent
of any other test's state. Per ``feedback_test_isolation.md`` we
redirect ``DATABASE_URL`` to a per-module temp SQLite file BEFORE the
app is first imported.

* ``GET  /api/v1/users/me/tour-state/`` — empty defaults when the user
  has never run a tour.
* ``PUT  /api/v1/users/me/tour-state/`` — upserts the bucket; a
  subsequent GET must return what was just written.
* Per-user IDOR isolation — user A writing must NOT show up under user
  B's account.
* Unknown / non-canonical tour ids are silently dropped at the server
  boundary.

Run:
    pytest backend/tests/modules/users/test_tour_state.py -v
or, for a quick filter:
    pytest backend/tests/modules/users/ -k tour_state -v
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-tourstate-"))
_TMP_DB = _TMP_DIR / "tourstate.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
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


async def _force_activate_and_set_role(email: str, role: str = "admin") -> None:
    """Force the test user to ``is_active=True`` + the chosen role.

    Some registration modes (anything other than ``open``) mark new
    accounts as dormant — the first user is admin/active by bootstrap,
    every subsequent one is inactive and a follow-up login returns 401.
    We bypass that for tests by writing the row directly. Mirrors the
    helper in ``test_dashboard_rollup.py``.
    """
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await session.commit()


async def _register_and_login(
    client: AsyncClient,
    *,
    email: str | None = None,
    password: str = "TourState1234",
) -> tuple[str, dict[str, str]]:
    """Register a fresh user and return (email, auth_headers)."""
    if email is None:
        email = f"tourstate-{uuid.uuid4().hex[:8]}@prefs.io"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Tour State Tester",
        },
    )
    assert reg.status_code in (200, 201), reg.text
    await _force_activate_and_set_role(email, "admin")
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json().get("access_token", "")
    assert token, resp.text
    return email, {"Authorization": f"Bearer {token}"}


# ── GET on fresh user ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_tour_state_empty_for_new_user(client):
    """A user who has never persisted a tour gets ``{"tours": {}}``, not 404."""
    _email, headers = await _register_and_login(client)

    resp = await client.get("/api/v1/users/me/tour-state/", headers=headers)

    assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text!r}"
    body = resp.json()
    assert body == {"tours": {}}


# ── PUT then GET round-trip ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_then_get_tour_state_round_trip(client):
    """A PUT followed by a GET returns the exact same payload."""
    _email, headers = await _register_and_login(client)

    payload = {
        "tours": {
            "dashboard": {
                "dismissed_at": "2026-05-24T10:00:00+00:00",
                "completed_at": None,
            },
            "boq": {
                "dismissed_at": "2026-05-24T11:00:00+00:00",
                "completed_at": "2026-05-24T11:30:00+00:00",
            },
        },
    }
    put_resp = await client.put(
        "/api/v1/users/me/tour-state/",
        headers=headers,
        json=payload,
    )
    assert put_resp.status_code == 200, put_resp.text
    assert put_resp.json() == payload

    get_resp = await client.get("/api/v1/users/me/tour-state/", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json() == payload


@pytest.mark.asyncio
async def test_put_overwrites_previous_value(client):
    """A second PUT fully replaces the first payload (not merge / append)."""
    _email, headers = await _register_and_login(client)

    await client.put(
        "/api/v1/users/me/tour-state/",
        headers=headers,
        json={
            "tours": {
                "dashboard": {
                    "dismissed_at": "2026-05-24T10:00:00+00:00",
                    "completed_at": None,
                },
                "boq": {
                    "dismissed_at": None,
                    "completed_at": "2026-05-24T11:30:00+00:00",
                },
            },
        },
    )
    await client.put(
        "/api/v1/users/me/tour-state/",
        headers=headers,
        json={
            "tours": {
                "bim": {
                    "dismissed_at": "2026-05-24T12:00:00+00:00",
                    "completed_at": None,
                },
            },
        },
    )

    resp = await client.get("/api/v1/users/me/tour-state/", headers=headers)
    body = resp.json()
    assert "dashboard" not in body["tours"]
    assert "boq" not in body["tours"]
    assert body["tours"]["bim"]["dismissed_at"] == "2026-05-24T12:00:00+00:00"


# ── Per-user isolation (IDOR posture) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_user_a_write_does_not_affect_user_b(client):
    """User A's tour-state stays with A — the IDOR check the spec calls out.

    The endpoint reads ``CurrentUserId`` for both the lookup and the write,
    so there's no way for a payload to spoof another user's bucket. This
    test pins the behaviour: user A writes, user B's GET returns empty.
    """
    _email_a, headers_a = await _register_and_login(client)
    _email_b, headers_b = await _register_and_login(client)

    await client.put(
        "/api/v1/users/me/tour-state/",
        headers=headers_a,
        json={
            "tours": {
                "dashboard": {
                    "dismissed_at": "2026-05-24T10:00:00+00:00",
                    "completed_at": None,
                },
            },
        },
    )

    resp_b = await client.get("/api/v1/users/me/tour-state/", headers=headers_b)
    assert resp_b.status_code == 200
    assert resp_b.json() == {"tours": {}}

    resp_a = await client.get("/api/v1/users/me/tour-state/", headers=headers_a)
    body_a = resp_a.json()
    assert body_a["tours"]["dashboard"]["dismissed_at"] == ("2026-05-24T10:00:00+00:00")


# ── Unknown tour ids dropped ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_drops_unknown_tour_ids(client):
    """A tour id outside the canonical set is dropped at the server."""
    _email, headers = await _register_and_login(client)

    resp = await client.put(
        "/api/v1/users/me/tour-state/",
        headers=headers,
        json={
            "tours": {
                "boq": {
                    "dismissed_at": "2026-05-24T10:00:00+00:00",
                    "completed_at": None,
                },
                # Garbage tour id — must not show up in the response.
                "imaginary-tour-id": {
                    "dismissed_at": "2026-05-24T10:00:00+00:00",
                    "completed_at": None,
                },
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "boq" in body["tours"]
    assert "imaginary-tour-id" not in body["tours"]


# ── Auth required ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_endpoints_require_authentication(client):
    """Both endpoints must reject anonymous callers."""
    get_resp = await client.get("/api/v1/users/me/tour-state/")
    assert get_resp.status_code in (401, 403)

    put_resp = await client.put(
        "/api/v1/users/me/tour-state/",
        json={
            "tours": {
                "dashboard": {
                    "dismissed_at": "2026-05-24T10:00:00+00:00",
                    "completed_at": None,
                },
            },
        },
    )
    assert put_resp.status_code in (401, 403)
