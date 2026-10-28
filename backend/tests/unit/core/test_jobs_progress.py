"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Progress-update tests for the W0.1 job runner (RFC 34 §4 W0.1).

Contract:
    update_progress(job_run_id, percent, message) MUST atomically update
    the JobRun row. Out-of-order updates that would *decrease* progress
    must be silently clamped — we only ever advance forward (monotonic),
    so flaky workers that emit stale progress events don't roll back the
    UI's progress bar.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.job_run import JobRun
from app.core.job_runner import submit_job, update_progress
from tests._pg import isolated_engine


@pytest.fixture
async def session_factory():
    # The job runner opens its OWN independent sessions from this factory and
    # commits them; the tests then open separate sessions on separate
    # connections to read the committed rows back. That cross-connection
    # visibility needs a real engine, so use a throwaway, schema-loaded
    # PostgreSQL database (dropped on teardown) rather than the savepoint-based
    # transactional_session helper.
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def job_run(session_factory) -> JobRun:
    """Create a JobRun row to operate against."""
    with patch("app.core.job_runner._dispatch_to_celery") as mock_dispatch:
        mock_dispatch.return_value = "task-id"
        jr = await submit_job(
            kind="test.progress",
            payload={},
            session_factory=session_factory,
        )
    return jr


@pytest.mark.asyncio
async def test_update_progress_sets_percent(session_factory, job_run) -> None:
    await update_progress(
        job_run.id,
        percent=50,
        message="halfway",
        session_factory=session_factory,
    )
    async with session_factory() as s:
        row = (await s.execute(select(JobRun).where(JobRun.id == job_run.id))).scalar_one()
        assert row.progress_percent == 50


@pytest.mark.asyncio
async def test_update_progress_with_message_persists(session_factory, job_run) -> None:
    await update_progress(
        job_run.id,
        percent=25,
        message="quarter done",
        session_factory=session_factory,
    )
    async with session_factory() as s:
        row = (await s.execute(select(JobRun).where(JobRun.id == job_run.id))).scalar_one()
        # Message is recorded in the result_jsonb under "progress_message"
        # so it survives until the final result_jsonb gets written.
        assert row.progress_percent == 25
        assert row.result_jsonb is not None
        assert row.result_jsonb.get("progress_message") == "quarter done"


@pytest.mark.asyncio
async def test_progress_clamps_to_0_100(session_factory, job_run) -> None:
    """Out-of-range percents are clamped to [0, 100]."""
    await update_progress(
        job_run.id,
        percent=150,
        message=None,
        session_factory=session_factory,
    )
    async with session_factory() as s:
        row = (await s.execute(select(JobRun).where(JobRun.id == job_run.id))).scalar_one()
        assert row.progress_percent == 100

    await update_progress(
        job_run.id,
        percent=-10,
        message=None,
        session_factory=session_factory,
    )
    async with session_factory() as s:
        row = (await s.execute(select(JobRun).where(JobRun.id == job_run.id))).scalar_one()
        # Going down would be a regression, but we already established
        # the clamp at 100 — out-of-order updates must NOT decrease the
        # percent. See the next test for the explicit monotonic check.
        assert row.progress_percent == 100


@pytest.mark.asyncio
async def test_progress_is_monotonic(session_factory, job_run) -> None:
    """A later, lower update_progress call must NOT regress progress_percent."""
    await update_progress(
        job_run.id,
        percent=80,
        message="almost done",
        session_factory=session_factory,
    )
    # Out-of-order, stale progress event — must be ignored.
    await update_progress(
        job_run.id,
        percent=20,
        message="stale event",
        session_factory=session_factory,
    )
    async with session_factory() as s:
        row = (await s.execute(select(JobRun).where(JobRun.id == job_run.id))).scalar_one()
        assert row.progress_percent == 80


@pytest.mark.asyncio
async def test_progress_no_message_keeps_existing(session_factory, job_run) -> None:
    """update_progress(message=None) must not erase a previously-set message."""
    await update_progress(
        job_run.id,
        percent=10,
        message="phase 1",
        session_factory=session_factory,
    )
    await update_progress(
        job_run.id,
        percent=50,
        message=None,
        session_factory=session_factory,
    )
    async with session_factory() as s:
        row = (await s.execute(select(JobRun).where(JobRun.id == job_run.id))).scalar_one()
        assert row.progress_percent == 50
        # Previous message preserved (None is "no update", not "clear").
        assert row.result_jsonb.get("progress_message") == "phase 1"


@pytest.mark.asyncio
async def test_progress_unknown_jobrun_id_is_noop(session_factory) -> None:
    """update_progress on an unknown id must not raise — best-effort semantics."""
    import uuid

    # Should silently no-op, not raise, since the worker may have lost
    # the JobRun row (e.g., test cleanup) and we don't want to crash the
    # task on a benign race.
    await update_progress(
        uuid.uuid4(),
        percent=42,
        message="ghost",
        session_factory=session_factory,
    )
