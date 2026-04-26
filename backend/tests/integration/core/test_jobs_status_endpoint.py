"""Integration: /api/v1/jobs/* status endpoints (RFC 34 §4 W0.1).

Verifies that the read-only status surface for the job runner works
end-to-end via the FastAPI test client. We mount only the jobs router
and a minimal app — keeps the test fast and avoids pulling in the
full module loader.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.job_run import JobRun
from app.core.job_runner import register_handler, submit_job, unregister_handler
from app.core.jobs import get_celery_app
from app.database import Base
from app.modules.jobs.router import router as jobs_router


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[JobRun.__table__])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    """Tiny FastAPI app mounting only the jobs router.

    The router resolves its async session via ``app.modules.jobs.router._get_session_factory``;
    we monkey-patch that to point at the in-memory SQLite created above.
    """
    app = FastAPI()
    app.include_router(jobs_router, prefix="/api/v1/jobs", tags=["Background Jobs"])

    with patch("app.modules.jobs.router._get_session_factory", return_value=session_factory):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture
def eager_celery():
    app = get_celery_app()
    prev_eager = app.conf.task_always_eager
    prev_prop = app.conf.task_eager_propagates
    app.conf.task_always_eager = True
    app.conf.task_eager_propagates = True
    yield app
    app.conf.task_always_eager = prev_eager
    app.conf.task_eager_propagates = prev_prop


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    for kind in ("status_endpoint.noop", "status_endpoint.long"):
        unregister_handler(kind)


@pytest.mark.asyncio
async def test_get_job_returns_404_for_unknown_id(client) -> None:
    resp = await client.get(f"/api/v1/jobs/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_job_returns_status_after_eager_dispatch(
    client, session_factory, eager_celery,
) -> None:
    def noop(job_run, payload):
        return {"done": True}

    register_handler("status_endpoint.noop", noop)

    with patch(
        "app.core.jobs_tasks._get_session_factory", return_value=session_factory,
    ):
        jr = await submit_job(
            kind="status_endpoint.noop",
            payload={},
            session_factory=session_factory,
        )

    resp = await client.get(f"/api/v1/jobs/{jr.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(jr.id)
    assert body["kind"] == "status_endpoint.noop"
    # In eager mode the job has already run by the time submit_job returns.
    assert body["status"] == "success"
    assert body["progress_percent"] in (0, 100)
    assert body["result"] == {"done": True}
    assert body["error"] is None


@pytest.mark.asyncio
async def test_list_jobs_supports_kind_filter(
    client, session_factory, eager_celery,
) -> None:
    def noop(job_run, payload):
        return {}

    register_handler("status_endpoint.noop", noop)

    with patch(
        "app.core.jobs_tasks._get_session_factory", return_value=session_factory,
    ):
        await submit_job(
            kind="status_endpoint.noop", payload={}, session_factory=session_factory,
        )
        await submit_job(
            kind="status_endpoint.noop", payload={}, session_factory=session_factory,
        )

    resp = await client.get("/api/v1/jobs?kind=status_endpoint.noop&limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 2
    assert all(item["kind"] == "status_endpoint.noop" for item in body["items"])


@pytest.mark.asyncio
async def test_list_jobs_clamps_limit_to_max(client, session_factory) -> None:
    """limit=500 must be clamped to the documented max of 200."""
    resp = await client.get("/api/v1/jobs?limit=500")
    assert resp.status_code == 200
    body = resp.json()
    assert body["limit"] == 200


@pytest.mark.asyncio
async def test_cancel_pending_job_marks_cancelled(
    client, session_factory,
) -> None:
    """Cancel on a still-pending job must transition status to 'cancelled'."""
    # Submit but do NOT enable eager mode → JobRun stays pending.
    with patch("app.core.job_runner._dispatch_to_celery") as mock_dispatch:
        mock_dispatch.return_value = "celery-task-id"
        jr = await submit_job(
            kind="status_endpoint.long",
            payload={},
            session_factory=session_factory,
        )

    resp = await client.post(f"/api/v1/jobs/{jr.id}/cancel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_already_succeeded_job_is_noop(
    client, session_factory, eager_celery,
) -> None:
    """Cancel on a finished job is a 200 no-op (status unchanged)."""

    def noop(job_run, payload):
        return {}

    register_handler("status_endpoint.noop", noop)

    with patch(
        "app.core.jobs_tasks._get_session_factory", return_value=session_factory,
    ):
        jr = await submit_job(
            kind="status_endpoint.noop",
            payload={},
            session_factory=session_factory,
        )

    resp = await client.post(f"/api/v1/jobs/{jr.id}/cancel")
    assert resp.status_code == 200
    body = resp.json()
    # Still success — cancel doesn't reverse a completed job.
    assert body["status"] == "success"
