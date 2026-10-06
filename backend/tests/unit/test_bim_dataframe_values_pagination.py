"""Distinct value paging keeps a complete count and does not lose late options."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user_id
from app.modules.bim_hub import dataframe_store as ds
from app.modules.bim_hub import router as routes


@pytest.mark.parametrize("engine", ["duckdb", "pyarrow"])
def test_pages_cover_every_value_with_stable_ties_and_total_beyond_last_page(tmp_path, monkeypatch, engine):
    if engine == "pyarrow":
        monkeypatch.setitem(sys.modules, "duckdb", None)
    rows = [{"Width/Height": f"v{i:03}"} for i in range(205)]
    rows += [{"Width/Height": "v200"}, {"Width/Height": ""}, {"Width/Height": None}]
    ds.write_dataframe("p", "m", rows, data_root=tmp_path)
    pages = [ds.column_value_counts_page("p", "m", "Width/Height", 100, tmp_path, offset=o) for o in (0, 100, 200, 300)]
    assert [len(p["items"]) for p in pages] == [100, 100, 5, 0]
    assert all(p["total"] == 205 for p in pages)
    assert [p["offset"] for p in pages] == [0, 100, 200, 300]
    assert all(p["limit"] == 100 for p in pages)
    items = [r for p in pages for r in p["items"]]
    assert items[0] == {"value": "v200", "count": 2}
    assert len({r["value"] for r in items}) == 205


@pytest.fixture
def app(monkeypatch):
    app = FastAPI()
    app.get("/models/{model_id}/dataframe/values/")(routes.get_column_values_by_query)
    app.dependency_overrides[get_current_user_id] = lambda: "user"
    app.dependency_overrides[routes._get_service] = lambda: None
    monkeypatch.setattr(routes, "_verify_model_access", AsyncMock(return_value=SimpleNamespace(project_id="p")))
    return app


@pytest.mark.asyncio
async def test_http_envelope_preserves_slash_column_and_counts_all_values(app, tmp_path, monkeypatch):
    model_id = uuid4()
    ds.write_dataframe("p", str(model_id), [{"Width/Height": str(i)} for i in range(3)], data_root=tmp_path)
    real = ds.column_value_counts_page
    monkeypatch.setattr(ds, "column_value_counts_page", lambda *a, **kw: real(*a, data_root=tmp_path, **kw))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/models/{model_id}/dataframe/values/", params={"column": "Width/Height", "offset": 2, "limit": 2}
        )
    assert response.status_code == 200
    assert response.json() == {"items": [{"value": "2", "count": 1}], "total": 3, "offset": 2, "limit": 2}


@pytest.mark.asyncio
@pytest.mark.parametrize("paging", [{"limit": 0}, {"limit": -1}, {"limit": 1001}, {"offset": -1}, {"offset": "oops"}])
async def test_http_rejects_invalid_paging_before_querying(app, monkeypatch, paging):
    def must_not_query(*args, **kwargs):
        raise AssertionError("invalid request reached the store")

    monkeypatch.setattr(ds, "column_value_counts_page", must_not_query)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/models/{uuid4()}/dataframe/values/", params={"column": "Width/Height", **paging})
    assert response.status_code == 422
