# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Catalogue status distinguishes a failed probe from an empty server."""

import httpx
import pytest

from app.modules.costs import router
from app.modules.costs.qdrant_snapshot_loader import server_collections


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["connect", "http", "json"])
async def test_failed_probe_is_not_reachable(monkeypatch, tmp_path, failure):
    def get(url, **kwargs):
        request = httpx.Request("GET", url)
        if failure == "connect":
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(503 if failure == "http" else 200, text="invalid", request=request)

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(router, "_v3_qdrant_url", lambda: "http://qdrant.invalid")
    monkeypatch.setattr(router, "_v3_snapshot_cache_path", lambda region: tmp_path / region)
    result = await router.list_v3_catalogues()
    assert result["server"]["reachable"] is False
    assert result["server"]["total_collections"] == 0
    assert not any(c["install_status"] == "loaded" for c in result["catalogues"])
    # Snapshot CLI/install callers retain their best-effort default.
    assert server_collections(qdrant_url="http://qdrant.invalid") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("names", [[], ["cwicr_en_v3"]])
async def test_successful_probe_is_reachable_even_when_empty(monkeypatch, tmp_path, names):
    def get(url, **kwargs):
        return httpx.Response(
            200,
            json={"result": {"collections": [{"name": name} for name in names]}},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(router, "_v3_qdrant_url", lambda: "http://qdrant.invalid")
    monkeypatch.setattr(router, "_v3_snapshot_cache_path", lambda region: tmp_path / region)
    result = await router.list_v3_catalogues()
    assert result["server"]["reachable"] is True
    assert result["server"]["v3_collections"] == names
    assert result["server"]["total_collections"] == len(names)
    assert bool([c for c in result["catalogues"] if c["install_status"] == "loaded"]) == bool(names)
