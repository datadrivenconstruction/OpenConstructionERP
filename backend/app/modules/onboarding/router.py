# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Onboarding provisioning API (auto-mounted at /api/v1/onboarding).

The wizard POSTs the heavy first-run work here instead of awaiting it inline.
Each requested item becomes a background JobRun; the endpoint returns the job
ids immediately so the client can move the user on and poll for a progress bar.
Jobs are de-duplicated per user and item through an idempotency key, so a
double submit (or a retried request) reuses the running job rather than
starting a second import. A job that FAILED is not reused: provisioning the
same item again starts a fresh attempt.

Reading job state:

    GET  /jobs/        - the caller's onboarding jobs, newest first
    GET  /jobs/{id}    - one of the caller's onboarding jobs (404 otherwise)
    POST /status       - the caller's jobs among a list of ids (what the wizard polls)

The generic ``/api/v1/jobs`` routes stay admin-only, because ``JobRun`` has no
owner column. These routes can serve a non-admin because onboarding stamps the
caller's id into each job payload and every read here filters on it, together
with the onboarding job kinds, so one user can never read another's jobs, or
unrelated background work, by guessing ids.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.job_run import JobRun
from app.core.job_runner import submit_job
from app.dependencies import CurrentUserId, SessionDep
from app.modules.onboarding.handlers import KIND_INSTALL_DEMO, KIND_LOAD_CWICR
from app.modules.onboarding.schemas import (
    JobState,
    ProvisionRequest,
    ProvisionResponse,
    StatusRequest,
    StatusResponse,
)

router = APIRouter(tags=["onboarding"])
logger = logging.getLogger(__name__)

_ONBOARDING_KINDS = frozenset({KIND_LOAD_CWICR, KIND_INSTALL_DEMO})

# Job states after which a job is over and will not change again.
_FINISHED_BADLY = frozenset({"failed", "cancelled"})

# How many jobs ``GET /jobs/`` returns. A user provisions a handful per
# onboarding; the cap only stops a runaway client.
_LIST_LIMIT = 50


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _outcome(row: JobRun, result: dict[str, Any]) -> str | None:
    """The truthful result of a finished job, None while it is still running."""
    if row.status in _FINISHED_BADLY:
        return "failed"
    if row.status != "success":
        return None
    # Rows written before the handlers raised on failure recorded a failed load
    # as success with ``skipped``; read them for what they were.
    if result.get("skipped") is True:
        return "failed"
    if (_as_int(result.get("failed")) or 0) > 0 or result.get("resource_prices_error"):
        return "partial"
    return "completed"


def _job_state(row: JobRun) -> JobState:
    """Project a JobRun row into the owner-facing JobState."""
    result = row.result_jsonb or {}
    payload = row.payload_jsonb or {}
    outcome = _outcome(row, result)
    error: str | None = None
    if row.error_jsonb:
        error = str(row.error_jsonb.get("message") or "failed")
    elif outcome == "failed" and result.get("reason"):
        error = str(result.get("reason"))
    arg = payload.get("db_id") or payload.get("demo_id")
    return JobState(
        id=str(row.id),
        kind=row.kind,
        arg=str(arg) if arg is not None else None,
        state=row.status,
        outcome=outcome,
        pct=int(row.progress_percent or 0),
        message=result.get("progress_message"),
        error=error,
        imported=_as_int(result.get("imported")),
        total=_as_int(result.get("total_items")),
        failed_items=_as_int(result.get("failed")) or 0,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _owned_by(user_id: str):
    """SQL filter: onboarding jobs whose payload names ``user_id`` as owner."""
    return (
        JobRun.kind.in_(sorted(_ONBOARDING_KINDS)),
        JobRun.payload_jsonb["owner_user_id"].as_string() == str(user_id),
    )


async def _attempt_key(session: SessionDep, base_key: str) -> str:
    """The idempotency key for the next attempt at one onboarding item.

    ``submit_job`` hands back whatever row carries the key, in any state, so a
    failed load would otherwise be returned to every later provision call and
    the item could never be retried. A failed attempt passes the key on to the
    next one (``<key>:after:<failed id>``): still deterministic, so a double
    submit after a failure starts one retry, not two.
    """
    key = base_key
    # Bounded: each hop is a failed attempt the user asked for, but a loop
    # guard costs nothing.
    for _ in range(100):
        row = (await session.execute(select(JobRun).where(JobRun.idempotency_key == key))).scalar_one_or_none()
        if row is None or row.status not in _FINISHED_BADLY:
            return key
        key = f"{base_key}:after:{row.id}"
    return key


@router.post("/provision", response_model=ProvisionResponse)
async def provision(body: ProvisionRequest, user_id: CurrentUserId, session: SessionDep) -> ProvisionResponse:
    """Kick off the heavy first-run work as background jobs and return their ids.

    Idempotent per user and item while a job is running or has succeeded:
    re-provisioning the same region or sample reuses that job instead of
    importing twice. After a failure it starts a new attempt.
    """
    jobs: list[JobState] = []

    if body.region:
        key = await _attempt_key(session, f"onboarding:{user_id}:load_cwicr:{body.region}")
        row = await submit_job(
            KIND_LOAD_CWICR,
            {"db_id": body.region, "owner_user_id": user_id},
            idempotency_key=key,
        )
        jobs.append(_job_state(row))

    # dict.fromkeys de-dupes while preserving the wizard's order.
    for demo_id in dict.fromkeys(body.demo_ids):
        if not demo_id:
            continue
        key = await _attempt_key(session, f"onboarding:{user_id}:install_demo:{demo_id}")
        row = await submit_job(
            KIND_INSTALL_DEMO,
            {"demo_id": demo_id, "owner_user_id": user_id},
            idempotency_key=key,
        )
        jobs.append(_job_state(row))

    logger.info("onboarding: provisioned %d job(s) for user %s", len(jobs), user_id)
    return ProvisionResponse(jobs=jobs)


@router.get("/jobs/", response_model=StatusResponse)
async def list_jobs(user_id: CurrentUserId, session: SessionDep) -> StatusResponse:
    """List the caller's onboarding jobs, newest first."""
    stmt = select(JobRun).where(*_owned_by(user_id)).order_by(JobRun.created_at.desc()).limit(_LIST_LIMIT)
    rows = (await session.execute(stmt)).scalars().all()
    return StatusResponse(jobs=[_job_state(row) for row in rows])


@router.get("/jobs/{job_id}", response_model=JobState)
async def get_job(job_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> JobState:
    """Return one of the caller's onboarding jobs.

    404 when the id is unknown, belongs to another user, or is not an
    onboarding job: the three are indistinguishable on purpose.
    """
    stmt = select(JobRun).where(JobRun.id == job_id, *_owned_by(user_id))
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Onboarding job not found")
    return _job_state(row)


@router.post("/status", response_model=StatusResponse)
async def job_status(
    body: StatusRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> StatusResponse:
    """Return live state for the caller's provisioning jobs, looked up by id."""
    ids: list[uuid.UUID] = []
    for raw in body.ids:
        try:
            ids.append(uuid.UUID(str(raw)))
        except (ValueError, TypeError):
            continue
    if not ids:
        return StatusResponse(jobs=[])

    stmt = select(JobRun).where(JobRun.id.in_(ids), *_owned_by(user_id))
    rows = (await session.execute(stmt)).scalars().all()
    return StatusResponse(jobs=[_job_state(row) for row in rows])
