"""PDF upload happy path — overlay is created, raster bytes are
generated, default corners follow the project's anchor bbox."""

from __future__ import annotations

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
