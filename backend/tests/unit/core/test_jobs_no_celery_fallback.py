"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Regression: the job runner must run in-process when Celery is absent.

Celery/kombu is an OPTIONAL extra (``celery[redis]`` in
``[project.optional-dependencies]``); the default ``pip install`` and the
shipped wheel run the lightweight, Redis-optional deploy without it. Before
this fix ``_dispatch_to_celery`` imported ``kombu`` unconditionally, so on a
Celery-less install every background job (pipeline run, AI estimate, geo-hub
tiling, …) raised ``ModuleNotFoundError: No module named 'kombu'``. That is
NOT a :class:`BrokerUnavailableError`, so ``submit_job`` never fell back to the
in-process runner - it hit the generic ``except``, marked the JobRun failed and
re-raised, surfacing as a hard 500 on ``POST /api/v1/pipelines/{id}/run``.

Every pre-existing job/pipeline test patches ``_dispatch_to_celery`` with a mock
return value, so this exact path - the transport imports themselves failing -
was never exercised. These two tests pin it:

1. a missing transport maps to :class:`BrokerUnavailableError` (unit, no DB);
2. ``submit_job`` then runs the handler IN-PROCESS and the JobRun reaches
   ``success`` without the caller ever seeing an exception (end-to-end).
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.job_run import JobRun
from app.core.job_runner import (
    BrokerUnavailableError,
    _dispatch_to_celery,
    register_handler,
    submit_job,
    unregister_handler,
)
from tests._pg import isolated_engine


@pytest_asyncio.fixture
async def session_factory():
    """Async session factory bound to a per-test throwaway PostgreSQL database.

    ``submit_job`` and the in-process fallback open their own sessions from the
    factory and commit, and the assertions re-read the committed rows from
    separate sessions - so a real throwaway database (not a savepoint-rolled-back
    shared session) is required for the cross-connection commit visibility.
    """
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def test_dispatch_to_celery_maps_missing_celery_to_broker_unavailable(monkeypatch) -> None:
    """A Celery-less install must surface as :class:`BrokerUnavailableError`.

    We force the transport imports to fail (even when the test env has the
    ``celery`` extra installed) by hiding the modules, so the assertion holds in
    CI regardless of whether the optional dependency is present.
    """
    monkeypatch.setitem(sys.modules, "kombu", None)
    monkeypatch.setitem(sys.modules, "kombu.exceptions", None)
    monkeypatch.setitem(sys.modules, "celery", None)

    with pytest.raises(BrokerUnavailableError):
        _dispatch_to_celery(uuid.uuid4())


@pytest.mark.asyncio
async def test_submit_job_runs_in_process_when_transport_unavailable(session_factory) -> None:
    """No broker + no Celery => the job still runs in-process, no 500.

    Patches ``_dispatch_to_celery`` to raise :class:`BrokerUnavailableError`
    (exactly what the import guard now does on a Celery-less install) and
    asserts ``submit_job`` does not propagate it: it returns the pending row and
    drives the registered handler through the in-process lifecycle to
    ``success``.
    """
    ran: dict[str, str] = {}

    async def _handler(job: JobRun, payload: dict) -> dict:
        ran["job_id"] = str(job.id)
        return {"echo": payload.get("v")}

    register_handler("test.inproc_fallback", _handler)
    try:
        with patch(
            "app.core.job_runner._dispatch_to_celery",
            side_effect=BrokerUnavailableError("no celery installed"),
        ):
            row = await submit_job(
                kind="test.inproc_fallback",
                payload={"v": 42},
                session_factory=session_factory,
            )

        # The caller must get the pending row back, NOT an exception.
        assert row is not None
        assert row.kind == "test.inproc_fallback"

        # The fire-and-forget in-process task finishes on this same loop; poll
        # the row until it reaches a terminal state (bounded so a genuine hang
        # fails fast rather than blocking the suite).
        fresh: JobRun | None = None
        for _ in range(100):
            await asyncio.sleep(0.05)
            async with session_factory() as s:
                fresh = await s.get(JobRun, row.id)
                if fresh is not None and fresh.status in ("success", "failed"):
                    break

        assert fresh is not None
        assert fresh.status == "success", f"status={fresh.status} error={fresh.error_jsonb}"
        assert (fresh.result_jsonb or {}).get("echo") == 42
        assert ran.get("job_id") == str(row.id)
    finally:
        unregister_handler("test.inproc_fallback")
