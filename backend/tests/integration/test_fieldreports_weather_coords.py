"""Coordinate-validation tests for ``GET /api/v1/fieldreports/weather/``.

The endpoint accepts ``lat`` / ``lon`` query params and forwards them
to OpenWeatherMap. Pre-fix the params were declared as unbounded
``float = Query(...)``, so a caller could send:

* lat / lon well outside WGS-84 (``lat=999``, ``lon=-500``) — the
  upstream provider would 400 but the request still hit the network;
* the literal strings ``nan`` / ``inf`` — FastAPI happily coerces
  these to float, and ``-90 <= nan <= 90`` evaluates to False but
  no error is raised on the way to ``params=`` in ``httpx`` — so a
  malformed URL would be emitted upstream.

The fix adds ``ge`` / ``le`` bounds plus an explicit ``math.isfinite``
check before any upstream call. These tests live as integration so
they exercise the actual FastAPI route validator.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-fr-weather-"))
_TMP_DB = _TMP_DIR / "fr_weather.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


@pytest_asyncio.fixture(scope="module")
async def app_instance():
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
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _auth_headers(client: AsyncClient) -> dict[str, str]:
    """Register + login a viewer — weather only needs an auth gate."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"weather-{uuid.uuid4().hex[:8]}@fieldreports-weather.io"
    password = f"WeatherCoords{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "weather"},
    )
    assert reg.status_code in (200, 201), reg.text

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True))
        await s.commit()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def headers(http_client):
    return await _auth_headers(http_client)


# ── Rejection cases — must 422 before any upstream call ────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        (91.0, 0.0),  # lat above 90
        (-90.5, 0.0),  # lat below -90
        (0.0, 181.0),  # lon above 180
        (0.0, -181.0),  # lon below -180
        (1e9, 0.0),  # absurdly large lat
        (0.0, -1e9),  # absurdly negative lon
    ],
)
async def test_out_of_range_coordinates_rejected(http_client, headers, lat, lon):
    resp = await http_client.get(
        f"/api/v1/fieldreports/weather/?lat={lat}&lon={lon}",
        headers=headers,
    )
    assert resp.status_code == 422, (
        f"out-of-range coords accepted: lat={lat} lon={lon} -> {resp.status_code} {resp.text!r}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        ("nan", "0.0"),
        ("0.0", "nan"),
        ("inf", "0.0"),
        ("0.0", "-inf"),
    ],
)
async def test_non_finite_coordinates_rejected(http_client, headers, lat, lon):
    resp = await http_client.get(
        f"/api/v1/fieldreports/weather/?lat={lat}&lon={lon}",
        headers=headers,
    )
    assert resp.status_code == 422, (
        f"non-finite coords accepted: lat={lat} lon={lon} -> {resp.status_code} {resp.text!r}"
    )


# ── Happy-path: valid coords pass validation (upstream may 503 without key)


@pytest.mark.asyncio
async def test_valid_coordinates_pass_validation(http_client, headers):
    """A well-formed coord pair gets past the validator.

    The fixture suite doesn't set ``OPENWEATHERMAP_API_KEY`` so the
    upstream provider call short-circuits to a 503 — that's the
    expected legacy shape and proves the validator let the request
    through.
    """
    resp = await http_client.get(
        "/api/v1/fieldreports/weather/?lat=52.5&lon=13.4",
        headers=headers,
    )
    # 200 if a key is set in the runner env, 503 if not. Either is
    # post-validation: a 422 would mean we wrongly rejected good coords.
    assert resp.status_code in (200, 503), resp.text
    body = resp.json()
    assert "available" in body
