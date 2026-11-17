# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
#
# Resource catalogue search filters in SQL first and ranks only that subset by
# vector similarity; without a usable vector index it falls back to text search (#563).

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.core import vector, vector_index
from app.modules.catalog import service as catalog_service
from app.modules.catalog.schemas import CatalogSearchQuery
from app.modules.catalog.service import CatalogResourceService
from app.modules.catalog.vector_adapter import catalog_resource_adapter

A, B, C = (str(uuid.uuid4()) for _ in range(3))


class _Repo:
    def __init__(self, ids: list[str]) -> None:
        self.ids = ids
        self.filters: dict[str, Any] = {}
        self.text_calls = 0

    async def ids_matching(self, **filters: Any) -> list[str]:
        self.filters = filters
        return self.ids

    async def get_active_by_ids(self, ids: list[str]) -> dict[str, Any]:
        return {i: SimpleNamespace(id=i) for i in ids if i != C}

    async def search(self, **_kw: Any):  # noqa: ANN201
        self.text_calls += 1
        return [SimpleNamespace(id="text")], 1


def _service(repo: _Repo) -> CatalogResourceService:
    svc = CatalogResourceService.__new__(CatalogResourceService)
    svc.repo = repo
    return svc


def _hits(*ids: str) -> list[Any]:
    return [SimpleNamespace(id=i) for i in ids]


@pytest.fixture
def store(monkeypatch):
    calls: list[dict[str, Any]] = []

    def install(hits: list[Any]) -> list[dict[str, Any]]:
        async def fake(adapter, query, *, limit=10, ids=None, **_kw):  # noqa: ANN001
            calls.append({"limit": limit, "ids": ids, "adapter": adapter})
            return hits

        monkeypatch.setattr(vector_index, "search_collection", fake)
        return calls

    return install


@pytest.mark.asyncio
async def test_filters_prefilter_then_rank(store):
    calls = store(_hits(B, A))
    repo = _Repo([A, B])
    q = CatalogSearchQuery(q="steel", category="Steel", region="DE", semantic=True, limit=10)

    items, total, mode = await _service(repo).search_resources_ranked(q)

    assert mode == "semantic" and total == 2
    assert [i.id for i in items] == [B, A]
    assert repo.filters["category"] == "Steel" and repo.filters["region"] == "DE"
    assert calls[0]["ids"] == [A, B] and calls[0]["adapter"] is catalog_resource_adapter
    assert repo.text_calls == 0


@pytest.mark.asyncio
async def test_page_slices_the_ranking(store):
    store(_hits(A, B, C))
    items, total, _ = await _service(_Repo([A, B, C])).search_resources_ranked(
        CatalogSearchQuery(q="steel", semantic=True, limit=1, offset=1)
    )
    assert [i.id for i in items] == [B] and total == 3


@pytest.mark.asyncio
async def test_no_vector_hits_falls_back_to_text(store):
    store([])
    repo = _Repo([A])
    items, _, mode = await _service(repo).search_resources_ranked(CatalogSearchQuery(q="steel", semantic=True))
    assert mode == "text" and repo.text_calls == 1 and items[0].id == "text"


@pytest.mark.asyncio
async def test_empty_subset_never_asks_the_vector_store(store):
    calls = store(_hits(A))
    _, _, mode = await _service(_Repo([])).search_resources_ranked(CatalogSearchQuery(q="steel", semantic=True))
    assert calls == [] and mode == "text"


@pytest.mark.asyncio
async def test_store_failure_falls_back_to_text(monkeypatch):
    async def boom(*_a, **_k):  # noqa: ANN002, ANN003
        raise RuntimeError("no store")

    monkeypatch.setattr(vector_index, "search_collection", boom)
    repo = _Repo([A])
    _, _, mode = await _service(repo).search_resources_ranked(CatalogSearchQuery(q="steel", semantic=True))
    assert mode == "text" and repo.text_calls == 1


@pytest.mark.asyncio
async def test_plain_search_and_short_query_stay_sql(store):
    calls = store(_hits(A))
    repo = _Repo([A])
    for q in (CatalogSearchQuery(q="steel"), CatalogSearchQuery(q="s", semantic=True)):
        _, _, mode = await _service(repo).search_resources_ranked(q)
        assert mode == "text"
    assert calls == []


@pytest.mark.asyncio
async def test_large_subset_ranks_wider_window_and_keeps_subset(store, monkeypatch):
    calls = store(_hits(C, B, A))
    monkeypatch.setattr(catalog_service, "VECTOR_PREFILTER_MAX_IDS", 0)
    items, total, _ = await _service(_Repo([A, B])).search_resources_ranked(
        CatalogSearchQuery(q="steel", semantic=True, limit=5)
    )
    assert calls[0]["ids"] is None and calls[0]["limit"] > 5
    assert [i.id for i in items] == [B, A] and total == 2


def test_lancedb_id_restriction_is_a_uuid_checked_predicate():
    assert vector._ids_where(None) is None
    assert vector._ids_where([A]) == f"id IN ('{A}')"
    assert vector._ids_where(["x' OR 1=1 --"]) == "1 = 0"


def test_vector_search_with_empty_ids_matches_nothing():
    assert vector.vector_search_collection("oe_catalog_resources", [0.1], ids=[]) == []
