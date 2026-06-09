"""Idempotency tests for the W0.1 job runner (RFC 34 §4 W0.1).

Contract:
    submit_job() with the same ``idempotency_key`` MUST return the same
    JobRun row, regardless of how many concurrent callers race the
    submission. No duplicate ``oe_job_run`` rows may be inserted, and
    only ONE Celery dispatch must be queued.

This test deliberately mocks the Celery dispatch — we are testing the
DB-side idempotency contract, not Celery delivery. The integration
test ``test_jobs_celery_redis.py`` covers the dispatch path end-to-end.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.job_run import JobRun
from app.core.job_runner import submit_job
from tests._pg import isolated_database_url, isolated_engine


@pytest_asyncio.fixture
async def session_factory():
    """Async session factory bound to a per-test throwaway PostgreSQL database.

    ``submit_job`` opens its own sessions from the factory, commits, and
    re-reads the committed rows from separate sessions — and the cross-thread
    test below spins up a fresh event loop per thread that must see those
    commits. A real throwaway database (cloned from the schema-loaded template)
    provides the required cross-connection commit visibility, which a
    savepoint-rolled-back shared session cannot.
    """
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_same_idempotency_key_returns_existing_jobrun(session_factory) -> None:
    """Second call with the same key MUST return the original JobRun id."""
    with patch("app.core.job_runner._dispatch_to_celery") as mock_dispatch:
        mock_dispatch.return_value = "celery-task-id-1"

        first = await submit_job(
            kind="test.noop",
            payload={"x": 1},
            idempotency_key="run-001",
            session_factory=session_factory,
        )
        second = await submit_job(
            kind="test.noop",
            payload={"x": 2},  # different payload — must still de-dupe
            idempotency_key="run-001",
            session_factory=session_factory,
        )

    assert first.id == second.id
    assert first.idempotency_key == "run-001"
    # Celery dispatch must only fire ONCE for the de-duped key.
    assert mock_dispatch.call_count == 1


@pytest.mark.asyncio
async def test_different_idempotency_keys_create_distinct_jobs(session_factory) -> None:
    """Different keys must produce distinct JobRuns."""
    with patch("app.core.job_runner._dispatch_to_celery") as mock_dispatch:
        mock_dispatch.return_value = "celery-task-id"

        a = await submit_job(
            kind="test.noop",
            payload={},
            idempotency_key="key-A",
            session_factory=session_factory,
        )
        b = await submit_job(
            kind="test.noop",
            payload={},
            idempotency_key="key-B",
            session_factory=session_factory,
        )

    assert a.id != b.id
    assert mock_dispatch.call_count == 2


@pytest.mark.asyncio
async def test_no_idempotency_key_creates_new_jobrun_each_time(session_factory) -> None:
    """Missing idempotency_key means every submit_job creates a fresh row."""
    with patch("app.core.job_runner._dispatch_to_celery") as mock_dispatch:
        mock_dispatch.return_value = "celery-task-id"

        a = await submit_job(
            kind="test.noop",
            payload={},
            session_factory=session_factory,
        )
        b = await submit_job(
            kind="test.noop",
            payload={},
            session_factory=session_factory,
        )

    assert a.id != b.id
    assert mock_dispatch.call_count == 2


@pytest.mark.asyncio
async def test_concurrent_submits_with_same_key_dedupe(session_factory) -> None:
    """Five concurrent submit_job calls on the same key must collapse to one row."""
    with patch("app.core.job_runner._dispatch_to_celery") as mock_dispatch:
        mock_dispatch.return_value = "celery-task-id"

        async def submit() -> JobRun:
            return await submit_job(
                kind="test.noop",
                payload={"i": 1},
                idempotency_key="concurrent-key",
                session_factory=session_factory,
            )

        results = await asyncio.gather(
            submit(),
            submit(),
            submit(),
            submit(),
            submit(),
        )

    ids = {r.id for r in results}
    assert len(ids) == 1, f"Expected 1 distinct JobRun id, got {len(ids)}: {ids}"

    # And only one DB row exists for that key.
    async with session_factory() as s:
        from sqlalchemy import select

        rows = (await s.execute(select(JobRun).where(JobRun.idempotency_key == "concurrent-key"))).scalars().all()
        assert len(rows) == 1


def test_idempotency_key_uniqueness_across_threads(monkeypatch) -> None:
    """Same key used from multiple threads (sync wrapper) must not duplicate.

    Each thread spins its own event loop and builds its OWN engine bound to
    that loop, all pointing at the SAME throwaway database. The contract here
    is that the UNIQUE constraint on ``idempotency_key`` plus the
    IntegrityError-recovery branch in ``submit_job`` collapse every concurrent
    caller onto one row.

    This is a synchronous test on purpose. asyncpg connections (and
    SQLAlchemy's async pool, with its first-connect ``asyncio.Lock``) are
    bound to the loop that first touches them. Sharing one engine across the
    five worker loops deadlocks: the lock binds to whichever loop wins, and
    the others hang forever on a cross-loop future, then trip the
    pytest-timeout signal at 300s. Giving each thread its own loop-local
    engine against the shared database keeps the cross-connection commit
    visibility the dedup contract needs without any cross-loop sharing.

    NOTE: We use ``monkeypatch.setattr`` (process-wide for the test
    duration) rather than ``with patch(...)`` inside each thread, because
    ``unittest.mock.patch`` is NOT thread-safe — concurrent enter/exit
    races leave the module attribute swapped permanently if two threads
    overlap, which leaks the mock into later tests in the same session.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    def fake_dispatch(_job_id):
        return "thread-task-id"

    monkeypatch.setattr(
        "app.core.job_runner._dispatch_to_celery",
        fake_dispatch,
    )

    with isolated_database_url() as db_url:

        def submit_sync() -> str:
            # A fresh loop per thread, and a fresh engine + session factory
            # built INSIDE that loop, so the asyncpg connection and the
            # pool's first-connect lock bind to this thread's loop only.
            # NullPool keeps no connection alive past the loop's teardown.
            loop = asyncio.new_event_loop()

            async def _run() -> str:
                engine = create_async_engine(db_url, future=True, poolclass=NullPool)
                factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
                try:
                    jr = await submit_job(
                        kind="test.noop",
                        payload={},
                        idempotency_key="threaded-key",
                        session_factory=factory,
                    )
                    return str(jr.id)
                finally:
                    await engine.dispose()

            try:
                return loop.run_until_complete(_run())
            finally:
                loop.close()

        with ThreadPoolExecutor(max_workers=5) as pool:
            ids = list(pool.map(lambda _: submit_sync(), range(5)))

    # Every thread must observe the same JobRun id.
    assert len(set(ids)) == 1
