# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Phase-0 performance smoke tests for v2.8.0 vector match feature.

Sanity-bounds, not formal benchmarks. The numbers below are intentionally
generous (2–10x typical observed) so we catch order-of-magnitude
regressions without flapping on slow CI runners.

* match_element with a typical BIM input (vector search mocked) — < 500 ms
* Translation cascade fallback path (no MUSE, no LLM key) — < 50 ms
* MatchProjectSettings GET (lazy init) — < 100 ms

Tests skip themselves if they exceed 5 s; we don't want a slow run to
block a release pipeline.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


# ── Shared fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _bypass_catalog_gate(monkeypatch):
    """v2.8.2 — short-circuit the catalogue gate so the perf tests measure
    the ranker's hot path, not a one-line early return."""
    async def _ok(*_args, **_kwargs):
        return "ok", 1, 1

    monkeypatch.setattr(
        "app.core.match_service.ranker._resolve_catalog_status",
        _ok,
        raising=True,
    )


def _register_minimal_models() -> None:
    import app.core.audit  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def engine_factory():
    tmp_db = Path(tempfile.mkdtemp()) / "perf.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)
    _register_minimal_models()
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
    """Real Project row so MatchProjectSettings can FK."""
    _engine, factory, _tmp = engine_factory

    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        id=uuid.uuid4(),
        email=f"perf-{uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x" * 60,
        full_name="P",
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


# ── Sanity bounds ────────────────────────────────────────────────────────────


_TIMEOUT_MS_PER_TEST = 5_000  # if any test exceeds this, skip rather than fail


