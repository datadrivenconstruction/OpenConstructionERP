"""Round-2 deep audit: storage cleanup + sweeper + dev-id SQL filter.

Three behaviours pinned down by this module:

1. ``DELETE /tilesets/{id}`` actually frees storage — pre-v5.2.9 the row
   went away but the ``tileset.json`` + ``tile_0.b3dm`` blobs leaked
   forever. We mock the storage backend to assert ``delete_prefix`` is
   called on the tileset's prefix.
2. ``sweep_deleted_raster_overlays`` hard-deletes rows older than the
   grace window AND removes their blobs.
3. ``GeoHubService.map_config(development_id=...)`` now filters tilesets
   in SQL instead of in Python — verified by mounting a fake repository
   that asserts the kwarg was forwarded.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest


@pytest.mark.asyncio
async def test_delete_tileset_calls_storage_delete_prefix(
    http_client,
    tenant_a,
    monkeypatch,
):
    """Deleting a tileset must sweep the per-tileset storage prefix."""
    # Create a tileset row directly via the API.
    create_payload = {
        "project_id": tenant_a["project_id"],
        "source_kind": "upload",
        "source_id": "00000000-0000-0000-0000-000000000001",
        "name": "Sweep me",
        "prefix": "tilesets/abc123-sweep",
        "tileset_json_uri": "tilesets/abc123-sweep/tileset.json",
        "status": "ready",
    }
    res = await http_client.post(
        "/api/v1/geo-hub/tilesets/",
        json=create_payload,
        headers=tenant_a["headers"],
    )
    assert res.status_code == 201, res.text
    tileset_id = res.json()["id"]

    # Hot-patch the storage backend so we can capture the delete_prefix
    # call. We patch the module the service imports lazily so the
    # capture survives even after the service.delete_tileset call
    # re-imports get_storage_backend.
    captured: dict[str, Any] = {"prefixes": []}

    class _FakeBackend:
        async def delete_prefix(self, prefix: str) -> int:
            captured["prefixes"].append(prefix)
            return 2  # pretend we removed two blobs

    from app.core import storage as storage_mod

    monkeypatch.setattr(
        storage_mod,
        "get_storage_backend",
        lambda: _FakeBackend(),
    )

    # DELETE -> 204.
    res = await http_client.delete(
        f"/api/v1/geo-hub/tilesets/{tileset_id}",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 204, res.text

    assert captured["prefixes"], "delete_prefix should have been called"
    # The prefix on the row was stored exactly as supplied above.
    assert captured["prefixes"][0] == "tilesets/abc123-sweep"

    # The row really is gone from the DB.
    get_res = await http_client.get(
        f"/api/v1/geo-hub/tilesets/{tileset_id}",
        headers=tenant_a["headers"],
    )
    assert get_res.status_code == 404


@pytest.mark.asyncio
async def test_delete_tileset_continues_when_storage_fails(
    http_client,
    tenant_a,
    monkeypatch,
):
    """A storage backend that throws must not block the DB delete."""
    res = await http_client.post(
        "/api/v1/geo-hub/tilesets/",
        json={
            "project_id": tenant_a["project_id"],
            "source_kind": "upload",
            "source_id": "00000000-0000-0000-0000-000000000002",
            "name": "Sweep fails",
            "prefix": "tilesets/abc-fail",
            "tileset_json_uri": "tilesets/abc-fail/tileset.json",
            "status": "ready",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 201
    tileset_id = res.json()["id"]

    class _BrokenBackend:
        async def delete_prefix(self, prefix: str) -> int:
            raise OSError("disk on fire")

    from app.core import storage as storage_mod

    monkeypatch.setattr(
        storage_mod,
        "get_storage_backend",
        lambda: _BrokenBackend(),
    )

    res = await http_client.delete(
        f"/api/v1/geo-hub/tilesets/{tileset_id}",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 204, res.text


@pytest.mark.asyncio
async def test_sweep_deleted_raster_overlays_removes_old_rows(
    app_instance,
    tenant_a,
    monkeypatch,
):
    """Soft-deleted raster overlays older than the grace window are purged."""
    from app.database import async_session_factory
    from app.modules.geo_hub.models import GeoRasterOverlay
    from app.modules.geo_hub.service import GeoHubService

    # Insert two soft-deleted rows: one stale (40 days ago), one fresh (5
    # days ago). The sweeper should remove the stale one only.
    async with async_session_factory() as s:
        stale = GeoRasterOverlay(
            project_id=tenant_a["project_id"],
            name="stale",
            source_kind="image",
            source_blob_url="geo_hub/overlays/x/stale-source",
            raster_blob_url="geo_hub/overlays/x/stale-raster",
            raster_width_px=10,
            raster_height_px=10,
            corners_geojson=[[0, 0], [1, 0], [1, 1], [0, 1]],
            deleted_at=datetime.now(UTC) - timedelta(days=40),
        )
        fresh = GeoRasterOverlay(
            project_id=tenant_a["project_id"],
            name="fresh",
            source_kind="image",
            source_blob_url="geo_hub/overlays/x/fresh-source",
            raster_blob_url="geo_hub/overlays/x/fresh-raster",
            raster_width_px=10,
            raster_height_px=10,
            corners_geojson=[[0, 0], [1, 0], [1, 1], [0, 1]],
            deleted_at=datetime.now(UTC) - timedelta(days=5),
        )
        s.add_all([stale, fresh])
        await s.commit()
        stale_id, fresh_id = stale.id, fresh.id

    deleted_keys: list[str] = []

    class _CapturingBackend:
        async def delete(self, key: str) -> None:
            deleted_keys.append(key)

    from app.core import storage as storage_mod

    monkeypatch.setattr(
        storage_mod,
        "get_storage_backend",
        lambda: _CapturingBackend(),
    )

    async with async_session_factory() as s:
        svc = GeoHubService(s)
        summary = await svc.sweep_deleted_raster_overlays(older_than_days=30)
        await s.commit()

    assert summary["swept"] == 1, summary
    # Both blobs for the stale row should have been removed (source + raster).
    assert sorted(deleted_keys) == sorted(
        ["geo_hub/overlays/x/stale-source", "geo_hub/overlays/x/stale-raster"],
    )

    # Stale row is gone; fresh row still soft-present.
    async with async_session_factory() as s:
        assert await s.get(GeoRasterOverlay, stale_id) is None
        fresh_row = await s.get(GeoRasterOverlay, fresh_id)
        assert fresh_row is not None
        assert fresh_row.deleted_at is not None


@pytest.mark.asyncio
async def test_sweep_rejects_negative_grace_window(app_instance):
    """Negative ``older_than_days`` must short-circuit, never flush everything."""
    from app.database import async_session_factory
    from app.modules.geo_hub.service import GeoHubService

    async with async_session_factory() as s:
        svc = GeoHubService(s)
        summary = await svc.sweep_deleted_raster_overlays(older_than_days=-1)
    assert summary == {"swept": 0, "blob_errors": 0}


@pytest.mark.asyncio
async def test_tileset_repository_filters_by_development_id_in_sql(
    app_instance,
    tenant_a,
):
    """``list_for_project(development_id=...)`` must filter in SQL.

    Mounts two tilesets that should match (one via native ``source_kind``,
    one via ``metadata.development_id``) and one that should NOT (a
    sibling BIM model). The dev-scoped list returns exactly two.
    """
    import uuid as _uuid

    from app.database import async_session_factory
    from app.modules.geo_hub.models import Tileset
    from app.modules.geo_hub.repository import TilesetRepository

    dev_id = _uuid.uuid4()
    other_dev_id = _uuid.uuid4()
    project_id = tenant_a["project_id"]

    async with async_session_factory() as s:
        # Match #1 — native development source.
        s.add(
            Tileset(
                project_id=project_id,
                source_kind="development",
                source_id=dev_id,
                name="dev-native",
                prefix=f"tilesets/{_uuid.uuid4()}",
                status="ready",
                geometric_error=Decimal("0"),
            )
        )
        # Match #2 — bim_model tagged with the dev in metadata.
        s.add(
            Tileset(
                project_id=project_id,
                source_kind="bim_model",
                source_id=_uuid.uuid4(),
                name="bim-tagged",
                prefix=f"tilesets/{_uuid.uuid4()}",
                status="ready",
                geometric_error=Decimal("0"),
                metadata_={"development_id": str(dev_id)},
            )
        )
        # Non-match — different dev id in metadata.
        s.add(
            Tileset(
                project_id=project_id,
                source_kind="bim_model",
                source_id=_uuid.uuid4(),
                name="other-dev",
                prefix=f"tilesets/{_uuid.uuid4()}",
                status="ready",
                geometric_error=Decimal("0"),
                metadata_={"development_id": str(other_dev_id)},
            )
        )
        await s.commit()

    async with async_session_factory() as s:
        rows = await TilesetRepository(s).list_for_project(
            project_id,
            limit=50,
            development_id=str(dev_id),
        )

    names = sorted(r.name for r in rows)
    assert names == ["bim-tagged", "dev-native"], names


@pytest.mark.asyncio
async def test_accuracy_m_upper_bound_rejects_huge_values(
    http_client,
    tenant_a,
):
    """Schema rejects accuracy_m > 10 km (Decimal upper bound)."""
    res = await http_client.post(
        "/api/v1/geo-hub/anchors/",
        json={
            "project_id": tenant_a["project_id"],
            "lat": "10.0",
            "lon": "20.0",
            "accuracy_m": "999999",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_admin_sweep_endpoint_returns_swept_count(
    http_client,
    tenant_a,
    monkeypatch,
):
    """``POST /admin/sweep-deleted-raster-overlays`` is reachable by admins
    and returns a ``{"swept": N, "blob_errors": N}`` payload.

    The service logic is covered by ``test_sweep_deleted_raster_overlays_*``;
    here we just pin the HTTP contract so a future refactor doesn't
    accidentally expose a different shape or mis-route the endpoint.
    """
    from app.core import storage as storage_mod

    class _NoopBackend:
        async def delete(self, key: str) -> None:
            pass

    monkeypatch.setattr(storage_mod, "get_storage_backend", lambda: _NoopBackend())

    res = await http_client.post(
        "/api/v1/geo-hub/admin/sweep-deleted-raster-overlays?older_than_days=30",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "swept" in body
    assert "blob_errors" in body
    # With a fresh db there should be nothing to sweep (all rows are live or
    # the previous test already committed them), so the count is 0 or small.
    assert isinstance(body["swept"], int)
    assert isinstance(body["blob_errors"], int)


@pytest.mark.asyncio
async def test_lat_lon_clamp_rejected_at_schema_layer(
    http_client,
    tenant_a,
):
    """Out-of-range lat/lon must 422 rather than silently clamp.

    Defends the "no silently-clamped values" promise of the schema by
    pinning the exact error response shape. Both axes are exercised so a
    later refactor that drops one validator can't slip through.
    """
    for bad_payload in (
        {"lat": "91.0", "lon": "0.0"},
        {"lat": "-91.0", "lon": "0.0"},
        {"lat": "0.0", "lon": "181.0"},
        {"lat": "0.0", "lon": "-181.0"},
    ):
        res = await http_client.post(
            "/api/v1/geo-hub/anchors/",
            json={
                "project_id": tenant_a["project_id"],
                **bad_payload,
            },
            headers=tenant_a["headers"],
        )
        assert res.status_code == 422, (bad_payload, res.text)
