"""Cross-tenant IDOR closures collapse to 404 (not 403)."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_tenant_b_cannot_see_tenant_a_overlays(
    http_client,
    tenant_a,
    tenant_b,
    tiny_png,
):
    # Tenant A creates an image overlay.
    files = {"file": ("plan.png", tiny_png, "image/png")}
    res = await http_client.post(
        "/api/v1/geo-hub/raster-overlays/upload-image",
        data={"project_id": tenant_a["project_id"]},
        files=files,
        headers=tenant_a["headers"],
    )
    assert res.status_code == 201, res.text
    overlay_id = res.json()["id"]

    # Tenant B (editor, non-admin) hits A's overlay -> 404, not 403.
    get_b = await http_client.get(
        f"/api/v1/geo-hub/raster-overlays/{overlay_id}",
        headers=tenant_b["headers"],
    )
    assert get_b.status_code == 404

    # PATCH from B -> 404.
    patch_b = await http_client.patch(
        f"/api/v1/geo-hub/raster-overlays/{overlay_id}",
        json={"opacity": "0.3"},
        headers=tenant_b["headers"],
    )
    assert patch_b.status_code == 404

    # DELETE from B -> 404.
    del_b = await http_client.delete(
        f"/api/v1/geo-hub/raster-overlays/{overlay_id}",
        headers=tenant_b["headers"],
    )
    assert del_b.status_code == 404

    # Raster fetch from B -> 404.
    raster_b = await http_client.get(
        f"/api/v1/geo-hub/raster-overlays/{overlay_id}/raster.png",
        headers=tenant_b["headers"],
    )
    assert raster_b.status_code == 404

    # B asking for A's project list -> 404 (project-not-found).
    list_b_cross = await http_client.get(
        f"/api/v1/geo-hub/raster-overlays/?project_id={tenant_a['project_id']}",
        headers=tenant_b["headers"],
    )
    assert list_b_cross.status_code == 404

    # A still owns the overlay and can soft-delete it.
    del_a = await http_client.delete(
        f"/api/v1/geo-hub/raster-overlays/{overlay_id}",
        headers=tenant_a["headers"],
    )
    assert del_a.status_code == 204

    # After soft delete A no longer sees it in list.
    list_a = await http_client.get(
        f"/api/v1/geo-hub/raster-overlays/?project_id={tenant_a['project_id']}",
        headers=tenant_a["headers"],
    )
    assert list_a.status_code == 200
    assert all(r["id"] != overlay_id for r in list_a.json())
