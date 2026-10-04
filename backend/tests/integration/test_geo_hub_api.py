"""Geo Hub integration suite — anchors, tilesets, imagery, terrain,
viewpoints, overlays, GeoJSON / KML I/O, tile-generation jobs, and
the map-config bundle.

Runs against the PostgreSQL cluster provisioned by ``conftest.py``; the
SQLAlchemy engine is already bound before this module is imported.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
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


async def _register(client: AsyncClient, label: str) -> tuple[str, dict[str, str]]:
    email = f"{label}-{uuid.uuid4().hex[:8]}@geo-hub.io"
    password = f"GeoHub{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"{label}"},
    )
    assert reg.status_code in (200, 201), reg.text
    return email, {"_password": password}


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
    email, meta = await _register(http_client, "tenant-a")
    await _set_role(email, "admin")
    headers = await _login(http_client, email, meta["_password"])

    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Geo-A {uuid.uuid4().hex[:6]}",
            "description": "owner: tenant A",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]
    return {
        "email": email,
        "headers": headers,
        "project_id": project_id,
    }


@pytest_asyncio.fixture(scope="module")
async def tenant_b(http_client):
    """Tenant B: editor (NOT admin) — so IDOR tests don't bypass via admin."""
    email, meta = await _register(http_client, "tenant-b")
    await _set_role(email, "editor")
    headers = await _login(http_client, email, meta["_password"])

    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Geo-B {uuid.uuid4().hex[:6]}",
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


async def _ensure_anchor(client: AsyncClient, tenant: dict[str, str]) -> dict:
    """Anchor the tenant's project and return the anchor.

    A test that needs the anchor makes it here instead of relying on
    ``TestAnchors`` having run first. The full suite is split across shards
    by test count with no regard for files, so a shard can open this module
    in the middle, and ``-k`` filters deselect siblings the same way. The
    POST is an upsert under the one-anchor-per-project constraint, so calling
    it again is harmless.
    """
    res = await client.post(
        "/api/v1/geo-hub/anchors/",
        json={
            "project_id": tenant["project_id"],
            "lat": "52.5200",
            "lon": "13.4050",
            "alt": "34.0",
            "epsg_code": 4326,
            "region_code": "DE-BE",
            "address": "Alexanderplatz, Berlin",
        },
        headers=tenant["headers"],
    )
    assert res.status_code in (200, 201), res.text
    return res.json()


# ── Anchors (8 tests) ───────────────────────────────────────────────────


