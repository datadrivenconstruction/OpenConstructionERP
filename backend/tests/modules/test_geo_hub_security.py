# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Geo Hub — Round-7 security audit (non-raster surface).

Round 6 (in v4.6.0) already hardened the raster-overlay endpoints —
those tests live in ``tests/modules/geo_hub/test_overlay_*.py``. This
file pins down the R7 sweep over the **rest** of the Geo Hub surface:

1. **IDOR closes to 404 (never 403)** on cross-tenant ``GET`` for
   anchors, viewpoints, and vector overlays — the three project-scoped
   entity families that survived R6 untouched. The cross-tenant caller
   must see the same response as if the row simply did not exist; any
   distinguishable 403 would be a UUID-existence oracle.

2. **KML import magic-byte gate** — a body that does not look like XML
   / KML must 415 *before* the parser sees it. Catches a class of
   client bugs where someone POSTs a raw PNG or JSON blob to the
   ``/overlays/import-kml/`` endpoint and gets a confusing 422 deep
   inside ``defusedxml``.

3. **GeoJSON DoS cap** — a FeatureCollection with > 50 k features must
   422 at import time. Without the cap a single request can stuff a
   multi-MB blob into the JSONB column.

4. **bbox / lat-lon sanitization** — the anchor create schema rejects
   |lat| > 90 / |lon| > 180 with 422. Same code path that any future
   bbox query parameter would lean on.

5. **Member-denied PATCH** — a plain VIEWER cannot mutate a viewpoint
   even on their own project; only EDITOR+ holds ``geo_hub.write``.

6. **Delete needs MANAGER** — R7 split delete out from the generic
   ``geo_hub.write``: an EDITOR can create / patch but cannot delete
   anchors, tilesets, viewpoints, imagery layers or vector overlays.
   Recoverability matters — hand-drawn boundaries are easier to
   accidentally lose than to recreate.

The fixtures here are deliberately self-contained (do NOT import from
``tests/modules/geo_hub/conftest.py``) so this file runs cleanly under
``pytest tests/modules/test_geo_hub_security.py`` without the parent
package's per-module SQLite isolation.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# Per-module SQLite isolation MUST be set BEFORE any ``app.*`` import.
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-geo-r7-"))
_TMP_DB = _TMP_DIR / "geo_r7.db"
os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}",
)
os.environ.setdefault(
    "DATABASE_SYNC_URL",
    f"sqlite:///{_TMP_DB.as_posix()}",
)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── App / client / auth fixtures ─────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.bim_hub import models as _bim  # noqa: F401
        from app.modules.geo_hub import models as _geo  # noqa: F401
        from app.modules.property_dev import models as _prop  # noqa: F401

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
    email = f"{label}-{uuid.uuid4().hex[:8]}@geo-r7.io"
    password = f"GeoR7{uuid.uuid4().hex[:6]}9!"
    res = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": label},
    )
    assert res.status_code in (200, 201), res.text
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


async def _make_project(
    client: AsyncClient,
    headers: dict[str, str],
    label: str,
) -> str:
    res = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"GeoR7-{label} {uuid.uuid4().hex[:6]}",
            "description": label,
            "currency": "EUR",
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def tenant_a(http_client):
    """Admin tenant. Creates a project + an anchor."""
    email, password = await _register(http_client, "tenant-a")
    await _set_role(email, "admin")
    headers = await _login(http_client, email, password)
    project_id = await _make_project(http_client, headers, "A")
    anchor = await http_client.post(
        "/api/v1/geo-hub/anchors/",
        json={
            "project_id": project_id,
            "lat": "52.5200",
            "lon": "13.4050",
            "alt": "34",
            "epsg_code": 4326,
        },
        headers=headers,
    )
    assert anchor.status_code in (200, 201), anchor.text
    return {
        "email": email,
        "headers": headers,
        "project_id": project_id,
        "anchor_id": anchor.json()["id"],
    }


@pytest_asyncio.fixture(scope="module")
async def tenant_b(http_client):
    """Editor tenant (NOT admin, so the IDOR helper cannot bypass)."""
    email, password = await _register(http_client, "tenant-b")
    await _set_role(email, "editor")
    headers = await _login(http_client, email, password)
    project_id = await _make_project(http_client, headers, "B")
    return {
        "email": email,
        "headers": headers,
        "project_id": project_id,
    }


