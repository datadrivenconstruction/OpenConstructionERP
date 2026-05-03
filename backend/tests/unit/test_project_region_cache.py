# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Unit tests for the per-project region TTL cache.

The cache lives in ``app.core.match_service.region_cache`` and exists
to amortise ``ProjectRepository.get_by_id`` calls that the ranker would
otherwise issue per match request.
"""

from __future__ import annotations

import asyncio
import tempfile
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.match_service import region_cache

# ── Minimal DB harness ──────────────────────────────────────────────────


@pytest_asyncio.fixture
async def engine_factory() -> AsyncGenerator[tuple[Any, Any, Path], None]:
    """Per-test SQLite + ORM metadata."""
    tmp_db = Path(tempfile.mkdtemp()) / "region_cache.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    # Force a coherent metadata snapshot (see conftest note).
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
async def project_with_region(
    engine_factory,
) -> tuple[uuid.UUID, str, Any]:
    """Create a real Project row so the cache layer can read it."""
    _engine, factory, _tmp = engine_factory

    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        id=uuid.uuid4(),
        email=f"rc-{uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x" * 60,
        full_name="Region Cache Test",
        role="estimator",
        locale="en",
        is_active=True,
        metadata_={},
    )
    project = Project(
        id=uuid.uuid4(),
        name="Region Project",
        owner_id=user.id,
        region="DACH",
        status="active",
    )
    async with factory() as session:
        session.add(user)
        await session.flush()
        session.add(project)
        await session.commit()
    return project.id, "DACH", factory


# ── Reset cache between tests ───────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    region_cache.clear_project_region_cache()
    yield
    region_cache.clear_project_region_cache()


# ── Tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_hit_returns_db_value(project_with_region) -> None:
    """First call reads DB; second call reads cache; both return same value."""
    project_id, expected_region, factory = project_with_region

    async with factory() as session:
        first = await region_cache.region_for(session, project_id)
    assert first == expected_region

    # A second call MUST come from cache — verify by passing a session
    # that would explode if touched (closed session).
    async with factory() as session:
        await session.close()  # closed; any DB call would raise
        second = await region_cache.region_for(session, project_id)
    assert second == expected_region


@pytest.mark.asyncio
async def test_cache_miss_falls_through_to_db(project_with_region) -> None:
    """Missing cache entry triggers a fresh DB read."""
    project_id, expected_region, factory = project_with_region
    region_cache.clear_project_region_cache()

    async with factory() as session:
        out = await region_cache.region_for(session, project_id)
    assert out == expected_region
    stats = region_cache.cache_stats()
    assert stats["entries"] == 1
    assert stats["fresh"] == 1


@pytest.mark.asyncio
async def test_unknown_project_returns_none(engine_factory) -> None:
    """Project that doesn't exist → cache stores None and returns None."""
    _engine, factory, _tmp = engine_factory
    bogus = uuid.uuid4()

    async with factory() as session:
        result = await region_cache.region_for(session, bogus)
    assert result is None
    # The miss is cached (as None) so a hot loop doesn't re-query.
    assert region_cache.cache_stats()["entries"] == 1


@pytest.mark.asyncio
async def test_ttl_eviction(project_with_region) -> None:
    """After TTL passes, the next call hits DB again."""
    project_id, expected_region, factory = project_with_region

    async with factory() as session:
        await region_cache.region_for(session, project_id, ttl_seconds=0.05)

    # Wait past the TTL.
    await asyncio.sleep(0.1)

    # Mutate the underlying row so a re-fetch returns a different value.
    async with factory() as session:
        from sqlalchemy import update

        from app.modules.projects.models import Project

        await session.execute(
            update(Project).where(Project.id == project_id).values(region="UK"),
        )
        await session.commit()

    async with factory() as session:
        new_region = await region_cache.region_for(session, project_id)
    assert new_region == "UK"


@pytest.mark.asyncio
async def test_concurrent_gets_share_one_db_fetch(
    project_with_region, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """50 concurrent gets on a cold cache key issue exactly one DB fetch."""
    project_id, expected_region, factory = project_with_region
    region_cache.clear_project_region_cache()

    fetch_count = 0

    from app.modules.projects.repository import ProjectRepository

    real_get = ProjectRepository.get_by_id

    async def _counting_get(self, pid):
        nonlocal fetch_count
        fetch_count += 1
        # Slow this down so all 50 tasks pile up before the first
        # finishes — without the inflight de-duplication every one of
        # them would issue its own fetch.
        await asyncio.sleep(0.05)
        return await real_get(self, pid)

    monkeypatch.setattr(ProjectRepository, "get_by_id", _counting_get, raising=True)

    async def _one_call() -> str | None:
        async with factory() as session:
            return await region_cache.region_for(session, project_id)

    results = await asyncio.gather(*[_one_call() for _ in range(50)])
    assert all(r == expected_region for r in results)
    assert fetch_count == 1, f"thundering herd: {fetch_count} DB fetches"


@pytest.mark.asyncio
async def test_clear_cache_per_project(project_with_region) -> None:
    """clear_project_region_cache(uuid) drops only that one entry."""
    project_id, _expected, factory = project_with_region
    other_id = uuid.uuid4()

    async with factory() as session:
        await region_cache.region_for(session, project_id)
        await region_cache.region_for(session, other_id)
    assert region_cache.cache_stats()["entries"] == 2

    region_cache.clear_project_region_cache(project_id)
    stats = region_cache.cache_stats()
    assert stats["entries"] == 1


@pytest.mark.asyncio
async def test_clear_cache_global(project_with_region) -> None:
    """clear_project_region_cache() with no args drops every entry."""
    project_id, _expected, factory = project_with_region

    async with factory() as session:
        await region_cache.region_for(session, project_id)
    assert region_cache.cache_stats()["entries"] == 1

    region_cache.clear_project_region_cache()
    assert region_cache.cache_stats()["entries"] == 0
