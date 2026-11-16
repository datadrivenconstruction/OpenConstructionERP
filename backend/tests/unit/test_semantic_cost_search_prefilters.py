# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
#
# Semantic cost search narrows by region, catalogue and category in SQL first
# and ranks only that subset by vector similarity, so a filter can never be
# emptied by nearer neighbours from other categories taking the top-k (#562).

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cost_scope, vector
from app.modules.costs import router as costs_router
from app.modules.costs.models import CostItem
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _seed(s: AsyncSession) -> dict[str, str]:
    region = f"ZZPRE{uuid.uuid4().hex[:6].upper()}"
    rows = {
        "concrete": CostItem(
            code="ZZPRE.C", description="Concrete wall C30/37", classification={"collection": "Concrete"}
        ),
        "masonry": CostItem(code="ZZPRE.M", description="Brick wall", classification={"collection": "Masonry"}),
        "elsewhere": CostItem(code="ZZPRE.E", description="Concrete wall", classification={"collection": "Concrete"}),
    }
    for key, item in rows.items():
        item.id = uuid.uuid4()
        item.unit = "m2"
        item.rate = "10"
        item.currency = "EUR"
        item.is_active = True
        item.region = region if key != "elsewhere" else f"{region}X"
    s.add_all(rows.values())
    await s.flush()
    return {"region": region, **{k: str(v.id) for k, v in rows.items()}}


class _Recorder:
    def __init__(self, all_hits: list[dict[str, Any]]) -> None:
        self.all_hits = all_hits
        self.calls: list[dict[str, Any]] = []

    def __call__(self, _vector, region=None, limit=10, ids=None):  # noqa: ANN001
        self.calls.append({"region": region, "limit": limit, "ids": ids})
        hits = [h for h in self.all_hits if region is None or h["region"] == region]
        if ids is not None:
            hits = [h for h in hits if h["id"] in set(ids)]
        return hits[:limit]


@pytest.fixture
def stack(monkeypatch):
    monkeypatch.setattr(vector, "encode_texts", lambda texts: [[0.1, 0.2] for _ in texts])

    def install(hits: list[dict[str, Any]]) -> _Recorder:
        recorder = _Recorder(hits)
        monkeypatch.setattr(vector, "vector_search", recorder)
        return recorder

    return install


def _hits(w: dict[str, str]) -> list[dict[str, Any]]:
    # Ranked as a pure vector search would: the masonry row is nearest.
    return [
        {"id": w["masonry"], "region": w["region"]},
        {"id": w["concrete"], "region": w["region"]},
        {"id": w["elsewhere"], "region": f"{w['region']}X"},
    ]


async def _search(s: AsyncSession, **kw: Any) -> list[dict]:
    with cost_scope.system_scope():
        return await costs_router.semantic_search(session=s, _user_id="reader", q="wall", limit=1, **kw)


@pytest.mark.asyncio
async def test_category_is_applied_before_ranking(session, stack):
    w = await _seed(session)
    recorder = stack(_hits(w))

    hits = await _search(session, region=w["region"], category="Concrete")

    assert [h["id"] for h in hits] == [w["concrete"]]
    assert recorder.calls[0]["ids"] == [w["concrete"]]


@pytest.mark.asyncio
async def test_a_filter_with_no_rows_never_asks_the_vector_store(session, stack):
    w = await _seed(session)
    recorder = stack(_hits(w))

    assert await _search(session, region=w["region"], category="Roofing") == []
    assert recorder.calls == []


@pytest.mark.asyncio
async def test_region_only_keeps_the_plain_vector_call(session, stack):
    w = await _seed(session)
    recorder = stack(_hits(w))

    hits = await _search(session, region=w["region"])

    assert [h["id"] for h in hits] == [w["masonry"]]
    assert recorder.calls[0]["ids"] is None


@pytest.mark.asyncio
async def test_a_large_subset_is_ranked_wider_then_narrowed(session, stack, monkeypatch):
    w = await _seed(session)
    recorder = stack(_hits(w))
    monkeypatch.setattr(costs_router, "_VECTOR_PREFILTER_MAX_IDS", 0)

    hits = await _search(session, region=w["region"], category="Concrete")

    assert [h["id"] for h in hits] == [w["concrete"]]
    assert recorder.calls[0]["ids"] is None
    assert recorder.calls[0]["limit"] > 1
