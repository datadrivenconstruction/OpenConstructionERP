"""Handler-registry tests for the W0.1 job runner (RFC 34 §4 W0.1).

Contract:
    register_handler(kind, handler) attaches a callable to a JobRun.kind.
    The dispatch task looks up the handler by kind and calls it with
    (JobRun, payload). On success the JobRun.status flips to "success"
    with result_jsonb populated. On unknown kind, the dispatcher marks
    the JobRun "failed" without raising.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.job_run import JobRun
from app.core.job_runner import (
    _dispatch_job_sync,
    register_handler,
    submit_job,
    unregister_handler,
)
from app.database import Base


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[JobRun.__table__])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


@pytest.fixture(autouse=True)
def _clean_registry():
    """Clear handler registrations between tests so each starts clean."""
    yield
    for kind in ("test.noop", "test.fail", "test.echo"):
        unregister_handler(kind)


@pytest.mark.asyncio
async def test_register_handler_then_dispatch_success(session_factory) -> None:
    captured: dict = {}

    def noop_handler(job_run: JobRun, payload: dict) -> dict:
        captured["job_run_id"] = str(job_run.id)
        captured["payload"] = payload
        return {"ok": True, "echoed": payload.get("x")}

    register_handler("test.noop", noop_handler)

    with patch("app.core.job_runner._dispatch_to_celery") as mock_dispatch:
        mock_dispatch.return_value = "task-id"
        jr = await submit_job(
            kind="test.noop",
            payload={"x": 42},
            session_factory=session_factory,
        )

    # Run the dispatch synchronously (simulates a worker picking up the task).
    await _dispatch_job_sync(jr.id, session_factory=session_factory)

    async with session_factory() as s:
        row = (await s.execute(select(JobRun).where(JobRun.id == jr.id))).scalar_one()
        assert row.status == "success"
        assert row.result_jsonb is not None
        assert row.result_jsonb["ok"] is True
        assert row.result_jsonb["echoed"] == 42
        assert row.completed_at is not None
        assert row.started_at is not None

    assert captured["payload"] == {"x": 42}
    assert captured["job_run_id"] == str(jr.id)


@pytest.mark.asyncio
async def test_unknown_kind_marks_jobrun_failed(session_factory) -> None:
    with patch("app.core.job_runner._dispatch_to_celery") as mock_dispatch:
        mock_dispatch.return_value = "task-id"
        jr = await submit_job(
            kind="test.no.handler.registered",
            payload={},
            session_factory=session_factory,
        )

    # Should not raise — failures are recorded in the row, not propagated.
    await _dispatch_job_sync(jr.id, session_factory=session_factory)

    async with session_factory() as s:
        row = (await s.execute(select(JobRun).where(JobRun.id == jr.id))).scalar_one()
        assert row.status == "failed"
        assert row.error_jsonb is not None
        assert "no handler" in row.error_jsonb["message"].lower()


@pytest.mark.asyncio
async def test_handler_exception_marks_jobrun_failed_with_traceback(
    session_factory,
) -> None:
    def boom_handler(job_run: JobRun, payload: dict) -> dict:
        raise RuntimeError("synthetic explosion")

    register_handler("test.fail", boom_handler)

    with patch("app.core.job_runner._dispatch_to_celery") as mock_dispatch:
        mock_dispatch.return_value = "task-id"
        jr = await submit_job(
            kind="test.fail",
            payload={},
            session_factory=session_factory,
        )

    await _dispatch_job_sync(jr.id, session_factory=session_factory)

    async with session_factory() as s:
        row = (await s.execute(select(JobRun).where(JobRun.id == jr.id))).scalar_one()
        assert row.status == "failed"
        assert row.error_jsonb["type"] == "RuntimeError"
        assert "synthetic explosion" in row.error_jsonb["message"]
        # Traceback is captured for debuggability.
        assert "traceback" in row.error_jsonb
        assert row.error_jsonb["traceback"]


@pytest.mark.asyncio
async def test_register_handler_overrides_previous(session_factory) -> None:
    def v1(job_run: JobRun, payload: dict) -> dict:
        return {"version": 1}

    def v2(job_run: JobRun, payload: dict) -> dict:
        return {"version": 2}

    register_handler("test.echo", v1)
    register_handler("test.echo", v2)  # overrides

    with patch("app.core.job_runner._dispatch_to_celery") as mock_dispatch:
        mock_dispatch.return_value = "task-id"
        jr = await submit_job(
            kind="test.echo",
            payload={},
            session_factory=session_factory,
        )

    await _dispatch_job_sync(jr.id, session_factory=session_factory)

    async with session_factory() as s:
        row = (await s.execute(select(JobRun).where(JobRun.id == jr.id))).scalar_one()
        assert row.result_jsonb["version"] == 2


@pytest.mark.asyncio
async def test_dispatch_marks_status_started_then_success(session_factory) -> None:
    """Status transitions: pending → started → success."""
    seen_during_handler: dict = {}

    def slow_handler(job_run: JobRun, payload: dict) -> dict:
        seen_during_handler["status_at_call_time"] = job_run.status
        return {"ok": True}

    register_handler("test.echo", slow_handler)

    with patch("app.core.job_runner._dispatch_to_celery") as mock_dispatch:
        mock_dispatch.return_value = "task-id"
        jr = await submit_job(
            kind="test.echo",
            payload={},
            session_factory=session_factory,
        )

    # Pre-dispatch: status should be pending.
    async with session_factory() as s:
        row = (await s.execute(select(JobRun).where(JobRun.id == jr.id))).scalar_one()
        assert row.status == "pending"

    await _dispatch_job_sync(jr.id, session_factory=session_factory)

    # Handler observed status="started"
    assert seen_during_handler["status_at_call_time"] == "started"

    # Post-dispatch: success.
    async with session_factory() as s:
        row = (await s.execute(select(JobRun).where(JobRun.id == jr.id))).scalar_one()
        assert row.status == "success"
