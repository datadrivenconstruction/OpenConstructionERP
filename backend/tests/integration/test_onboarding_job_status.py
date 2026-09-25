"""The onboarding job status a client can wait on, and how truthful it is.

A client that provisions a country cost base has to be able to wait for it to
finish and learn how it finished. ``GET /api/v1/onboarding/jobs/`` answered 404,
and the generic ``/api/v1/jobs`` routes are admin-only because ``JobRun`` has no
owner column, so a normal user had nothing to poll by listing. These tests pin:

* the caller's onboarding jobs can be listed and read by id, and nobody else's
  (or unrelated background work) can, whatever id is guessed;
* a finished job states its outcome: ``completed``, ``partial`` with the number
  of items left out, or ``failed`` with the reason;
* a failed item can be provisioned again. ``submit_job`` returns whatever row
  carries the idempotency key, so the failed job used to come back forever.

Runs on a throwaway PostgreSQL database: the owner filter is a JSON path in SQL.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.job_run import JobRun
from app.dependencies import get_current_user_id, get_session
from app.modules.onboarding import router as onboarding_router
from app.modules.onboarding.handlers import KIND_INSTALL_DEMO, KIND_LOAD_CWICR
from tests._pg import isolated_engine

ALICE = "00000000-0000-4000-8000-0000000000a1"
BOB = "00000000-0000-4000-8000-0000000000b0"


@pytest_asyncio.fixture
async def maker():
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _client(maker: async_sessionmaker, user_id: str) -> AsyncClient:
    app = FastAPI()
    app.include_router(onboarding_router.router, prefix="/api/v1/onboarding")

    async def _session():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _job(
    maker: async_sessionmaker,
    *,
    owner: str,
    kind: str = KIND_LOAD_CWICR,
    status: str = "success",
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    key: str | None = None,
    arg: str = "ENG_TORONTO",
) -> uuid.UUID:
    row = JobRun(
        id=uuid.uuid4(),
        kind=kind,
        status=status,
        progress_percent=100 if status == "success" else 15,
        payload_jsonb={"db_id": arg, "owner_user_id": owner},
        result_jsonb=result,
        error_jsonb=error,
        idempotency_key=key,
    )
    async with maker() as session:
        session.add(row)
        await session.commit()
    return row.id


async def test_the_callers_jobs_are_listed_with_a_truthful_outcome(maker) -> None:
    done = await _job(maker, owner=ALICE, result={"imported": 55719, "total_items": 55719, "failed": 0})
    partial = await _job(maker, owner=ALICE, result={"imported": 55717, "total_items": 55717, "failed": 2})
    failed = await _job(
        maker,
        owner=ALICE,
        status="failed",
        error={"type": "ProvisioningError", "message": "CWICR database 'XX' not found.", "traceback": "..."},
    )
    running = await _job(maker, owner=ALICE, status="started")
    # A row an older build wrote for a failed load: success with ``skipped``.
    legacy = await _job(maker, owner=ALICE, result={"skipped": True, "reason": "download failed"})
    await _job(maker, owner=BOB)
    await _job(maker, owner=ALICE, kind="closeout.build")

    async with _client(maker, ALICE) as client:
        resp = await client.get("/api/v1/onboarding/jobs/")
    assert resp.status_code == 200, resp.text
    by_id = {j["id"]: j for j in resp.json()["jobs"]}

    assert set(by_id) == {str(done), str(partial), str(failed), str(running), str(legacy)}
    assert by_id[str(done)]["outcome"] == "completed"
    assert by_id[str(done)]["imported"] == 55719
    assert by_id[str(partial)]["outcome"] == "partial"
    assert by_id[str(partial)]["failed_items"] == 2
    assert by_id[str(failed)]["outcome"] == "failed"
    assert by_id[str(failed)]["error"] == "CWICR database 'XX' not found."
    assert by_id[str(running)]["outcome"] is None
    assert by_id[str(legacy)]["outcome"] == "failed"
    assert by_id[str(legacy)]["error"] == "download failed"
    # The traceback never crosses the API.
    assert "traceback" not in resp.text


async def test_one_job_is_read_by_id_and_only_by_its_owner(maker) -> None:
    mine = await _job(maker, owner=ALICE)
    theirs = await _job(maker, owner=BOB)
    unrelated = await _job(maker, owner=ALICE, kind="closeout.build")

    async with _client(maker, ALICE) as client:
        ok = await client.get(f"/api/v1/onboarding/jobs/{mine}")
        other = await client.get(f"/api/v1/onboarding/jobs/{theirs}")
        wrong_kind = await client.get(f"/api/v1/onboarding/jobs/{unrelated}")
        unknown = await client.get(f"/api/v1/onboarding/jobs/{uuid.uuid4()}")

    assert ok.status_code == 200, ok.text
    assert ok.json()["id"] == str(mine)
    assert ok.json()["outcome"] == "completed"
    assert (other.status_code, wrong_kind.status_code, unknown.status_code) == (404, 404, 404)


async def test_status_by_ids_still_filters_to_the_caller(maker) -> None:
    mine = await _job(maker, owner=ALICE, kind=KIND_INSTALL_DEMO, arg="demo-1")
    theirs = await _job(maker, owner=BOB)
    async with _client(maker, ALICE) as client:
        resp = await client.post("/api/v1/onboarding/status", json={"ids": [str(mine), str(theirs), "nope"]})
    assert resp.status_code == 200, resp.text
    assert [j["id"] for j in resp.json()["jobs"]] == [str(mine)]


@pytest.fixture
def submitted(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the idempotency keys provision submits, without dispatching work."""
    keys: list[str] = []

    async def _submit(kind: str, payload: dict[str, Any], *, idempotency_key: str | None = None, **_: Any) -> JobRun:
        keys.append(idempotency_key or "")
        return JobRun(id=uuid.uuid4(), kind=kind, status="pending", progress_percent=0, payload_jsonb=payload)

    monkeypatch.setattr(onboarding_router, "submit_job", _submit)
    return keys


async def test_a_failed_load_can_be_provisioned_again(maker, submitted: list[str]) -> None:
    base = f"onboarding:{ALICE}:load_cwicr:ENG_TORONTO"
    first = await _job(maker, owner=ALICE, status="failed", key=base)

    async with _client(maker, ALICE) as client:
        resp = await client.post("/api/v1/onboarding/provision", json={"region": "ENG_TORONTO"})
    assert resp.status_code == 200, resp.text
    assert submitted == [f"{base}:after:{first}"]

    # A second failure hands the key on again, and a running retry is reused.
    second = await _job(maker, owner=ALICE, status="failed", key=f"{base}:after:{first}")
    await _job(maker, owner=ALICE, status="started", key=f"{base}:after:{second}")
    async with _client(maker, ALICE) as client:
        await client.post("/api/v1/onboarding/provision", json={"region": "ENG_TORONTO"})
    assert submitted[-1] == f"{base}:after:{second}"


async def test_a_running_or_finished_load_is_reused(maker, submitted: list[str]) -> None:
    base = f"onboarding:{ALICE}:load_cwicr:ENG_TORONTO"
    await _job(maker, owner=ALICE, status="success", key=base)
    async with _client(maker, ALICE) as client:
        await client.post("/api/v1/onboarding/provision", json={"region": "ENG_TORONTO"})
    assert submitted == [base]
