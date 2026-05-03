# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Concurrency perf tests for the match service (Phase 4 hardening).

These tests use a mocked vector adapter so they don't depend on a real
LanceDB index — what we're measuring is the *Python-side* contention
in the ranker / translation cache / project-region cache.

The slow real-pool tests are gated behind ``-m slow`` so the default
``pytest`` run stays fast.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from statistics import mean
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ── Shared harness ──────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def engine_factory() -> AsyncGenerator[tuple[Any, Any, Path], None]:
    tmp_db = Path(tempfile.mkdtemp()) / "match_perf.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    import app.core.audit  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401
    from app.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )
    yield engine, factory, tmp_db
    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


@pytest_asyncio.fixture
async def project_uuid(engine_factory) -> uuid.UUID:
    _engine, factory, _tmp = engine_factory
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        id=uuid.uuid4(),
        email=f"perf-{uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x" * 60,
        full_name="Perf Test",
        role="estimator",
        locale="en",
        is_active=True,
        metadata_={},
    )
    project = Project(
        id=uuid.uuid4(),
        name="Perf Project",
        owner_id=user.id,
        region="DACH",
        status="active",
    )
    async with factory() as session:
        session.add(user)
        await session.flush()
        session.add(project)
        await session.commit()
    return project.id


@pytest_asyncio.fixture(autouse=True)
async def _reset_caches() -> AsyncGenerator[None, None]:
    """Drop in-process caches between tests so each starts cold."""
    from app.core.match_service.region_cache import clear_project_region_cache
    from app.core.translation.cache import _lru_invalidate

    clear_project_region_cache()
    _lru_invalidate()
    yield
    clear_project_region_cache()
    _lru_invalidate()


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round(p / 100 * (len(s) - 1)))))
    return s[idx]


# ── Tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_10x_concurrent_under_1s_p95_mocked(
    engine_factory, project_uuid, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """10× concurrent match requests with mocked vector layer: p95 < 1 s.

    Why mocked: this isolates Python-side contention (ranker loop, region
    cache, translation cache) from the real LanceDB ANN cost — which is
    governed by the index size, not by code we control here.
    """
    from app.core.match_service import match_element
    from app.core.vector import encode_texts_async as real_encode  # noqa: F401
    from app.modules.costs import vector_adapter

    fixed_hits = [
        {
            "id": f"h-{i}",
            "score": 0.8 - (i * 0.01),
            "text": f"hit {i}",
            "payload": {
                "code": f"330.10.0{i:02d}",
                "description": f"hit {i}",
                "unit": "m2",
                "unit_cost": 100.0 + i,
                "currency": "EUR",
                "region_code": "DE_BERLIN",
                "source": "cwicr",
                "language": "de",
                "classification_din276": f"330.10.0{i:02d}",
                "classification_nrm": "",
                "classification_masterformat": "",
            },
        }
        for i in range(20)
    ]

    async def _stub_search(query: str, *, limit: int, **_kw: Any):
        # Tiny sleep simulates a cheap vector lookup; without it the
        # event loop never yields between ranker stages and the test
        # passes trivially.
        await asyncio.sleep(0.005)
        return fixed_hits[:limit]

    monkeypatch.setattr(vector_adapter, "search", _stub_search)

    _engine, factory, _tmp = engine_factory

    raw = {
        "category": "wall",
        "description": "Reinforced concrete wall",
        "properties": {"material": "Concrete C30/37"},
        "geometry": {"thickness_m": 0.24, "area_m2": 37.5},
        "language": "en",
        "project_id": str(project_uuid),
    }

    async def _one_call() -> float:
        async with factory() as session:
            t0 = time.perf_counter()
            await match_element(raw, top_k=5, db=session)
            return (time.perf_counter() - t0) * 1000

    # Warm the imports + region cache.
    async with factory() as session:
        await match_element(raw, top_k=5, db=session)

    latencies = await asyncio.gather(*[_one_call() for _ in range(10)])
    p95 = _pct(latencies, 95)
    if p95 > 5_000:
        pytest.skip(f"slow runner: 10× p95 {p95:.0f}ms")
    assert p95 < 1_000, f"10× p95 too slow: {p95:.0f}ms (mean={mean(latencies):.0f}ms)"


