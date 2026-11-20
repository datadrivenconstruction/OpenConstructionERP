"""KPI freshness must stay O(1) and bounded, whatever the project count."""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest
from fastapi import HTTPException

from app.modules.bi_dashboards import events, router


def test_watermark_map_is_capped_and_lookup_does_not_scan(monkeypatch):
    monkeypatch.setattr(events, "_KPI_WATERMARKS", {})
    monkeypatch.setattr(events, "_MAX_WATERMARKS", 200)
    ids = [str(uuid.uuid4()) for _ in range(5000)]
    for pid in ids:
        events._bump_watermark(pid, "upstream_event", "x")
    assert len(events._KPI_WATERMARKS) <= 201  # cap plus the global key
    assert events._GLOBAL_KEY in events._KPI_WATERMARKS
    start = time.perf_counter()
    for pid in ids:
        events.get_kpi_freshness(pid)
    assert time.perf_counter() - start < 1.0
    assert events.get_kpi_freshness(ids[-1])["invalidated_at"] is not None


def test_freshness_unknown_project_falls_back_to_global(monkeypatch):
    monkeypatch.setattr(events, "_KPI_WATERMARKS", {})
    events._bump_watermark(None, "r", "e")
    assert events.get_kpi_freshness(str(uuid.uuid4()))["source_event"] == "e"


@pytest.mark.asyncio
async def test_stalled_access_check_returns_503_quickly(monkeypatch):
    async def _hang(*_a, **_k):
        await asyncio.sleep(60)

    monkeypatch.setattr(router, "verify_project_access", _hang)
    monkeypatch.setattr(router, "_FRESHNESS_ACCESS_TIMEOUT_S", 0.05)
    start = time.perf_counter()
    with pytest.raises(HTTPException) as exc:
        await router.kpi_freshness("u", None, uuid.uuid4())  # type: ignore[arg-type]
    assert exc.value.status_code == 503
    assert exc.value.headers == {"Retry-After": "5"}
    assert time.perf_counter() - start < 2.0