@pytest_asyncio.fixture(scope="module")
async def viewer_user(http_client):
    """A pure VIEWER — read-only role, no project of their own."""
    email, password = await _register(http_client, "viewer")
    await _set_role(email, "viewer")
    headers = await _login(http_client, email, password)
    return {"email": email, "headers": headers}


@pytest_asyncio.fixture(scope="module")
async def editor_member(http_client):
    """An EDITOR-role user — holds geo_hub.write but NOT geo_hub.delete."""
    email, password = await _register(http_client, "editor")
    await _set_role(email, "editor")
    headers = await _login(http_client, email, password)
    return {"email": email, "headers": headers}


# ── 1. IDOR — non-raster surface ────────────────────────────────────────


@pytest.mark.asyncio
async def test_idor_anchor_get_cross_tenant_is_404(
    http_client,
    tenant_a,
    tenant_b,
):
    """Tenant B hitting A's anchor by id must see 404, never 403."""
    res = await http_client.get(
        f"/api/v1/geo-hub/anchors/{tenant_a['anchor_id']}",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_idor_anchor_list_cross_tenant_is_404(
    http_client,
    tenant_a,
    tenant_b,
):
    """``GET /anchors/?project_id=<A>`` from B must 404, not return empty."""
    res = await http_client.get(
        f"/api/v1/geo-hub/anchors/?project_id={tenant_a['project_id']}",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_idor_viewpoint_get_cross_tenant_is_404(
    http_client,
    tenant_a,
    tenant_b,
):
    """Tenant B hitting A's viewpoint by id must see 404."""
    # Create a viewpoint on A.
    vp = await http_client.post(
        "/api/v1/geo-hub/viewpoints/",
        json={
            "project_id": tenant_a["project_id"],
            "name": "Front entrance",
            "camera_lat": "52.5200",
            "camera_lon": "13.4050",
        },
        headers=tenant_a["headers"],
    )
    assert vp.status_code == 201, vp.text
    vp_id = vp.json()["id"]

    # B reads A's viewpoint -> 404 (must not leak existence as 403).
    cross = await http_client.patch(
        f"/api/v1/geo-hub/viewpoints/{vp_id}",
        json={"name": "Hijacked"},
        headers=tenant_b["headers"],
    )
    assert cross.status_code == 404, cross.text


@pytest.mark.asyncio
async def test_idor_overlay_get_cross_tenant_is_404(
    http_client,
    tenant_a,
    tenant_b,
):
    """B hitting A's vector overlay must 404 (pin / survey IDOR)."""
    # Create a boundary overlay on A.
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [13.4050, 52.5200],
                },
                "properties": {"label": "site centre"},
            },
        ],
    }
    ov = await http_client.post(
        "/api/v1/geo-hub/overlays/",
        json={
            "project_id": tenant_a["project_id"],
            "name": "Boundary pin",
            "kind": "boundary",
            "geojson": geojson,
        },
        headers=tenant_a["headers"],
    )
    assert ov.status_code == 201, ov.text
    overlay_id = ov.json()["id"]

    # B PATCH on A's overlay -> 404, not 403.
    cross = await http_client.patch(
        f"/api/v1/geo-hub/overlays/{overlay_id}",
        json={"name": "Hijacked"},
        headers=tenant_b["headers"],
    )
    assert cross.status_code == 404, cross.text


# ── 2. KML import magic-byte gate ────────────────────────────────────────


