"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration: /api/v1/jobs/* status endpoints (RFC 34 §4 W0.1).

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
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests._pg import isolated_engine

# Celery is an optional dependency (the ``server`` extra, not ``dev``). The
# eager-dispatch fixtures here drive the Celery transport via get_celery_app /
# submit_job, so skip cleanly when the dep is absent rather than crashing
# collection.
pytest.importorskip("celery")

from app.core.job_runner import register_handler, submit_job, unregister_handler  # noqa: E402
from app.core.jobs import get_celery_app  # noqa: E402
from app.dependencies import get_current_user_id, get_current_user_payload  # noqa: E402
from app.modules.jobs.router import router as jobs_router  # noqa: E402


@pytest_asyncio.fixture
async def session_factory():
    """Session factory bound to a throwaway PostgreSQL database.

    The router and ``submit_job`` each open their own independent sessions
    from this factory on separate connections, and the tests rely on rows
    committed in one session being visible from another. That cross-connection
    durability needs a real engine, so we use ``isolated_engine`` (a clone of
    the schema-loaded template, dropped on teardown) rather than the
    transaction-rollback ``transactional_session`` primitive. The clone already
    carries the full schema, so no ``create_all`` is needed.
    """
    async with isolated_engine() as engine:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        yield maker


@pytest_asyncio.fixture
async def client(session_factory):
    """Tiny FastAPI app mounting only the jobs router.

    The router resolves its async session via ``app.modules.jobs.router._get_session_factory``;
    we monkey-patch that to point at the throwaway PostgreSQL factory created above.
    """
    app = FastAPI()
    app.include_router(jobs_router, prefix="/api/v1/jobs", tags=["Background Jobs"])

    # Every route on this router requires authentication, and all four are
    # role-gated (RequireRole("admin") in app/modules/jobs/router.py). That
    # check resolves the caller via get_current_user_payload, not
    # get_current_user_id — overriding only the latter leaves the role check
    # hitting the real dependency and failing auth (401) before a test ever
    # reaches the handler body. Override both so tests don't need to mint
    # real JWTs or satisfy the role check separately.
    app.dependency_overrides[get_current_user_id] = lambda: "00000000-0000-0000-0000-000000000001"
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": "00000000-0000-0000-0000-000000000001",
        "role": "admin",
        "permissions": ["admin"],
    }

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
    client,
    session_factory,
    eager_celery,
) -> None:
    def noop(job_run, payload):
        return {"done": True}

    register_handler("status_endpoint.noop", noop)

    with patch(
        "app.core.jobs_tasks._get_session_factory",
        return_value=session_factory,
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
    client,
    session_factory,
    eager_celery,
) -> None:
    def noop(job_run, payload):
        return {}

    register_handler("status_endpoint.noop", noop)

    with patch(
        "app.core.jobs_tasks._get_session_factory",
        return_value=session_factory,
    ):
        await submit_job(
            kind="status_endpoint.noop",
            payload={},
            session_factory=session_factory,
        )
        await submit_job(
            kind="status_endpoint.noop",
            payload={},
            session_factory=session_factory,
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
    client,
    session_factory,
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
    client,
    session_factory,
    eager_celery,
) -> None:
    """Cancel on a finished job is a 200 no-op (status unchanged)."""

    def noop(job_run, payload):
        return {}

    register_handler("status_endpoint.noop", noop)

    with patch(
        "app.core.jobs_tasks._get_session_factory",
        return_value=session_factory,
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