class TestAnchors:
    @pytest.mark.asyncio
    async def test_anchor_create_get(self, http_client, tenant_a):
        res = await http_client.post(
            "/api/v1/geo-hub/anchors/",
            json={
                "project_id": tenant_a["project_id"],
                "lat": "52.5200",
                "lon": "13.4050",
                "alt": "34.0",
                "epsg_code": 4326,
                "region_code": "DE-BE",
                "address": "Alexanderplatz, Berlin",
            },
            headers=tenant_a["headers"],
        )
        assert res.status_code == 201, res.text
        anchor = res.json()
        # Pydantic Decimal serialisation trims trailing zeros.
        assert Decimal(anchor["lat"]) == Decimal("52.52")
        assert anchor["region_code"] == "DE-BE"

        # List for the project.
        listed = await http_client.get(
            f"/api/v1/geo-hub/anchors/?project_id={tenant_a['project_id']}",
            headers=tenant_a["headers"],
        )
        assert listed.status_code == 200
        assert len(listed.json()) == 1

    @pytest.mark.asyncio
    async def test_anchor_create_is_idempotent(self, http_client, tenant_a):
        # POST again with a new lat — the unique-per-project constraint
        # means the service updates in place rather than 409-ing.
        res = await http_client.post(
            "/api/v1/geo-hub/anchors/",
            json={
                "project_id": tenant_a["project_id"],
                "lat": "48.1351",
                "lon": "11.5820",
                "alt": "519.0",
                "epsg_code": 4326,
                "region_code": "DE-BY",
            },
            headers=tenant_a["headers"],
        )
        assert res.status_code == 201, res.text
        anchor = res.json()
        assert Decimal(anchor["lat"]) == Decimal("48.1351")

    @pytest.mark.asyncio
    async def test_anchor_lat_lon_bounds_enforced(
        self,
        http_client,
        tenant_a,
    ):
        res = await http_client.post(
            "/api/v1/geo-hub/anchors/",
            json={
                "project_id": tenant_a["project_id"],
                "lat": "120.0",  # invalid
                "lon": "0.0",
            },
            headers=tenant_a["headers"],
        )
        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_anchor_patch(self, http_client, tenant_a):
        anchor_id = (await _ensure_anchor(http_client, tenant_a))["id"]
        res = await http_client.patch(
            f"/api/v1/geo-hub/anchors/{anchor_id}",
            json={"address": "Marienplatz, Munich", "accuracy_m": "1.5"},
            headers=tenant_a["headers"],
        )
        assert res.status_code == 200, res.text
        assert res.json()["address"] == "Marienplatz, Munich"

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_anchor_idor_cross_tenant_returns_404(
        self,
        http_client,
        tenant_a,
        tenant_b,
    ):
        anchor_id = (await _ensure_anchor(http_client, tenant_a))["id"]
        # tenant_b tries to mutate tenant_a's project anchor — must 404.
        res = await http_client.patch(
            f"/api/v1/geo-hub/anchors/{anchor_id}",
            json={"address": "ATTACKER WAS HERE"},
            headers=tenant_b["headers"],
        )
        assert res.status_code == 404

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_anchor_idor_cross_tenant_get_returns_404(
        self,
        http_client,
        tenant_a,
        tenant_b,
    ):
        anchor_id = (await _ensure_anchor(http_client, tenant_a))["id"]
        res = await http_client.get(
            f"/api/v1/geo-hub/anchors/{anchor_id}",
            headers=tenant_b["headers"],
        )
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_anchor_unauthenticated_returns_401(self, http_client):
        res = await http_client.get("/api/v1/geo-hub/anchors/?project_id=00000000-0000-0000-0000-000000000000")
        assert res.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_anchor_invalid_region_code_rejected(
        self,
        http_client,
        tenant_a,
    ):
        res = await http_client.post(
            "/api/v1/geo-hub/anchors/",
            json={
                "project_id": tenant_a["project_id"],
                "lat": "0",
                "lon": "0",
                "region_code": "de-be",  # lowercase, fails the pattern
            },
            headers=tenant_a["headers"],
        )
        assert res.status_code == 422


# ── Tilesets + jobs (10 tests) ──────────────────────────────────────────