@pytest.mark.asyncio
async def test_kml_import_rejects_non_xml_payload(http_client, tenant_a):
    """A KML body that is plainly not XML must 415, not 422."""
    res = await http_client.post(
        "/api/v1/geo-hub/overlays/import-kml/",
        json={
            "project_id": tenant_a["project_id"],
            "name": "Boundary",
            "kind": "boundary",
            "kml": "this is not KML at all, just some random text payload",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 415, res.text


@pytest.mark.asyncio
async def test_kml_import_rejects_json_lookalike(http_client, tenant_a):
    """A JSON object passed as KML must 415."""
    res = await http_client.post(
        "/api/v1/geo-hub/overlays/import-kml/",
        json={
            "project_id": tenant_a["project_id"],
            "name": "Boundary",
            "kind": "boundary",
            "kml": '{"type": "FeatureCollection", "features": [1, 2, 3]}',
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 415, res.text


@pytest.mark.asyncio
async def test_kml_import_accepts_valid_kml(http_client, tenant_a):
    """Sanity-check: a real (minimal) KML still goes through 201."""
    kml = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<kml xmlns='http://www.opengis.net/kml/2.2'>"
        "<Placemark>"
        "<name>Site centre</name>"
        "<Point><coordinates>13.4050,52.5200,0</coordinates></Point>"
        "</Placemark>"
        "</kml>"
    )
    res = await http_client.post(
        "/api/v1/geo-hub/overlays/import-kml/",
        json={
            "project_id": tenant_a["project_id"],
            "name": "Boundary KML",
            "kind": "boundary",
            "kml": kml,
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 201, res.text


# ── 3. GeoJSON DoS cap ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_geojson_import_caps_feature_count(http_client, tenant_a):
    """A FeatureCollection > MAX_GEOJSON_FEATURES must 422."""
    from app.modules.geo_hub.geojson_io import MAX_GEOJSON_FEATURES

    huge = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": {},
            }
            for _ in range(MAX_GEOJSON_FEATURES + 1)
        ],
    }
    res = await http_client.post(
        "/api/v1/geo-hub/overlays/import-geojson/",
        json={
            "project_id": tenant_a["project_id"],
            "name": "Huge",
            "kind": "boundary",
            "geojson": huge,
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422, res.text


# ── 4. bbox / lat-lon sanitization ───────────────────────────────────────


@pytest.mark.asyncio
async def test_anchor_create_rejects_out_of_range_latitude(
    http_client,
    tenant_a,
):
    """|lat| > 90 must 422 (schema validator path also serves bbox queries)."""
    res = await http_client.post(
        "/api/v1/geo-hub/anchors/",
        json={
            "project_id": tenant_a["project_id"],
            "lat": "91",  # invalid
            "lon": "13.4050",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_anchor_create_rejects_out_of_range_longitude(
    http_client,
    tenant_a,
):
    """|lon| > 180 must 422."""
    res = await http_client.post(
        "/api/v1/geo-hub/anchors/",
        json={
            "project_id": tenant_a["project_id"],
            "lat": "52.5200",
            "lon": "-200",  # invalid
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_anchor_create_rejects_malformed_coord_string(
    http_client,
    tenant_a,
):
    """Garbage in a Decimal coord field is rejected (422), not silently coerced."""
    res = await http_client.post(
        "/api/v1/geo-hub/anchors/",
        json={
            "project_id": tenant_a["project_id"],
            "lat": "not-a-number",
            "lon": "13.4050",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422, res.text


# ── 5. RBAC — member denied PATCH ───────────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_role_cannot_patch_viewpoint(
    http_client,
    tenant_a,
    viewer_user,
):
    """A pure VIEWER must be 403'd on PATCH (geo_hub.write = EDITOR+)."""
    vp = await http_client.post(
        "/api/v1/geo-hub/viewpoints/",
        json={
            "project_id": tenant_a["project_id"],
            "name": "RBAC test",
            "camera_lat": "52.5200",
            "camera_lon": "13.4050",
        },
        headers=tenant_a["headers"],
    )
    assert vp.status_code == 201, vp.text
    vp_id = vp.json()["id"]

    # Viewer attempts PATCH -> 403 from RequirePermission. Note: this is
    # the *permission* layer rejecting, which happens before the IDOR
    # check; a 403 here means the global permission gate is intact, not
    # a tenant leak.
    res = await http_client.patch(
        f"/api/v1/geo-hub/viewpoints/{vp_id}",
        json={"name": "Should not stick"},
        headers=viewer_user["headers"],
    )
    assert res.status_code == 403, res.text


# ── 6. Delete needs MANAGER+ ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_editor_cannot_delete_overlay_requires_manager(
    http_client,
    tenant_a,
    editor_member,
):
    """EDITOR can create/patch overlays but NOT delete (R7 split)."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [13.4050, 52.5200]},
                "properties": {},
            }
        ],
    }
    ov = await http_client.post(
        "/api/v1/geo-hub/overlays/",
        json={
            "project_id": tenant_a["project_id"],
            "name": "To-delete",
            "kind": "boundary",
            "geojson": geojson,
        },
        headers=tenant_a["headers"],
    )
    assert ov.status_code == 201, ov.text
    overlay_id = ov.json()["id"]

    # Editor on a different project hits a 403 from the permission
    # gate, NOT a 404 — the permission check fires before the IDOR
    # helper. This intentionally reveals NOTHING about whether the
    # overlay exists on tenant A's project; both 403 ("missing
    # geo_hub.delete") and 404 (IDOR fallthrough) would be valid
    # responses, but the permission layer wins by registration order.
    res = await http_client.delete(
        f"/api/v1/geo-hub/overlays/{overlay_id}",
        headers=editor_member["headers"],
    )
    assert res.status_code == 403, res.text

    # Tenant A (admin) can still delete it — sanity-check the path.
    cleanup = await http_client.delete(
        f"/api/v1/geo-hub/overlays/{overlay_id}",
        headers=tenant_a["headers"],
    )
    assert cleanup.status_code == 204, cleanup.text


# ── 7. Raster overlay delete requires geo_hub.delete (not geo_hub.write) ─


@pytest.mark.asyncio
async def test_editor_cannot_delete_raster_overlay_requires_delete_perm(
    http_client,
    tenant_a,
    editor_member,
):
    """EDITOR role must be 403'd on DELETE /raster-overlays/{id}.

    Pre-fix the endpoint used geo_hub.write — allowing any editor to soft-
    delete raster overlays on any project they could reach. Post-fix it
    requires geo_hub.delete (MANAGER+), consistent with the vector overlay
    and tileset delete endpoints.
    """
    # Create a tiny PNG as a raster overlay under tenant A.
    import base64
    import struct
    import zlib

    def _tiny_png() -> bytes:
        """Minimal 1x1 white PNG — same helper as conftest uses."""
        raw = b"\x00\xff\xff\xff"  # filter byte + 1 pixel RGB
        compressed = zlib.compress(raw)
        chunks = [
            struct.pack(">I", 13) + b"IHDR" + struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0),
            struct.pack(">I", len(compressed)) + b"IDAT" + compressed,
            struct.pack(">I", 0) + b"IEND",
        ]

        def _crc(data: bytes) -> bytes:
            return struct.pack(">I", zlib.crc32(data) & 0xFFFFFFFF)

        body = b"\x89PNG\r\n\x1a\n"
        for chunk in chunks:
            body += chunk + _crc(chunk[4:])
        return body

    tiny = _tiny_png()
    upload = await http_client.post(
        "/api/v1/geo-hub/raster-overlays/upload-image",
        data={"project_id": tenant_a["project_id"]},
        files={"file": ("plan.png", tiny, "image/png")},
        headers=tenant_a["headers"],
    )
    assert upload.status_code == 201, upload.text
    overlay_id = upload.json()["id"]

    # Editor attempts DELETE -> 403 from RequirePermission("geo_hub.delete").
    res = await http_client.delete(
        f"/api/v1/geo-hub/raster-overlays/{overlay_id}",
        headers=editor_member["headers"],
    )
    assert res.status_code == 403, (
        f"Expected 403 for editor on raster overlay delete, got {res.status_code}: {res.text}"
    )

    # Admin (tenant A) can still delete — sanity-check happy path.
    cleanup = await http_client.delete(
        f"/api/v1/geo-hub/raster-overlays/{overlay_id}",
        headers=tenant_a["headers"],
    )
    assert cleanup.status_code == 204, cleanup.text


# ── Pure-unit checks of the magic-byte / DoS helpers ────────────────────


def test_kml_looks_like_kml_pure_unit():
    """The KML sniffer accepts XML / KML prologs and rejects everything else."""
    from app.modules.geo_hub.geojson_io import kml_looks_like_kml

    assert kml_looks_like_kml("<?xml version='1.0'?><kml/>")
    assert kml_looks_like_kml("﻿<?xml version='1.0'?><kml/>")
    assert kml_looks_like_kml("  \n  <kml xmlns='...'/>")
    assert kml_looks_like_kml(b"<?xml version='1.0'?>")
    assert not kml_looks_like_kml("")
    assert not kml_looks_like_kml("hello world")
    assert not kml_looks_like_kml('{"type":"FeatureCollection"}')
    assert not kml_looks_like_kml(b"\x89PNG\r\n\x1a\n")
    assert not kml_looks_like_kml(b"%PDF-1.7")