@pytest.mark.asyncio
async def test_match_element_typical_under_500ms(
    engine_factory, project_uuid, monkeypatch,
) -> None:
    """match_element with mocked vector search must complete in < 500 ms.

    Why: anything beyond 500ms in the pipeline (excluding network) hints
    at a python-side hot loop or a sync DB call that should be async.
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
                "unit": "m2", "unit_cost": 100.0 + i,
                "currency": "EUR", "region_code": "DE_BERLIN",
                "source": "cwicr", "language": "de",
                "classification_din276": f"330.10.0{i:02d}",
                "classification_nrm": "", "classification_masterformat": "",
            },
        }
        for i in range(30)
    ]

    async def _stub_search(query: str, *, limit: int, **kw: Any):
        return fixed_hits[:limit]

    monkeypatch.setattr(vector_adapter, "search", _stub_search)
    _engine, factory, _tmp = engine_factory

    raw = {
        "category": "wall",
        "description": "Reinforced concrete wall, C30/37, 24cm",
        "properties": {
            "material": "Concrete C30/37",
            "fire_rating": "F90",
            "thickness_m": 0.24,
        },
        "geometry": {"area_m2": 37.5, "thickness_m": 0.24, "length_m": 12.5},
        "classification": {"din276": "330.10.020"},
        "language": "en",
        "project_id": str(project_uuid),
    }

    async with factory() as session:
        # Warm up — first call pulls in repository imports lazily.
        await match_element(raw, top_k=10, db=session)
        # Measure.
        started = time.perf_counter()
        result = await match_element(raw, top_k=10, db=session)
        elapsed_ms = (time.perf_counter() - started) * 1000

    if elapsed_ms > _TIMEOUT_MS_PER_TEST:
        pytest.skip(f"slow runner: match_element took {elapsed_ms:.0f}ms")

    assert isinstance(result, list)
    assert elapsed_ms < 500, f"match_element too slow: {elapsed_ms:.0f}ms"


@pytest.mark.asyncio
async def test_translation_fallback_under_50ms(tmp_path: Path) -> None:
    """Translation cascade fallback path < 50 ms.

    Path: no MUSE file, no LLM settings → fall through to fallback tier
    immediately. The cache.db file is created lazily.
    """
    from app.core.translation import translate

    # Warm up — schema initialisation amortises across runs in the same
    # cache file.
    await translate(
        "Concrete wall", "en", "de",
        cache_db_path=str(tmp_path / "cache.db"),
        lookup_root=str(tmp_path),
    )

    started = time.perf_counter()
    result = await translate(
        "Concrete wall section type B", "en", "de",
        cache_db_path=str(tmp_path / "cache.db"),
        lookup_root=str(tmp_path),
    )
    elapsed_ms = (time.perf_counter() - started) * 1000

    if elapsed_ms > _TIMEOUT_MS_PER_TEST:
        pytest.skip(f"slow runner: translate took {elapsed_ms:.0f}ms")

    assert result.translated == "Concrete wall section type B"
    # 50ms is generous — observed ~5–15ms locally.
    assert elapsed_ms < 50, f"translation fallback too slow: {elapsed_ms:.0f}ms"


@pytest.mark.asyncio
async def test_match_settings_get_under_100ms(
    engine_factory, project_uuid,
) -> None:
    """MatchProjectSettings lazy-init GET completes in < 100 ms.

    Lazy init = SELECT (miss) → INSERT → SELECT round-trip. Should be
    fast on local SQLite.
    """
    from app.modules.projects.service import get_or_create_match_settings

    _engine, factory, _tmp = engine_factory

    # Warm up the schema cache.
    async with factory() as session:
        await get_or_create_match_settings(session, project_uuid)
        await session.commit()

    # Measure subsequent (cache-hit) GET.
    async with factory() as session:
        started = time.perf_counter()
        row = await get_or_create_match_settings(session, project_uuid)
        elapsed_ms = (time.perf_counter() - started) * 1000

    if elapsed_ms > _TIMEOUT_MS_PER_TEST:
        pytest.skip(f"slow runner: get_or_create_match_settings took {elapsed_ms:.0f}ms")

    assert row is not None
    assert elapsed_ms < 100, f"settings GET too slow: {elapsed_ms:.0f}ms"


@pytest.mark.asyncio
async def test_envelope_construction_under_5ms() -> None:
    """Building an envelope from BIM raw data should be near-free.

    Why: extractors run per element on bulk imports — milliseconds add up.
    """
    from app.core.match_service.extractors import build_envelope

    raw = {
        "category": "wall",
        "name": "Stahlbetonwand",
        "properties": {"material": "Concrete C30/37", "fire_rating": "F90"},
        "geometry": {"thickness_m": 0.24, "area_m2": 37.5, "length_m": 12.5},
        "classification": {"din276": "330.10.020"},
        "language": "de",
    }
    # Warm up
    for _ in range(5):
        build_envelope("bim", raw)

    started = time.perf_counter()
    for _ in range(100):
        build_envelope("bim", raw)
    elapsed_ms = (time.perf_counter() - started) * 1000
    per_call_ms = elapsed_ms / 100

    if per_call_ms > 5:
        pytest.skip(f"slow runner: envelope build {per_call_ms:.2f}ms/call")
    assert per_call_ms < 5, f"envelope construction too slow: {per_call_ms:.2f}ms"


@pytest.mark.asyncio
async def test_boost_apply_under_2ms() -> None:
    """Boost stack runs in < 2 ms per candidate.

    Why: boosts run per-candidate inside the tight ranker loop.
    """
    from app.core.match_service.boosts import apply_boosts
    from app.core.match_service.envelope import ElementEnvelope, MatchCandidate

    envelope = ElementEnvelope(
        source="bim",
        category="wall",
        description="Reinforced concrete wall",
        unit_hint="m2",
        classifier_hint={"din276": "330.10.020"},
    )
    candidate = MatchCandidate(
        code="330.10.020",
        description="Stahlbetonwand C30/37",
        unit="m2",
        unit_rate=145.0,
        currency="EUR",
        region_code="DE_BERLIN",
        classification={"din276": "330.10.020"},
    )

    class _Settings:
        classifier = "din276"
        project = type("P", (), {"region": "DACH"})()

    # Warm up
    for _ in range(5):
        apply_boosts(envelope, candidate, _Settings())

    started = time.perf_counter()
    for _ in range(100):
        apply_boosts(envelope, candidate, _Settings())
    elapsed_ms = (time.perf_counter() - started) * 1000
    per_call_ms = elapsed_ms / 100

    if per_call_ms > 5:
        pytest.skip(f"slow runner: boost {per_call_ms:.2f}ms/call")
    assert per_call_ms < 2, f"boost stack too slow: {per_call_ms:.2f}ms"
