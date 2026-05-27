"""Geo Hub cross-module pin layers — HSE incidents, Punchlist items,
Daily Diary photos.

Mirrors ``test_geo_hub_api.py`` scaffolding: per-module temp SQLite
registered BEFORE any ``from app...`` import. Verifies:

* Pins land on the layer endpoint when the source row has WGS84
  coordinates.
* Rows without coordinates are excluded (so a "no pin" row never
  bleeds into the map).
* Cross-tenant access returns 404 (IDOR via ``_verify_project_owner``).
* Anonymous access returns 401/403 (RBAC).
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-geo-hub-pins-"))
_TMP_DB = _TMP_DIR / "geo_hub_pins.db"
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
        from app.modules.daily_diary import models as _diary_models  # noqa: F401
        from app.modules.geo_hub import models as _geo_models  # noqa: F401
        from app.modules.punchlist import models as _punch_models  # noqa: F401
        from app.modules.safety import models as _safety_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _set_role(email: str, role: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


async def _register(client: AsyncClient, label: str) -> tuple[str, str]:
    email = f"{label}-{uuid.uuid4().hex[:8]}@geo-pins.io"
    password = f"GeoPins{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": label},
    )
    assert reg.status_code in (200, 201), reg.text
    return email, password


async def _login(
    client: AsyncClient,
    email: str,
    password: str,
) -> dict[str, str]:
    res = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def tenant_a(http_client):
    email, password = await _register(http_client, "tenant-a")
    await _set_role(email, "admin")
    headers = await _login(http_client, email, password)

    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"GeoPins-A {uuid.uuid4().hex[:6]}",
            "description": "owner: tenant A",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    return {
        "email": email,
        "headers": headers,
        "project_id": proj.json()["id"],
    }


@pytest_asyncio.fixture(scope="module")
async def tenant_b(http_client):
    """Tenant B: editor (NOT admin) — so IDOR tests don't bypass via admin."""
    email, password = await _register(http_client, "tenant-b")
    await _set_role(email, "editor")
    headers = await _login(http_client, email, password)

    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"GeoPins-B {uuid.uuid4().hex[:6]}",
            "description": "owner: tenant B",
            "currency": "USD",
        },
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    return {
        "email": email,
        "headers": headers,
        "project_id": proj.json()["id"],
    }


# ── HSE pin layer ───────────────────────────────────────────────────────


class TestHSEPins:
    @pytest.mark.asyncio
    async def test_hse_pin_round_trip(self, http_client, tenant_a):
        # Create one geo-pinned incident, one un-pinned.
        pinned = await http_client.post(
            "/api/v1/safety/incidents/",
            json={
                "project_id": tenant_a["project_id"],
                "title": "Slip near scaffold",
                "incident_date": "2026-05-01",
                "incident_type": "injury",
                "severity": "moderate",
                "description": "Worker slipped on wet decking.",
                "geo_lat": 52.5200,
                "geo_lon": 13.4050,
            },
            headers=tenant_a["headers"],
        )
        assert pinned.status_code == 201, pinned.text
        body = pinned.json()
        assert body["geo_lat"] == 52.52
        assert body["geo_lon"] == 13.405

        unpinned = await http_client.post(
            "/api/v1/safety/incidents/",
            json={
                "project_id": tenant_a["project_id"],
                "title": "Paperwork-only near miss",
                "incident_date": "2026-05-02",
                "incident_type": "near_miss",
                "severity": "minor",
                "description": "No location pin attached.",
            },
            headers=tenant_a["headers"],
        )
        assert unpinned.status_code == 201, unpinned.text

        # Layer endpoint should only return the geo-tagged incident.
        layer = await http_client.get(
            f"/api/v1/geo-hub/projects/{tenant_a['project_id']}/hse-pins",
            headers=tenant_a["headers"],
        )
        assert layer.status_code == 200, layer.text
        pins = layer.json()
        assert isinstance(pins, list)
        assert len(pins) == 1
        pin = pins[0]
        assert pin["lat"] == 52.52
        assert pin["lon"] == 13.405
        assert pin["incident_type"] == "injury"
        assert pin["severity"] == "moderate"
        assert pin["status"] == "reported"

    @pytest.mark.asyncio
    async def test_hse_pin_cross_tenant_returns_404(
        self,
        http_client,
        tenant_a,
        tenant_b,
    ):
        res = await http_client.get(
            f"/api/v1/geo-hub/projects/{tenant_a['project_id']}/hse-pins",
            headers=tenant_b["headers"],
        )
        assert res.status_code == 404, res.text

    @pytest.mark.asyncio
    async def test_hse_pin_unauthenticated_returns_401(self, http_client):
        res = await http_client.get(
            f"/api/v1/geo-hub/projects/{uuid.uuid4()}/hse-pins",
        )
        assert res.status_code in (401, 403)


