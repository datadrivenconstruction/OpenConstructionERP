"""Integration: Celery happy-path with eager mode (RFC 34 §4 W0.1).

Why eager mode and not testcontainers Redis?
    Real testcontainers Redis adds a 3-5 s container spin-up per test
    run on Windows + macOS dev machines. ``CELERY_TASK_ALWAYS_EAGER``
    runs the task synchronously inside the test process, which is
    sufficient for verifying the dispatch task wiring and the JobRun
    row lifecycle. The full Redis end-to-end check happens at deploy
    time via ``make dev`` + the W0.1 acceptance Playwright test.

If testcontainers Redis is available later, lift this test to a
``test_jobs_celery_redis_real.py`` companion gated on a marker.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.job_run import JobRun
from app.core.job_runner import register_handler, submit_job, unregister_handler
from app.core.jobs import get_celery_app
from app.database import Base


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[JobRun.__table__])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


@pytest.fixture
def eager_celery():
    """Force the Celery app into eager (synchronous) mode for the test."""
    app = get_celery_app()
    prev_eager = app.conf.task_always_eager
    prev_propagates = app.conf.task_eager_propagates
    app.conf.task_always_eager = True
    app.conf.task_eager_propagates = True
    yield app
    app.conf.task_always_eager = prev_eager
    app.conf.task_eager_propagates = prev_propagates


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    for kind in ("celery_int.echo", "celery_int.fail"):
        unregister_handler(kind)


@pytest.mark.asyncio
async def test_celery_eager_dispatch_runs_handler_to_completion(
    session_factory, eager_celery,
) -> None:
    """In eager mode, submit_job triggers the dispatch task inline.

    The JobRun must be marked success without the test having to
    explicitly call _dispatch_job_sync.
    """

    def echo_handler(job_run: JobRun, payload: dict) -> dict:
        return {"echoed": payload.get("msg", "")}

    register_handler("celery_int.echo", echo_handler)

    # Patch the session factory used inside the dispatch task so the
    # eager worker reads our in-memory SQLite (not the global one).
    with patch("app.core.jobs_tasks._get_session_factory", return_value=session_factory):
        jr = await submit_job(
            kind="celery_int.echo",
            payload={"msg": "hello"},
            session_factory=session_factory,
        )

    async with session_factory() as s:
        row = (await s.execute(select(JobRun).where(JobRun.id == jr.id))).scalar_one()
        assert row.status == "success"
        assert row.result_jsonb["echoed"] == "hello"
        assert row.celery_task_id is not None


@pytest.mark.asyncio
async def test_celery_eager_dispatch_records_failure(
    session_factory, eager_celery,
) -> None:
    """A handler exception in eager mode lands in error_jsonb, not as a raise."""

    def fail_handler(job_run: JobRun, payload: dict) -> dict:
        raise ValueError("integration boom")

    register_handler("celery_int.fail", fail_handler)

    with patch("app.core.jobs_tasks._get_session_factory", return_value=session_factory):
        jr = await submit_job(
            kind="celery_int.fail",
            payload={},
            session_factory=session_factory,
        )

    async with session_factory() as s:
        row = (await s.execute(select(JobRun).where(JobRun.id == jr.id))).scalar_one()
        assert row.status == "failed"
        assert row.error_jsonb["type"] == "ValueError"
        assert "integration boom" in row.error_jsonb["message"]


def test_celery_app_singleton_exposes_required_config() -> None:
    """The shared Celery app must carry RFC 34 W0.1 configuration."""
    app = get_celery_app()
    assert app.main == "oe_jobs"
    assert app.conf.task_serializer == "json"
    assert app.conf.result_serializer == "json"
    assert "json" in app.conf.accept_content
    assert app.conf.timezone == "UTC"
    assert app.conf.enable_utc is True
    assert app.conf.task_track_started is True
    assert app.conf.task_time_limit == 600
    assert app.conf.worker_prefetch_multiplier == 1


def test_celery_app_registers_dispatch_task() -> None:
    """The dispatch task is registered on the canonical Celery app."""
    app = get_celery_app()
    assert "oe.dispatch_job" in app.tasks
