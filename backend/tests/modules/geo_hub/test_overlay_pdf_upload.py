"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PDF upload: overlay is created, raster bytes are generated, and default
corners follow the project's own location: the persisted anchor bbox when
one exists, and the address-derived coordinates when the project is located
by address only (regression against the overlay landing on null island)."""

from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_pdf_upload_generates_raster_and_default_corners(
    http_client,
    tenant_a,
    tiny_pdf,
):
    files = {"file": ("plan.pdf", tiny_pdf, "application/pdf")}
    res = await http_client.post(
        "/api/v1/geo-hub/raster-overlays/upload-pdf",
        data={"project_id": tenant_a["project_id"], "page": "1"},
        files=files,
        headers=tenant_a["headers"],
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["page_count"] >= 1

    overlay = body["overlay"]
    assert overlay["source_kind"] == "pdf"
    assert overlay["raster_width_px"] > 0
    assert overlay["raster_height_px"] > 0
    assert overlay["raster_blob_url"], "rasterised PNG path expected"

    # Four corners stamped from the project anchor's bbox.
    corners = overlay["corners_geojson"]
    assert isinstance(corners, list) and len(corners) == 4
    # Anchor is 13.4050, 52.5200 — corners should bracket that point.
    lons = [c[0] for c in corners]
    lats = [c[1] for c in corners]
    assert min(lons) < 13.4050 < max(lons)
    assert min(lats) < 52.5200 < max(lats)

    # Raster bytes are serve-able.
    raster = await http_client.get(
        f"/api/v1/geo-hub/raster-overlays/{overlay['id']}/raster.png",
        headers=tenant_a["headers"],
    )
    assert raster.status_code == 200
    assert raster.headers["content-type"] == "image/png"
    assert raster.content[:8] == b"\x89PNG\r\n\x1a\n", "PNG magic bytes"

    # List endpoint returns the overlay.
    list_res = await http_client.get(
        f"/api/v1/geo-hub/raster-overlays/?project_id={tenant_a['project_id']}",
        headers=tenant_a["headers"],
    )
    assert list_res.status_code == 200
    assert any(r["id"] == overlay["id"] for r in list_res.json())


@pytest.mark.asyncio
async def test_pdf_upload_corners_follow_address_when_no_real_anchor(
    http_client,
    tenant_a,
    tiny_pdf,
):
    """A project located only by its address coords (no real GeoAnchor, or
    just the 0/0 placeholder the ``projects.created`` subscriber seeds) must
    get its placed overlay centred on that address, not dropped on null
    island. Regression for the "Place file on map anchors at the wrong
    point" bug: ``_default_corners_for_project`` used to read the persisted
    anchor only, ignoring the address-derived location the map itself uses.
    """
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.projects.models import Project

    # Fresh project - gets a 0/0 placeholder anchor from projects.created,
    # and no address (so the geocoding address_set path never runs).
    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"AddrDerived {uuid.uuid4().hex[:6]}",
            "description": "located by address coords only",
            "currency": "EUR",
        },
        headers=tenant_a["headers"],
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    # Stamp address coords straight onto the JSONB (no event fired, so the
    # 0/0 placeholder anchor stays in place). Paris, deliberately far from
    # both null island and tenant_a's Berlin anchor.
    addr_lat, addr_lon = 48.8566, 2.3522
    async with async_session_factory() as session:
        await session.execute(
            update(Project)
            .where(Project.id == uuid.UUID(project_id))
            .values(
                address={
                    "city": "Paris",
                    "country": "France",
                    "country_code": "FR",
                    "lat": addr_lat,
                    "lng": addr_lon,
                }
            )
        )
        await session.commit()

    files = {"file": ("plan.pdf", tiny_pdf, "application/pdf")}
    res = await http_client.post(
        "/api/v1/geo-hub/raster-overlays/upload-pdf",
        data={"project_id": project_id, "page": "1"},
        files=files,
        headers=tenant_a["headers"],
    )
    assert res.status_code == 201, res.text
    corners = res.json()["overlay"]["corners_geojson"]
    assert isinstance(corners, list) and len(corners) == 4
    lons = [c[0] for c in corners]
    lats = [c[1] for c in corners]
    # Corners bracket the address point, NOT (0, 0).
    assert min(lons) < addr_lon < max(lons)
    assert min(lats) < addr_lat < max(lats)
    assert max(abs(v) for v in lons) < 5.0, "overlay must not land near null island"