# ── Punchlist pin layer ──────────────────────────────────────────────────


class TestPunchlistPins:
    @pytest.mark.asyncio
    async def test_punchlist_pin_round_trip(self, http_client, tenant_a):
        pinned = await http_client.post(
            "/api/v1/punchlist/items/",
            json={
                "project_id": tenant_a["project_id"],
                "title": "Cracked floor tile",
                "priority": "high",
                "category": "finishing",
                "geo_lat": 48.1351,
                "geo_lon": 11.5820,
            },
            headers=tenant_a["headers"],
        )
        assert pinned.status_code == 201, pinned.text
        body = pinned.json()
        assert body["geo_lat"] == 48.1351
        assert body["geo_lon"] == 11.582

        unpinned = await http_client.post(
            "/api/v1/punchlist/items/",
            json={
                "project_id": tenant_a["project_id"],
                "title": "Sheet-pinned but no map pin",
                "priority": "low",
            },
            headers=tenant_a["headers"],
        )
        assert unpinned.status_code == 201, unpinned.text

        layer = await http_client.get(
            f"/api/v1/geo-hub/projects/{tenant_a['project_id']}/punchlist-pins",
            headers=tenant_a["headers"],
        )
        assert layer.status_code == 200, layer.text
        pins = layer.json()
        assert len(pins) == 1
        pin = pins[0]
        assert pin["lat"] == 48.1351
        assert pin["lon"] == 11.582
        assert pin["priority"] == "high"
        assert pin["category"] == "finishing"
        assert pin["status"] == "open"

    @pytest.mark.asyncio
    async def test_punchlist_pin_cross_tenant_returns_404(
        self,
        http_client,
        tenant_a,
        tenant_b,
    ):
        res = await http_client.get(
            f"/api/v1/geo-hub/projects/{tenant_a['project_id']}/punchlist-pins",
            headers=tenant_b["headers"],
        )
        assert res.status_code == 404, res.text


# ── Daily Diary photo pin layer ─────────────────────────────────────────


class TestDiaryPhotoPins:
    @pytest.mark.asyncio
    async def test_diary_photo_pin_round_trip(self, http_client, tenant_a):
        # Daily Diary photos have lat/lng already — exercise via direct DB
        # write because the upload endpoint requires real binary content
        # and we just want to verify the Geo Hub projection.
        from sqlalchemy import insert

        from app.database import async_session_factory
        from app.modules.daily_diary.models import DiaryPhoto

        now = datetime.now(UTC)

        async with async_session_factory() as s:
            await s.execute(
                insert(DiaryPhoto).values(
                    project_id=uuid.UUID(tenant_a["project_id"]),
                    taken_at=now,
                    lat=40.7128,
                    lng=-74.0060,
                    file_url="https://example.test/photo-geo.jpg",
                    mime_type="image/jpeg",
                    file_size_bytes=12345,
                )
            )
            await s.execute(
                insert(DiaryPhoto).values(
                    project_id=uuid.UUID(tenant_a["project_id"]),
                    taken_at=now,
                    lat=None,
                    lng=None,
                    file_url="https://example.test/photo-nopin.jpg",
                    mime_type="image/jpeg",
                    file_size_bytes=12345,
                )
            )
            # Archived photo with geo — must NOT show up.
            await s.execute(
                insert(DiaryPhoto).values(
                    project_id=uuid.UUID(tenant_a["project_id"]),
                    taken_at=now,
                    lat=40.0,
                    lng=-74.0,
                    file_url="https://example.test/photo-archived.jpg",
                    mime_type="image/jpeg",
                    file_size_bytes=12345,
                    is_archived=True,
                )
            )
            await s.commit()

        layer = await http_client.get(
            f"/api/v1/geo-hub/projects/{tenant_a['project_id']}/diary-photo-pins",
            headers=tenant_a["headers"],
        )
        assert layer.status_code == 200, layer.text
        pins = layer.json()
        assert len(pins) == 1
        pin = pins[0]
        assert pin["lat"] == 40.7128
        assert pin["lon"] == -74.006
        assert pin["file_url"].endswith("photo-geo.jpg")

    @pytest.mark.asyncio
    async def test_diary_photo_pin_cross_tenant_returns_404(
        self,
        http_client,
        tenant_a,
        tenant_b,
    ):
        res = await http_client.get(
            f"/api/v1/geo-hub/projects/{tenant_a['project_id']}/diary-photo-pins",
            headers=tenant_b["headers"],
        )
        assert res.status_code == 404, res.text
