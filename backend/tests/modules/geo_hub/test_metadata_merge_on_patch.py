"""Regression: geo_hub PATCH must MERGE the ``metadata_`` JSON column.

Audit finding #14 - the shared ``_dump`` helper renamed ``metadata`` ->
``metadata_`` and fed it straight into ``update_fields``, which issues a plain
``UPDATE ... SET metadata = <new dict>``. A PATCH that sent ``metadata``
partially therefore silently DROPPED every other key already stored on the row
(geocode precision/source on anchors, rasterisation provenance on raster
overlays, GeoJSON feature metadata on overlays, ...).

These tests seed a row with two metadata keys, PATCH a *single* (new) key, and
assert the pre-existing keys survive - i.e. the column is shallow-merged, not
overwritten. They fail against the pre-fix code (the seeded keys vanish) and
pass once ``_dump`` merges via ``app.core.json_merge.merge_metadata``.

Mirrors the HTTP + tenant-fixture style of ``test_anchor_from_address.py`` and
the shared fixtures in ``conftest.py``.
"""

from __future__ import annotations

import uuid

import pytest


async def _fresh_project(http_client, tenant_a) -> str:
    """Create a fresh tenant_a project (no address -> no auto-anchor)."""
    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"MetaMerge-{uuid.uuid4().hex[:6]}",
            "description": "metadata merge regression",
            "currency": "EUR",
        },
        headers=tenant_a["headers"],
    )
    assert proj.status_code == 201, proj.text
    return proj.json()["id"]


def _meta(body: dict) -> dict:
    """Response model field is ``metadata`` but the alias may surface it as
    ``metadata_`` depending on FastAPI's ``response_model_by_alias`` config."""
    return body.get("metadata") or body.get("metadata_") or {}


@pytest.mark.asyncio
async def test_anchor_patch_merges_metadata_keeps_existing_keys(
    http_client,
    tenant_a,
):
    project_id = await _fresh_project(http_client, tenant_a)

    # Seed an anchor carrying TWO metadata keys.
    created = await http_client.post(
        "/api/v1/geo-hub/anchors/",
        json={
            "project_id": project_id,
            "lat": "52.5200",
            "lon": "13.4050",
            "epsg_code": 4326,
            "metadata": {"geocode_precision": "address", "label": "Site office"},
        },
        headers=tenant_a["headers"],
    )
    assert created.status_code in (200, 201), created.text
    anchor_id = created.json()["id"]
    seeded = _meta(created.json())
    assert seeded.get("geocode_precision") == "address"
    assert seeded.get("label") == "Site office"

    # PATCH a SINGLE, new metadata key. Pre-fix this overwrote the whole
    # column and dropped ``geocode_precision`` + ``label``.
    patched = await http_client.patch(
        f"/api/v1/geo-hub/anchors/{anchor_id}",
        json={"metadata": {"note": "patched"}},
        headers=tenant_a["headers"],
    )
    assert patched.status_code == 200, patched.text
    meta = _meta(patched.json())
    # The new key is applied ...
    assert meta.get("note") == "patched"
    # ... and the pre-existing keys SURVIVE the merge (the regression guard).
    assert meta.get("geocode_precision") == "address"
    assert meta.get("label") == "Site office"

    # Confirm it is persisted (not just echoed) via a fresh GET.
    fetched = await http_client.get(
        f"/api/v1/geo-hub/anchors/{anchor_id}",
        headers=tenant_a["headers"],
    )
    assert fetched.status_code == 200, fetched.text
    meta2 = _meta(fetched.json())
    assert meta2.get("note") == "patched"
    assert meta2.get("geocode_precision") == "address"
    assert meta2.get("label") == "Site office"


@pytest.mark.asyncio
async def test_overlay_patch_merges_metadata_keeps_existing_keys(
    http_client,
    tenant_a,
):
    """Same guarantee on a different ``_dump`` consumer (GeoOverlay)."""
    project_id = await _fresh_project(http_client, tenant_a)

    created = await http_client.post(
        "/api/v1/geo-hub/overlays/",
        json={
            "project_id": project_id,
            "name": "Survey lines",
            "kind": "survey",
            "metadata": {"source": "survey", "crs": "EPSG:4326"},
        },
        headers=tenant_a["headers"],
    )
    assert created.status_code in (200, 201), created.text
    overlay_id = created.json()["id"]

    patched = await http_client.patch(
        f"/api/v1/geo-hub/overlays/{overlay_id}",
        json={"metadata": {"reviewed": True}},
        headers=tenant_a["headers"],
    )
    assert patched.status_code == 200, patched.text
    meta = _meta(patched.json())
    assert meta.get("reviewed") is True
    # Pre-existing provenance keys must survive the partial PATCH.
    assert meta.get("source") == "survey"
    assert meta.get("crs") == "EPSG:4326"
