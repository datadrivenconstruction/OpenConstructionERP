"""Integration tests for the canonical -> 3D Tileset packaging endpoint.

POST /api/v1/geo-hub/from-canonical/{cad_import_id}

Validates the happy path (200 + persisted Tileset row + storage write),
the missing-anchor 422, the cross-tenant 404, and the missing-import
404.

Scaffolding mirrors test_geo_hub_api.py — per-module temp SQLite
registered BEFORE any ``from app...`` import.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-geo-hub-canonical-"))
_TMP_DB = _TMP_DIR / "geo_hub_canonical.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.bim_hub import models as _bim_models  # noqa: F401
        from app.modules.geo_hub import models as _geo_models  # noqa: F401
        from app.modules.property_dev import models as _prop_models  # noqa: F401

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
    email = f"{label}-{uuid.uuid4().hex[:8]}@geo-canon.io"
    password = f"GeoCan{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": label},
    )
    assert reg.status_code in (200, 201), reg.text
    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
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
        json={"name": f"Canon-A {uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    return {"headers": headers, "project_id": proj.json()["id"]}


@pytest_asyncio.fixture(scope="module")
async def tenant_b(http_client):
    email, password = await _register(http_client, "tenant-b")
    await _set_role(email, "editor")
    headers = await _login(http_client, email, password)
    proj = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"Canon-B {uuid.uuid4().hex[:6]}", "currency": "USD"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    return {"headers": headers, "project_id": proj.json()["id"]}


# ── Helpers ────────────────────────────────────────────────────────────────


async def _create_bim_model_with_elements(
    project_id: str,
    *,
    with_elements: bool = True,
) -> uuid.UUID:
    """Insert a BIMModel + a few canonical-shaped BIMElement rows."""
    from app.database import async_session_factory
    from app.modules.bim_hub.models import BIMElement, BIMModel

    async with async_session_factory() as s:
        model = BIMModel(
            project_id=uuid.UUID(project_id),
            name="Canonical Test Model",
            model_format="ifc",
            version="1",
            status="ready",
            element_count=3 if with_elements else 0,
        )
        s.add(model)
        await s.flush()
        if with_elements:
            for i in range(3):
                s.add(
                    BIMElement(
                        model_id=model.id,
                        stable_id=f"elem-{i:03d}",
                        element_type="wall" if i % 2 == 0 else "slab",
                        properties={"din276": "330" if i % 2 == 0 else "350"},
                        quantities={
                            "area_m2": 12.5,
                            "volume_m3": 3.0,
                            "length_m": 5.0,
                            "height_m": 3.0,
                        },
                        bounding_box={
                            "min": [i * 5.0, 0.0, 0.0],
                            "max": [i * 5.0 + 4.5, 0.3, 3.0],
                        },
                    )
                )
        await s.commit()
        return model.id


async def _create_anchor(client: AsyncClient, tenant: dict) -> None:
    res = await client.post(
        "/api/v1/geo-hub/anchors/",
        json={
            "project_id": tenant["project_id"],
            "lat": "52.5200",
            "lon": "13.4050",
            "alt": "34.0",
            "epsg_code": 4326,
        },
        headers=tenant["headers"],
    )
    assert res.status_code == 201, res.text


# ── Tests ──────────────────────────────────────────────────────────────────


class TestFromCanonical:
    @pytest.mark.asyncio
    async def test_happy_path_returns_200_and_persists_tileset(
        self,
        http_client,
        tenant_a,
    ):
        await _create_anchor(http_client, tenant_a)
        model_id = await _create_bim_model_with_elements(tenant_a["project_id"])

        res = await http_client.post(
            f"/api/v1/geo-hub/from-canonical/{model_id}",
            json={"heading_deg": 0, "name": "Berlin Tower", "tags": ["bim"]},
            headers=tenant_a["headers"],
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["source_kind"] == "bim_model"
        assert body["source_id"] == str(model_id)
        assert body["status"] == "ready"
        assert body["tile_count"] == 1
        assert body["total_bytes"] > 0
        assert body["tileset_json_uri"]
        assert body["bounding_volume"] is not None
        assert "region" in body["bounding_volume"]
        meta = body.get("metadata") or body.get("metadata_") or {}
        assert meta.get("cad_import_id") == str(model_id)
        assert meta.get("feature_count") == 3
        assert meta.get("tags") == ["bim"]

        # The row must be visible in the project's tileset list.
        listed = await http_client.get(
            f"/api/v1/geo-hub/tilesets/?project_id={tenant_a['project_id']}",
            headers=tenant_a["headers"],
        )
        assert listed.status_code == 200
        assert any(t["id"] == body["id"] for t in listed.json())

    @pytest.mark.asyncio
    async def test_missing_anchor_returns_422(self, http_client, tenant_b):
        # tenant_b has a project but NO anchor.
        model_id = await _create_bim_model_with_elements(
            tenant_b["project_id"],
        )
        res = await http_client.post(
            f"/api/v1/geo-hub/from-canonical/{model_id}",
            json={},
            headers=tenant_b["headers"],
        )
        assert res.status_code == 422, res.text
        assert res.json()["detail"] == "no_anchor_for_project"

    @pytest.mark.asyncio
    async def test_cross_tenant_returns_404(
        self,
        http_client,
        tenant_a,
        tenant_b,
    ):
        # Anchor + model belong to tenant_a; tenant_b must see 404.
        model_id = await _create_bim_model_with_elements(
            tenant_a["project_id"],
        )
        res = await http_client.post(
            f"/api/v1/geo-hub/from-canonical/{model_id}",
            json={},
            headers=tenant_b["headers"],
        )
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_unknown_cad_import_returns_404(
        self,
        http_client,
        tenant_a,
    ):
        fake_id = uuid.uuid4()
        res = await http_client.post(
            f"/api/v1/geo-hub/from-canonical/{fake_id}",
            json={},
            headers=tenant_a["headers"],
        )
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_heading_rotates_without_error(self, http_client, tenant_a):
        # Heading rotation path is exercised — output must still pack.
        model_id = await _create_bim_model_with_elements(
            tenant_a["project_id"],
        )
        res = await http_client.post(
            f"/api/v1/geo-hub/from-canonical/{model_id}",
            json={"heading_deg": 45.0},
            headers=tenant_a["headers"],
        )
        assert res.status_code == 200, res.text
        body = res.json()
        meta = body.get("metadata") or body.get("metadata_") or {}
        assert meta.get("heading_deg") == 45.0

    @pytest.mark.asyncio
    async def test_elements_with_no_geometry_returns_422(
        self,
        http_client,
        tenant_a,
    ):
        """An import whose elements all lack usable bounding boxes must
        fail loudly with 422 instead of persisting a degenerate tileset.

        A degenerate tileset (region collapsed to the anchor point,
        feature_count=0) would render invisibly in Cesium and would
        poison the reuse short-circuit on the next generate call.
        """
        from app.database import async_session_factory
        from app.modules.bim_hub.models import BIMElement, BIMModel

        await _create_anchor(http_client, tenant_a)
        async with async_session_factory() as s:
            model = BIMModel(
                project_id=uuid.UUID(tenant_a["project_id"]),
                name="No-geometry Model",
                model_format="ifc",
                version="1",
                status="ready",
                element_count=2,
            )
            s.add(model)
            await s.flush()
            for i in range(2):
                # Elements with no bbox, no extrusion, no area/volume —
                # _element_geometry_aabb returns None for each.
                s.add(
                    BIMElement(
                        model_id=model.id,
                        stable_id=f"empty-{i:03d}",
                        element_type="annotation",
                        properties={},
                        quantities={},
                        bounding_box={},
                    )
                )
            await s.commit()
            model_id = model.id

        res = await http_client.post(
            f"/api/v1/geo-hub/from-canonical/{model_id}",
            json={},
            headers=tenant_a["headers"],
        )
        assert res.status_code == 422, res.text
        assert res.json()["detail"] == "canonical_elements_have_no_geometry"