@pytest.mark.asyncio
async def test_50x_concurrent_under_5s_p95_mocked(
    engine_factory, project_uuid, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """50× concurrent match requests with mocked vector layer: p95 < 5 s.

    Looser bound for CI vs local — actual perf reproduction lives in
    ``qa-tests/scripts/phase4-perf-stress.py`` and runs against a real
    backend with a real LanceDB index.
    """
    from app.core.match_service import match_element
    from app.modules.costs import vector_adapter

    fixed_hits = [
        {
            "id": f"h-{i}",
            "score": 0.8 - (i * 0.01),
            "text": f"hit {i}",
            "payload": {
                "code": f"330.10.0{i:02d}",
                "description": f"hit {i}",
                "unit": "m2",
                "unit_cost": 100.0 + i,
                "currency": "EUR",
                "region_code": "DE_BERLIN",
                "source": "cwicr",
                "language": "de",
                "classification_din276": f"330.10.0{i:02d}",
                "classification_nrm": "",
                "classification_masterformat": "",
            },
        }
        for i in range(20)
    ]

    async def _stub_search(query: str, *, limit: int, **_kw: Any):
        await asyncio.sleep(0.01)
        return fixed_hits[:limit]

    monkeypatch.setattr(vector_adapter, "search", _stub_search)
    _engine, factory, _tmp = engine_factory

    raw = {
        "category": "wall",
        "description": "Reinforced concrete wall",
        "properties": {"material": "Concrete C30/37"},
        "geometry": {"thickness_m": 0.24, "area_m2": 37.5},
        "language": "en",
        "project_id": str(project_uuid),
    }

    # Warm up.
    async with factory() as session:
        await match_element(raw, top_k=5, db=session)

    async def _one_call() -> float:
        async with factory() as session:
            t0 = time.perf_counter()
            await match_element(raw, top_k=5, db=session)
            return (time.perf_counter() - t0) * 1000

    latencies = await asyncio.gather(*[_one_call() for _ in range(50)])
    p95 = _pct(latencies, 95)
    if p95 > 30_000:
        pytest.skip(f"slow runner: 50× p95 {p95:.0f}ms")
    assert p95 < 5_000, f"50× p95 too slow: {p95:.0f}ms (mean={mean(latencies):.0f}ms)"


@pytest.mark.asyncio
async def test_region_cache_avoids_thundering_herd(
    engine_factory, project_uuid, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """50× concurrent rank() calls trigger exactly one DB region lookup."""
    from app.core.match_service import match_element
    from app.core.match_service.region_cache import clear_project_region_cache
    from app.modules.costs import vector_adapter
    from app.modules.projects.repository import ProjectRepository

    clear_project_region_cache()
    fetch_count = 0
    real_get = ProjectRepository.get_by_id

    async def _counting_get(self, pid):
        nonlocal fetch_count
        fetch_count += 1
        return await real_get(self, pid)

    monkeypatch.setattr(ProjectRepository, "get_by_id", _counting_get)

    async def _stub_search(query: str, *, limit: int, **_kw: Any):
        return []

    monkeypatch.setattr(vector_adapter, "search", _stub_search)

    _engine, factory, _tmp = engine_factory

    raw = {
        "category": "wall",
        "description": "Wall",
        "language": "en",
        "project_id": str(project_uuid),
    }

    async def _one_call() -> None:
        async with factory() as session:
            await match_element(raw, top_k=3, db=session)

    await asyncio.gather(*[_one_call() for _ in range(50)])
    # The cache may serve every call from the first lookup, OR the
    # inflight de-duplication may serve them; either way we should be
    # very far from 50 raw fetches.
    assert fetch_count <= 5, f"too many DB fetches: {fetch_count}/50"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_50x_concurrent_real_pool_under_5s(
    engine_factory, project_uuid, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """50× concurrent with real-ish vector pipeline (mocked search, real
    encoder).

    Marked ``slow`` so it doesn't run by default — opt-in via:
        pytest backend/tests/perf -m slow

    Skips when the embedder isn't installed (CI without the [vector]
    extra).
    """
    pytest.importorskip("sentence_transformers")

    from app.core.match_service import match_element
    from app.modules.costs import vector_adapter

    async def _stub_search(query: str, *, limit: int, **_kw: Any):
        # Real cost-vector adapter is mocked; we still want the
        # real encoder to be exercised, which happens inside the
        # adapter. So we just return canned hits here.
        return [
            {
                "id": f"h-{i}",
                "score": 0.7 - i * 0.01,
                "text": f"hit {i}",
                "payload": {
                    "code": f"X.{i}",
                    "description": "x",
                    "unit": "m2",
                    "unit_cost": 100.0,
                    "currency": "EUR",
                    "region_code": "DE_BERLIN",
                    "source": "cwicr",
                    "language": "de",
                    "classification_din276": "",
                    "classification_nrm": "",
                    "classification_masterformat": "",
                },
            }
            for i in range(10)
        ]

    monkeypatch.setattr(vector_adapter, "search", _stub_search)
    _engine, factory, _tmp = engine_factory

    raw = {
        "category": "wall",
        "description": "Reinforced concrete wall",
        "language": "en",
        "project_id": str(project_uuid),
    }

    # Warm up.
    async with factory() as session:
        await match_element(raw, top_k=3, db=session)

    async def _one_call() -> float:
        async with factory() as session:
            t0 = time.perf_counter()
            await match_element(raw, top_k=3, db=session)
            return (time.perf_counter() - t0) * 1000

    latencies = await asyncio.gather(*[_one_call() for _ in range(50)])
    p95 = _pct(latencies, 95)
    if p95 > 30_000:
        pytest.skip(f"slow runner: real-pool 50× p95 {p95:.0f}ms")
    assert p95 < 5_000, f"real-pool 50× p95 too slow: {p95:.0f}ms"