class TestTilesets:
    @pytest.mark.asyncio
    async def test_create_tileset(self, http_client, tenant_a):
        source_id = str(uuid.uuid4())
        res = await http_client.post(
            "/api/v1/geo-hub/tilesets/",
            json={
                "project_id": tenant_a["project_id"],
                "source_kind": "bim_model",
                "source_id": source_id,
                "name": "Wohnpark Berlin",
                "status": "draft",
            },
            headers=tenant_a["headers"],
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["source_kind"] == "bim_model"
        assert body["status"] == "draft"

    @pytest.mark.asyncio
    async def test_list_tilesets(self, http_client, tenant_a):
        res = await http_client.get(
            f"/api/v1/geo-hub/tilesets/?project_id={tenant_a['project_id']}",
            headers=tenant_a["headers"],
        )
        assert res.status_code == 200
        assert isinstance(res.json(), list)

    @pytest.mark.asyncio
    async def test_tileset_status_fsm_enforced(self, http_client, tenant_a):
        # Create draft -> patch to "ready" must fail (must go via
        # "generating" first).
        source_id = str(uuid.uuid4())
        res = await http_client.post(
            "/api/v1/geo-hub/tilesets/",
            json={
                "project_id": tenant_a["project_id"],
                "source_kind": "bim_model",
                "source_id": source_id,
                "status": "draft",
            },
            headers=tenant_a["headers"],
        )
        assert res.status_code == 201
        tileset_id = res.json()["id"]
        res2 = await http_client.patch(
            f"/api/v1/geo-hub/tilesets/{tileset_id}",
            json={"status": "ready"},
            headers=tenant_a["headers"],
        )
        assert res2.status_code == 409

    @pytest.mark.asyncio
    async def test_enqueue_tile_job_queues_and_pollable(
        self,
        http_client,
        tenant_a,
    ):
        source_id = str(uuid.uuid4())
        res = await http_client.post(
            "/api/v1/geo-hub/tilesets/generate/",
            json={
                "project_id": tenant_a["project_id"],
                "source_kind": "bim_model",
                "source_id": source_id,
            },
            headers=tenant_a["headers"],
        )
        assert res.status_code == 202, res.text
        job = res.json()
        assert job["state"] == "queued"
        assert job["progress_pct"] == 0

        # Poll.
        get_res = await http_client.get(
            f"/api/v1/geo-hub/jobs/{job['id']}",
            headers=tenant_a["headers"],
        )
        assert get_res.status_code == 200

    @pytest.mark.asyncio
    async def test_cancel_tile_job(self, http_client, tenant_a):
        source_id = str(uuid.uuid4())
        res = await http_client.post(
            "/api/v1/geo-hub/tilesets/generate/",
            json={
                "project_id": tenant_a["project_id"],
                "source_kind": "bim_model",
                "source_id": source_id,
            },
            headers=tenant_a["headers"],
        )
        job_id = res.json()["id"]
        cancel = await http_client.post(
            f"/api/v1/geo-hub/jobs/{job_id}/cancel",
            headers=tenant_a["headers"],
        )
        assert cancel.status_code == 200
        assert cancel.json()["state"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_completed_job_returns_409(
        self,
        http_client,
        tenant_a,
    ):
        # Existing-tileset short-circuit produces a completed job.
        # First create a "ready" tileset by going through the FSM.
        source_id = str(uuid.uuid4())
        ts = await http_client.post(
            "/api/v1/geo-hub/tilesets/",
            json={
                "project_id": tenant_a["project_id"],
                "source_kind": "bim_model",
                "source_id": source_id,
                "status": "draft",
            },
            headers=tenant_a["headers"],
        )
        tileset_id = ts.json()["id"]
        # draft -> generating -> ready.
        await http_client.patch(
            f"/api/v1/geo-hub/tilesets/{tileset_id}",
            json={"status": "generating"},
            headers=tenant_a["headers"],
        )
        await http_client.patch(
            f"/api/v1/geo-hub/tilesets/{tileset_id}",
            json={"status": "ready"},
            headers=tenant_a["headers"],
        )
        # Now enqueue — should produce a completed (reused) job.
        res = await http_client.post(
            "/api/v1/geo-hub/tilesets/generate/",
            json={
                "project_id": tenant_a["project_id"],
                "source_kind": "bim_model",
                "source_id": source_id,
            },
            headers=tenant_a["headers"],
        )
        job = res.json()
        assert job["state"] == "completed"
        # Cancelling a completed job is not a valid transition.
        cancel = await http_client.post(
            f"/api/v1/geo-hub/jobs/{job['id']}/cancel",
            headers=tenant_a["headers"],
        )
        assert cancel.status_code == 409

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_tile_job_idor(self, http_client, tenant_a, tenant_b):
        source_id = str(uuid.uuid4())
        res = await http_client.post(
            "/api/v1/geo-hub/tilesets/generate/",
            json={
                "project_id": tenant_a["project_id"],
                "source_kind": "bim_model",
                "source_id": source_id,
            },
            headers=tenant_a["headers"],
        )
        job_id = res.json()["id"]
        # tenant_b attempts to cancel.
        cancel = await http_client.post(
            f"/api/v1/geo-hub/jobs/{job_id}/cancel",
            headers=tenant_b["headers"],
        )
        assert cancel.status_code == 404

    @pytest.mark.asyncio
    async def test_list_jobs_filtered_by_state(self, http_client, tenant_a):
        res = await http_client.get(
            f"/api/v1/geo-hub/jobs/?project_id={tenant_a['project_id']}&state=queued",
            headers=tenant_a["headers"],
        )
        assert res.status_code == 200
        for job in res.json():
            assert job["state"] == "queued"

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_tileset_idor(self, http_client, tenant_a, tenant_b):
        ts = await http_client.post(
            "/api/v1/geo-hub/tilesets/",
            json={
                "project_id": tenant_a["project_id"],
                "source_kind": "bim_model",
                "source_id": str(uuid.uuid4()),
                "status": "draft",
            },
            headers=tenant_a["headers"],
        )
        tileset_id = ts.json()["id"]
        # tenant_b read attempt.
        res = await http_client.get(
            f"/api/v1/geo-hub/tilesets/{tileset_id}",
            headers=tenant_b["headers"],
        )
        assert res.status_code == 404

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_generate_for_other_tenants_project_404(
        self,
        http_client,
        tenant_a,
        tenant_b,
    ):
        res = await http_client.post(
            "/api/v1/geo-hub/tilesets/generate/",
            json={
                "project_id": tenant_a["project_id"],
                "source_kind": "bim_model",
                "source_id": str(uuid.uuid4()),
            },
            headers=tenant_b["headers"],
        )
        assert res.status_code == 404

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_generate_does_not_leak_other_tenants_tileset_uri(
        self,
        http_client,
        tenant_a,
        tenant_b,
    ):
        """Cross-tenant reuse leak: tenant A owns a ``ready`` tileset for
        ``source_id=X``; tenant B then enqueues a job against THEIR own
        project but with the same ``source_id``. Without project-scoping
        the reuse lookup, the service would happily return a completed
        job whose ``output_uri`` points at tenant A's storage prefix.
        """
        shared_source_id = str(uuid.uuid4())
        # Tenant A creates a tileset, walks it through the FSM to ``ready``.
        ts = await http_client.post(
            "/api/v1/geo-hub/tilesets/",
            json={
                "project_id": tenant_a["project_id"],
                "source_kind": "bim_model",
                "source_id": shared_source_id,
                "status": "draft",
                "tileset_json_uri": "minio://oe/tilesets/tenant-a-secret/tileset.json",
            },
            headers=tenant_a["headers"],
        )
        assert ts.status_code == 201, ts.text
        ts_id = ts.json()["id"]
        await http_client.patch(
            f"/api/v1/geo-hub/tilesets/{ts_id}",
            json={"status": "generating"},
            headers=tenant_a["headers"],
        )
        promote = await http_client.patch(
            f"/api/v1/geo-hub/tilesets/{ts_id}",
            json={"status": "ready"},
            headers=tenant_a["headers"],
        )
        assert promote.status_code == 200

        # Tenant B enqueues against their OWN project using A's source_id.
        res = await http_client.post(
            "/api/v1/geo-hub/tilesets/generate/",
            json={
                "project_id": tenant_b["project_id"],
                "source_kind": "bim_model",
                "source_id": shared_source_id,
            },
            headers=tenant_b["headers"],
        )
        # Must NOT short-circuit to tenant A's tileset. Either a queued
        # job for B's own project, or a brand-new tileset_id.
        assert res.status_code == 202, res.text
        job = res.json()
        # Critical: the reused tileset_id (if any) must belong to B, not A.
        assert job.get("tileset_id") != ts_id
        assert job.get("output_uri") != ("minio://oe/tilesets/tenant-a-secret/tileset.json")


# ── Imagery & Terrain (6 tests) ─────────────────────────────────────────


class TestImageryAndTerrain:
    @pytest.mark.asyncio
    async def test_create_imagery_layer(self, http_client, tenant_a):
        res = await http_client.post(
            "/api/v1/geo-hub/imagery-layers/",
            json={
                "project_id": tenant_a["project_id"],
                "name": "OpenStreetMap",
                "provider": "osm",
                "url_template": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                "attribution": "(c) OpenStreetMap contributors",
                "default_for_project": True,
            },
            headers=tenant_a["headers"],
        )
        assert res.status_code == 201, res.text
        assert res.json()["default_for_project"] is True

    @pytest.mark.asyncio
    async def test_only_one_default_imagery_per_project(
        self,
        http_client,
        tenant_a,
    ):
        # Add a second default — the first must be demoted.
        await http_client.post(
            "/api/v1/geo-hub/imagery-layers/",
            json={
                "project_id": tenant_a["project_id"],
                "name": "Bing Aerial",
                "provider": "bing",
                "url_template": "https://bing/...",
                "default_for_project": True,
            },
            headers=tenant_a["headers"],
        )
        layers = await http_client.get(
            f"/api/v1/geo-hub/imagery-layers/?project_id={tenant_a['project_id']}",
            headers=tenant_a["headers"],
        )
        defaults = [l for l in layers.json() if l["default_for_project"]]
        assert len(defaults) == 1

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_imagery_idor(self, http_client, tenant_a, tenant_b):
        # The sibling create test is deselected by the tenant-isolation -k
        # filter, so create the imagery layer here.
        created = await http_client.post(
            "/api/v1/geo-hub/imagery-layers/",
            json={
                "project_id": tenant_a["project_id"],
                "name": "OpenStreetMap",
                "provider": "osm",
                "url_template": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                "attribution": "(c) OpenStreetMap contributors",
                "default_for_project": True,
            },
            headers=tenant_a["headers"],
        )
        assert created.status_code in (200, 201), created.text
        layer_id = created.json()["id"]
        res = await http_client.patch(
            f"/api/v1/geo-hub/imagery-layers/{layer_id}",
            json={"name": "ATTACKER"},
            headers=tenant_b["headers"],
        )
        assert res.status_code == 404

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_terrain_source_admin_only(self, http_client, tenant_a, tenant_b):
        # tenant_a is admin, tenant_b is editor; creating a system
        # terrain source requires geo_hub.admin.
        res_a = await http_client.post(
            "/api/v1/geo-hub/terrain-sources/",
            json={
                "name": "Ellipsoid",
                "provider": "ellipsoid",
                "is_default": True,
            },
            headers=tenant_a["headers"],
        )
        assert res_a.status_code == 201, res_a.text

        res_b = await http_client.post(
            "/api/v1/geo-hub/terrain-sources/",
            json={
                "name": "WorldTerrain",
                "provider": "cesium_world",
                "endpoint": "https://api.cesium.com/v1/assets/1/endpoint",
            },
            headers=tenant_b["headers"],
        )
        assert res_b.status_code == 403

    @pytest.mark.asyncio
    async def test_terrain_source_token_never_returned(
        self,
        http_client,
        tenant_a,
    ):
        res = await http_client.post(
            "/api/v1/geo-hub/terrain-sources/",
            json={
                "name": "TestIon",
                "provider": "cesium_world",
                "endpoint": "https://api.cesium.com/v1/assets/1/endpoint",
                "ion_token": "secret-do-not-leak",
            },
            headers=tenant_a["headers"],
        )
        assert res.status_code == 201
        # The response must NOT include ion_token.
        assert "ion_token" not in res.json()

    @pytest.mark.asyncio
    async def test_list_terrain_sources(self, http_client, tenant_a):
        # Its own source rather than the one test_terrain_source_admin_only
        # creates: the suite's shards split this module by test count, so
        # that test may run in another process. Names are unique.
        name = f"Listed-{uuid.uuid4().hex[:8]}"
        created = await http_client.post(
            "/api/v1/geo-hub/terrain-sources/",
            json={"name": name, "provider": "ellipsoid"},
            headers=tenant_a["headers"],
        )
        assert created.status_code == 201, created.text
        res = await http_client.get(
            "/api/v1/geo-hub/terrain-sources/",
            headers=tenant_a["headers"],
        )
        assert res.status_code == 200
        names = [t["name"] for t in res.json()]
        assert name in names


# ── Overlays + GeoJSON/KML (6 tests) ───────────────────────────────────


_SAMPLE_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Site boundary</name>
      <description>Berlin Wohnpark site</description>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              13.405,52.520,0
              13.410,52.520,0
              13.410,52.525,0
              13.405,52.525,0
              13.405,52.520,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>Crane location</name>
      <Point>
        <coordinates>13.407,52.522,0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>
"""


_SAMPLE_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [13.40, 52.52],
                        [13.41, 52.52],
                        [13.41, 52.53],
                        [13.40, 52.53],
                        [13.40, 52.52],
                    ]
                ],
            },
            "properties": {"name": "Plot A"},
        },
    ],
}


class TestOverlays:
    @pytest.mark.asyncio
    async def test_import_geojson(self, http_client, tenant_a):
        res = await http_client.post(
            "/api/v1/geo-hub/overlays/import-geojson/",
            json={
                "project_id": tenant_a["project_id"],
                "name": "Site boundary",
                "kind": "boundary",
                "geojson": _SAMPLE_GEOJSON,
            },
            headers=tenant_a["headers"],
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["kind"] == "boundary"
        assert body["geojson"]["type"] == "FeatureCollection"

    @pytest.mark.asyncio
    async def test_import_kml(self, http_client, tenant_a):
        res = await http_client.post(
            "/api/v1/geo-hub/overlays/import-kml/",
            json={
                "project_id": tenant_a["project_id"],
                "name": "KML boundary",
                "kind": "boundary",
                "kml": _SAMPLE_KML,
            },
            headers=tenant_a["headers"],
        )
        assert res.status_code == 201, res.text
        body = res.json()
        feats = body["geojson"]["features"]
        # Two placemarks: a polygon + a point.
        types = [f["geometry"]["type"] for f in feats]
        assert "Polygon" in types
        assert "Point" in types

    @pytest.mark.asyncio
    async def test_kml_with_no_placemarks_422(self, http_client, tenant_a):
        res = await http_client.post(
            "/api/v1/geo-hub/overlays/import-kml/",
            json={
                "project_id": tenant_a["project_id"],
                "kml": "<?xml version='1.0'?><kml xmlns='http://www.opengis.net/kml/2.2'><Document/></kml>",
            },
            headers=tenant_a["headers"],
        )
        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_export_geojson_merges_overlays(self, http_client, tenant_a):
        # Two overlays of its own, so the merge has something to merge even
        # when the import tests ran in another shard.
        for path, field, doc in (
            ("import-geojson", "geojson", _SAMPLE_GEOJSON),
            ("import-kml", "kml", _SAMPLE_KML),
        ):
            imported = await http_client.post(
                f"/api/v1/geo-hub/overlays/{path}/",
                json={"project_id": tenant_a["project_id"], "name": f"Export {path}", "kind": "boundary", field: doc},
                headers=tenant_a["headers"],
            )
            assert imported.status_code == 201, imported.text
        res = await http_client.get(
            f"/api/v1/geo-hub/overlays/export-geojson/?project_id={tenant_a['project_id']}",
            headers=tenant_a["headers"],
        )
        assert res.status_code == 200
        body = res.json()
        assert body["type"] == "FeatureCollection"
        assert len(body["features"]) >= 2

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_overlay_idor(self, http_client, tenant_a, tenant_b):
        # The sibling import test is deselected by the tenant-isolation -k
        # filter, so create the overlay here via import-geojson.
        created = await http_client.post(
            "/api/v1/geo-hub/overlays/import-geojson/",
            json={
                "project_id": tenant_a["project_id"],
                "name": "Site boundary",
                "kind": "boundary",
                "geojson": _SAMPLE_GEOJSON,
            },
            headers=tenant_a["headers"],
        )
        assert created.status_code in (200, 201), created.text
        ov_id = created.json()["id"]
        res = await http_client.patch(
            f"/api/v1/geo-hub/overlays/{ov_id}",
            json={"name": "ATTACKER"},
            headers=tenant_b["headers"],
        )
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_geojson_invalid_payload_rejected(
        self,
        http_client,
        tenant_a,
    ):
        res = await http_client.post(
            "/api/v1/geo-hub/overlays/import-geojson/",
            json={
                "project_id": tenant_a["project_id"],
                "name": "Bad",
                "kind": "boundary",
                "geojson": {"type": "NotAFeatureCollection"},
            },
            headers=tenant_a["headers"],
        )
        assert res.status_code in (422, 500)


# ── Viewpoints (4 tests) ───────────────────────────────────────────────


class TestViewpoints:
    @pytest.mark.asyncio
    async def test_create_and_list_viewpoint(self, http_client, tenant_a):
        res = await http_client.post(
            "/api/v1/geo-hub/viewpoints/",
            json={
                "project_id": tenant_a["project_id"],
                "name": "Overview",
                "camera_lat": "52.520",
                "camera_lon": "13.405",
                "camera_alt": "500",
                "heading": "0",
                "pitch": "-45",
            },
            headers=tenant_a["headers"],
        )
        assert res.status_code == 201, res.text
        listed = await http_client.get(
            f"/api/v1/geo-hub/viewpoints/?project_id={tenant_a['project_id']}",
            headers=tenant_a["headers"],
        )
        assert listed.status_code == 200
        assert any(v["name"] == "Overview" for v in listed.json())

    @pytest.mark.asyncio
    async def test_viewpoint_patch(self, http_client, tenant_a):
        # Its own viewpoint, not the one the create test may have made in
        # another shard.
        created = await http_client.post(
            "/api/v1/geo-hub/viewpoints/",
            json={
                "project_id": tenant_a["project_id"],
                "name": f"Patch me {uuid.uuid4().hex[:6]}",
                "camera_lat": "52.520",
                "camera_lon": "13.405",
                "camera_alt": "500",
                "heading": "0",
                "pitch": "-45",
            },
            headers=tenant_a["headers"],
        )
        assert created.status_code == 201, created.text
        vp_id = created.json()["id"]
        res = await http_client.patch(
            f"/api/v1/geo-hub/viewpoints/{vp_id}",
            json={"description": "From south-east"},
            headers=tenant_a["headers"],
        )
        assert res.status_code == 200
        assert res.json()["description"] == "From south-east"

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_viewpoint_idor(self, http_client, tenant_a, tenant_b):
        # The sibling create test is deselected by the tenant-isolation -k
        # filter, so create the viewpoint here.
        created = await http_client.post(
            "/api/v1/geo-hub/viewpoints/",
            json={
                "project_id": tenant_a["project_id"],
                "name": "Overview",
                "camera_lat": "52.520",
                "camera_lon": "13.405",
                "camera_alt": "500",
                "heading": "0",
                "pitch": "-45",
            },
            headers=tenant_a["headers"],
        )
        assert created.status_code in (200, 201), created.text
        vp_id = created.json()["id"]
        # Mutate (PATCH) cross-tenant rather than DELETE: PATCH needs
        # ``geo_hub.write`` which the editor attacker HOLDS, so the request
        # clears the RBAC gate and the 404 genuinely proves the project-access
        # (ownership) check fired - mirroring the anchor/imagery/overlay IDOR
        # tests. (DELETE needs ``geo_hub.delete``, which the editor lacks, so it
        # 403s uniformly at the RBAC gate before any resource lookup - that is
        # not an existence leak, but it would not exercise the access check.)
        res = await http_client.patch(
            f"/api/v1/geo-hub/viewpoints/{vp_id}",
            json={"description": "ATTACKER WAS HERE"},
            headers=tenant_b["headers"],
        )
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_viewpoint_invalid_latitude_rejected(
        self,
        http_client,
        tenant_a,
    ):
        res = await http_client.post(
            "/api/v1/geo-hub/viewpoints/",
            json={
                "project_id": tenant_a["project_id"],
                "name": "BadLat",
                "camera_lat": "not_a_number",  # type-coercion failure → 422
                "camera_lon": "0",
            },
            headers=tenant_a["headers"],
        )
        assert res.status_code == 422


# ── Map-config bundle (2 tests) ────────────────────────────────────────


class TestMapConfig:
    @pytest.mark.asyncio
    async def test_map_config_returns_bundle(self, http_client, tenant_a):
        await _ensure_anchor(http_client, tenant_a)
        res = await http_client.get(
            f"/api/v1/geo-hub/map-config/{tenant_a['project_id']}",
            headers=tenant_a["headers"],
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["project_id"] == tenant_a["project_id"]
        assert body["anchor"] is not None
        assert isinstance(body["imagery_layers"], list)
        assert isinstance(body["tilesets"], list)
        assert isinstance(body["overlays"], list)
        assert isinstance(body["viewpoints"], list)

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_map_config_idor(self, http_client, tenant_a, tenant_b):
        res = await http_client.get(
            f"/api/v1/geo-hub/map-config/{tenant_a['project_id']}",
            headers=tenant_b["headers"],
        )
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_map_config_unknown_development_returns_404(
        self,
        http_client,
        tenant_a,
    ):
        # ``development_id`` not under the project must 404 — IDOR closure
        # so the filter cannot be turned into a UUID-existence oracle.
        bogus = uuid.uuid4()
        res = await http_client.get(
            f"/api/v1/geo-hub/map-config/{tenant_a['project_id']}?development_id={bogus}",
            headers=tenant_a["headers"],
        )
        assert res.status_code == 404


# ── Anchored projects (Global pin layer) ───────────────────────────────


class TestAnchoredProjects:
    @pytest.mark.asyncio
    async def test_list_anchored_projects_returns_own(
        self,
        http_client,
        tenant_a,
    ):
        anchor = await _ensure_anchor(http_client, tenant_a)
        res = await http_client.get(
            "/api/v1/geo-hub/projects",
            headers=tenant_a["headers"],
        )
        assert res.status_code == 200, res.text
        rows = res.json()
        assert isinstance(rows, list)
        # The anchored project appears in the global pin list, pinned by its
        # anchor rather than by an address fallback.
        by_id = {r["project_id"]: r for r in rows}
        assert tenant_a["project_id"] in by_id
        assert by_id[tenant_a["project_id"]]["anchor_id"] == anchor["id"]
        # And every row carries the minimum fields the frontend needs to
        # paint a pin.
        for r in rows:
            assert "lat" in r and "lon" in r
            assert "project_name" in r
            assert "anchor_id" in r

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_list_anchored_projects_excludes_other_tenants(
        self,
        http_client,
        tenant_a,
        tenant_b,
    ):
        # tenant_b is a non-admin editor — tenant_a's anchored project
        # must NOT appear in tenant_b's list (single-tenant per-project).
        # Anchored here, or its absence would prove nothing.
        await _ensure_anchor(http_client, tenant_a)
        res = await http_client.get(
            "/api/v1/geo-hub/projects",
            headers=tenant_b["headers"],
        )
        assert res.status_code == 200
        ids = {r["project_id"] for r in res.json()}
        assert tenant_a["project_id"] not in ids

    @pytest.mark.asyncio
    async def test_list_anchored_projects_requires_auth(self, http_client):
        res = await http_client.get("/api/v1/geo-hub/projects")
        assert res.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_address_coords_without_anchor_are_pinned(
        self,
        http_client,
        tenant_b,
    ):
        """A project with ``address.lat``/``lng`` but NO GeoAnchor must still
        appear on the global map (the demo / showcase seeds store coords this
        way and used to be silently dropped by the old inner join)."""
        # Fresh project owned by tenant_b (non-admin editor) so it stays
        # tenant-scoped and never pollutes other tests.
        proj = await http_client.post(
            "/api/v1/projects/",
            json={
                "name": f"AddrOnly {uuid.uuid4().hex[:6]}",
                "description": "address coords, no anchor",
                "currency": "EUR",
            },
            headers=tenant_b["headers"],
        )
        assert proj.status_code == 201, proj.text
        pid = proj.json()["id"]

        # Stamp the address JSONB with coordinates directly — the project has
        # NO GeoAnchor row, mirroring the showcase snapshot's shape.
        from sqlalchemy import update

        from app.database import async_session_factory
        from app.modules.projects.models import Project

        async with async_session_factory() as s:
            await s.execute(
                update(Project)
                .where(Project.id == uuid.UUID(pid))
                .values(address={"city": "Berlin", "lat": 52.5173885, "lng": 13.3951309})
            )
            await s.commit()

        res = await http_client.get(
            "/api/v1/geo-hub/projects",
            headers=tenant_b["headers"],
        )
        assert res.status_code == 200, res.text
        row = next((r for r in res.json() if r["project_id"] == pid), None)
        assert row is not None, "address-only project should be pinned"
        # Coords come from the address; no anchor exists yet.
        assert row["anchor_id"] is None
        assert abs(float(row["lat"]) - 52.5173885) < 1e-6
        assert abs(float(row["lon"]) - 13.3951309) < 1e-6

    @pytest.mark.asyncio
    async def test_newer_projects_without_a_location_do_not_crowd_out_the_pins(self, http_client):
        """``limit`` counts pins, not every project the caller can see.

        It used to be applied before the projects without a location were
        dropped, so a caller whose newest projects had none got fewer pins
        than the limit, down to an empty map, while older located projects
        existed. The admin view of a large install is where that bites; a
        fresh account and a small limit show the same thing.
        """
        email, meta = await _register(http_client, "crowded")
        await _set_role(email, "editor")
        owner = {"headers": await _login(http_client, email, meta["_password"])}

        async def _project(label: str) -> str:
            res = await http_client.post(
                "/api/v1/projects/",
                json={"name": f"{label} {uuid.uuid4().hex[:6]}", "currency": "EUR"},
                headers=owner["headers"],
            )
            assert res.status_code == 201, res.text
            return res.json()["id"]

        anchored = await _project("Anchored")
        await _ensure_anchor(http_client, {**owner, "project_id": anchored})

        address_only = await _project("AddrOnly")
        from sqlalchemy import update

        from app.database import async_session_factory
        from app.modules.projects.models import Project

        async with async_session_factory() as s:
            await s.execute(
                update(Project)
                .where(Project.id == uuid.UUID(address_only))
                .values(address={"city": "Munich", "lat": 48.1371, "lon": 11.5754})
            )
            await s.commit()

        for _ in range(3):
            await _project("Unlocated")

        res = await http_client.get("/api/v1/geo-hub/projects?limit=2", headers=owner["headers"])
        assert res.status_code == 200, res.text
        ids = [r["project_id"] for r in res.json()]
        assert ids == [address_only, anchored], f"the two located projects, newest first, got {ids}"
